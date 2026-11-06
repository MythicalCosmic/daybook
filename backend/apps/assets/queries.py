"""Reading fixed assets: the register with each asset's value, its schedule, and the reports
an owner plans with. Branch-bound: every function takes `branch_ids` (None = every branch);
an asset without a branch is seen only with every branch.

Values come from the posted history (`DepreciationEntry`), so the register adds up to what
Finance holds; what lies ahead comes from the engine (`posting.schedule_of`).
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import DecimalField, F, OuterRef, Q, QuerySet, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from apps.assets import conf, engine, posting
from apps.assets.models import (
    Asset,
    AssetAssignment,
    AssetCategory,
    AssetEvent,
    DepreciationEntry,
)
from apps.core.money import quantize

ZERO = Decimal("0")
MONEY = DecimalField(max_digits=18, decimal_places=2)
LIVE = ~Q(status=Asset.Status.DISPOSED)


def scoped(company, *, branch_ids: list[int] | None) -> QuerySet[Asset]:
    rows = Asset.objects.for_company(company)
    if branch_ids is not None:
        rows = rows.filter(branch_id__in=branch_ids)
    return rows


def _sum_of(model, **filters):
    return Coalesce(
        Subquery(
            model.objects.filter(asset=OuterRef("pk"), **filters)
            .values("asset")
            .annotate(total=Sum("amount"))
            .values("total")[:1],
            output_field=MONEY,
        ),
        Value(ZERO),
        output_field=MONEY,
    )


def with_values(rows: QuerySet[Asset]) -> QuerySet[Asset]:
    """Each asset with `accumulated` (depreciation posted, the old books' too), `added`
    (improvements), `written_down` and `book` (what it is worth now)."""
    return rows.annotate(
        accumulated=_sum_of(DepreciationEntry),
        added=_sum_of(AssetEvent, kind=AssetEvent.Kind.ADDITION),
        written_down=_sum_of(AssetEvent, kind=AssetEvent.Kind.IMPAIRMENT),
        last_amount=Coalesce(
            Subquery(
                DepreciationEntry.objects.filter(asset=OuterRef("pk"), opening=False)
                .order_by("-month")
                .values("amount")[:1],
                output_field=MONEY,
            ),
            Value(ZERO),
            output_field=MONEY,
        ),
    ).annotate(book=F("cost") + F("added") - F("written_down") - F("accumulated"))


def register(
    company,
    *,
    branch_ids: list[int] | None,
    q: str = "",
    status: str = "",
    category: int | None = None,
    branch: int | None = None,
    custodian: int | None = None,
    include_disposed: bool = False,
) -> QuerySet[Asset]:
    rows = scoped(company, branch_ids=branch_ids).select_related(
        "category", "branch", "custodian", "responsible"
    )
    if status:
        rows = rows.filter(status=status)
    elif not include_disposed:
        rows = rows.filter(LIVE)
    if category:
        rows = rows.filter(category_id=category)
    if branch:
        rows = rows.filter(branch_id=branch)
    if custodian:
        rows = rows.filter(custodian_id=custodian)
    if q := q.strip():
        rows = rows.filter(
            Q(name__icontains=q)
            | Q(number__icontains=q)
            | Q(serial__icontains=q)
            | Q(model__icontains=q)
        )
    return with_values(rows).order_by("number")


def next_due(asset: Asset, today: date) -> tuple[str, date] | None:
    """The soonest upkeep date of a live asset (warranty and insurance only while ahead)."""
    if asset.status == Asset.Status.DISPOSED:
        return None
    options = []
    if asset.next_service_on and asset.status != Asset.Status.SUSPENDED:
        options.append(("service", asset.next_service_on))
    if asset.next_verification_on:
        options.append(("verification", asset.next_verification_on))
    if asset.warranty_until and asset.warranty_until >= today:
        options.append(("warranty", asset.warranty_until))
    if asset.insurance_until and asset.insurance_until >= today:
        options.append(("insurance", asset.insurance_until))
    return min(options, key=lambda option: option[1]) if options else None


def summary(company, *, branch_ids: list[int] | None, today: date | None = None) -> dict:
    """The register's header: how much the company owns and what it costs a month."""
    today = today or posting.local_today(company)
    settings = conf.get_settings(company)
    live = with_values(scoped(company, branch_ids=branch_ids).filter(LIVE)).select_related(
        "category", "company"
    )
    totals = {"count": 0, "cost": ZERO, "accumulated": ZERO, "book": ZERO, "this_month": ZERO}
    fully, due, low_value = 0, 0, 0
    month = engine.first_of(today)
    soon = today + timedelta(days=settings.remind_days)
    for asset in live:
        totals["count"] += 1
        totals["cost"] += asset.cost + asset.added
        totals["accumulated"] += asset.accumulated + asset.written_down
        totals["book"] += asset.book
        if asset.category.kind == AssetCategory.Kind.LOW_VALUE:
            low_value += 1
            continue
        if asset.depreciates and asset.in_service_on:
            rows = posting.schedule_of(asset, until=month, settings=settings)
            current = next((row for row in rows if row.month == month), None)
            if current is not None:
                totals["this_month"] += current.amount
            elif rows and rows[-1].month < month and asset.book <= asset.salvage_value:
                fully += 1
        upcoming = next_due(asset, today)
        if upcoming and upcoming[1] <= soon:
            due += 1
    return {
        **{key: quantize(value) if key != "count" else value for key, value in totals.items()},
        "fully_depreciated": fully,
        "upkeep_due": due,
        "low_value": low_value,
        "this_year": _year_total(company, branch_ids=branch_ids, year=today.year),
    }


def _year_total(company, *, branch_ids, year: int) -> str:
    rows = DepreciationEntry.objects.filter(company=company, opening=False, month__year=year)
    if branch_ids is not None:
        rows = rows.filter(asset__branch_id__in=branch_ids)
    return str(quantize(rows.aggregate(total=Sum("amount"))["total"] or ZERO))


@dataclass
class Values:
    cost: Decimal
    added: Decimal
    written_down: Decimal
    accumulated: Decimal
    book: Decimal
    months_used: int
    months_left: int | None
    end_month: date | None
    monthly_now: Decimal
    fully_depreciated: bool


def detail(asset: Asset, *, today: date | None = None) -> dict:
    """An asset's page: its values now, every month of its life (posted, then planned), the tax
    book when the company keeps one, its timeline, holders and files."""
    company = asset.company
    today = today or posting.local_today(company)
    settings = conf.get_settings(company)
    entries = list(asset.entries.select_related("transaction").order_by("month"))
    events = list(
        asset.events.select_related("from_branch", "to_branch", "membership", "created_by")
    )
    facts = posting.facts_of(asset, settings=settings, events=events, entries=entries)
    rows = engine.schedule(facts, actual_until=engine.first_of(today))
    by_month = {entry.month: entry for entry in entries}
    schedule = []
    for entry in entries:
        if (
            entry.opening
            and asset.opening_accumulated is not None
            and entry.month not in {row.month for row in rows}
        ):
            schedule.append(
                {
                    "month": entry.month,
                    "opening": quantize(asset.cost),
                    "amount": entry.amount,
                    "closing": entry.book_value,
                    "accumulated": entry.amount,
                    "state": "opening",
                    "notes": ["old_books"],
                    "transaction_id": None,
                }
            )
    for row in rows:
        entry = by_month.get(row.month)
        if entry is None:
            state = "planned"
        elif entry.opening:
            state = "opening"
        elif entry.transaction_id:
            state = "booked"
        else:
            state = "posted"
        schedule.append(
            {
                "month": row.month,
                "opening": row.opening,
                "amount": row.amount,
                "closing": row.closing,
                "accumulated": row.accumulated,
                "state": state,
                "notes": row.notes,
                "transaction_id": entry.transaction_id if entry else None,
            }
        )
    added = sum((event.amount or ZERO for event in events if event.kind == "addition"), ZERO)
    written = sum((event.amount or ZERO for event in events if event.kind == "impairment"), ZERO)
    accumulated = sum((entry.amount for entry in entries), ZERO)
    book = quantize(asset.cost + added - written - accumulated)
    month = engine.first_of(today)
    current = next((row for row in rows if row.month == month), None)
    end = rows[-1].month if rows and "final" in rows[-1].notes else None
    used = sum(1 for row in rows if row.month < month and row.fraction > 0)
    if asset.opening_accumulated is not None and entries:
        lump = next((entry for entry in entries if entry.opening), None)
        first = engine.first_month(facts)
        if lump is not None and first is not None:
            used += max(engine.months_between(first, engine.add_months(lump.month, 1)), 0)
    left = None
    if end is not None:
        left = max(engine.months_between(month, end) + 1, 0) if end >= month else 0
    values = Values(
        cost=quantize(asset.cost),
        added=quantize(added),
        written_down=quantize(written),
        accumulated=quantize(accumulated),
        book=book,
        months_used=used,
        months_left=left,
        end_month=end,
        monthly_now=current.amount if current else ZERO,
        fully_depreciated=asset.depreciates and book <= asset.salvage_value and bool(entries),
    )
    tax = None
    if settings.tax_book and asset.category.tax_rate and asset.depreciates:
        tax_rows = engine.tax_schedule(
            asset.cost + added,
            asset.category.tax_rate,
            asset.in_service_on,
            until=engine.add_months(month, 600),
            rule=settings.start_rule,
        )
        done = sum((amount for day, amount in tax_rows if day < month), ZERO)
        tax = {
            "rate": asset.category.tax_rate,
            "group": asset.category.tax_group,
            "monthly": tax_rows[0][1] if tax_rows else ZERO,
            "accumulated": quantize(done),
            "book": quantize(asset.cost + added - done),
            "end_month": tax_rows[-1][0] if tax_rows else None,
            # What the books and the tax book differ by now (a deferred tax item).
            "difference": quantize((asset.cost + added - done) - book),
        }
    return {
        "values": values,
        "schedule": schedule,
        "tax": tax,
        "events": events,
        "assignments": list(asset.assignments.select_related("membership", "issued_by")),
        "files": list(asset.files.all()),
        "next_due": next_due(asset, today),
    }


def _group_key(asset: Asset, group: str) -> tuple[int | None, str]:
    if group == "branch":
        return (asset.branch_id, asset.branch.name if asset.branch_id else "")
    return (asset.category_id, asset.category.name)


def depreciation_report(
    company, *, branch_ids: list[int] | None, year: int, group: str = "category"
) -> dict:
    """Depreciation of each month of `year` by category or branch: posted months as posted,
    the rest of the year as planned, and the tax book's when the company keeps one."""
    settings = conf.get_settings(company)
    today = posting.local_today(company)
    months = [date(year, number, 1) for number in range(1, 13)]
    end = months[-1]
    groups: dict[tuple, dict] = {}
    totals = [ZERO] * 12
    tax_totals = [ZERO] * 12
    assets = (
        scoped(company, branch_ids=branch_ids)
        .select_related("category", "branch", "company")
        .exclude(in_service_on=None)
        .exclude(disposed_on__lt=months[0])
    )
    for asset in assets:
        if not asset.depreciates:
            continue
        rows = posting.schedule_of(asset, until=end, settings=settings)
        key = _group_key(asset, group)
        bucket = groups.setdefault(
            key, {"id": key[0], "name": key[1], "amounts": [ZERO] * 12, "assets": 0}
        )
        counted = False
        for row in rows:
            if row.month.year != year:
                continue
            index = row.month.month - 1
            bucket["amounts"][index] += row.amount
            totals[index] += row.amount
            counted = counted or row.amount > 0
        bucket["assets"] += 1 if counted else 0
        if settings.tax_book and asset.category.tax_rate:
            for day, amount in engine.tax_schedule(
                asset.cost,
                asset.category.tax_rate,
                asset.in_service_on,
                until=end,
                rule=settings.start_rule,
            ):
                if day.year == year:
                    tax_totals[day.month - 1] += amount
    posted_through = posting.last_closed_month(company, today)
    rows = sorted(groups.values(), key=lambda bucket: (-sum(bucket["amounts"]), bucket["name"]))
    return {
        "year": year,
        "group": group,
        "months": months,
        "posted_through": posted_through,
        "groups": [
            {**bucket, "total": quantize(sum(bucket["amounts"], ZERO))}
            for bucket in rows
            if any(bucket["amounts"])
        ],
        "totals": [quantize(value) for value in totals],
        "total": quantize(sum(totals, ZERO)),
        "tax": [quantize(value) for value in tax_totals] if settings.tax_book else None,
        "tax_total": quantize(sum(tax_totals, ZERO)) if settings.tax_book else None,
    }


def _acquired(asset: Asset) -> date:
    return (
        asset.purchased_on
        or asset.in_service_on
        or posting.engine.first_of(asset.created_at.date())
    )


def movement(company, *, branch_ids: list[int] | None, start: date, end: date) -> dict:
    """The roll-forward of `start`..`end` by category: what the company owned at the start,
    what came in, what left, the depreciation and write-downs, and what it owns at the end
    (cost, accumulated depreciation, book value), the way an accountant checks the register."""
    assets = scoped(company, branch_ids=branch_ids).select_related("category")
    events = AssetEvent.objects.filter(
        asset__in=assets, kind__in=(AssetEvent.Kind.ADDITION, AssetEvent.Kind.IMPAIRMENT)
    )
    entries = DepreciationEntry.objects.filter(asset__in=assets)
    added_before = defaultdict(lambda: ZERO)
    added_in = defaultdict(lambda: ZERO)
    down_before = defaultdict(lambda: ZERO)
    down_in = defaultdict(lambda: ZERO)
    for event in events:
        if event.on < start:
            target = added_before if event.kind == "addition" else down_before
        elif event.on <= end:
            target = added_in if event.kind == "addition" else down_in
        else:
            continue
        target[event.asset_id] += event.amount or ZERO
    dep_before = defaultdict(lambda: ZERO)
    dep_in = defaultdict(lambda: ZERO)
    first, last = engine.first_of(start), engine.first_of(end)
    for entry in entries:
        if entry.month < first:
            dep_before[entry.asset_id] += entry.amount
        elif entry.month <= last:
            dep_in[entry.asset_id] += entry.amount
    lines: dict[int, dict] = {}
    keys = (
        "open_cost",
        "open_depreciation",
        "in_cost",
        "out_cost",
        "out_depreciation",
        "depreciation",
        "written_down",
        "close_cost",
        "close_depreciation",
    )
    for asset in assets:
        acquired = _acquired(asset)
        gone_before = asset.disposed_on is not None and asset.disposed_on < start
        if acquired > end or gone_before:
            continue
        line = lines.setdefault(
            asset.category_id,
            {"id": asset.category_id, "name": asset.category.name, **dict.fromkeys(keys, ZERO)},
        )
        pk = asset.pk
        owned_at_start = acquired < start
        cost_before = (asset.cost if owned_at_start else ZERO) + added_before[pk]
        line["open_cost"] += cost_before
        line["open_depreciation"] += dep_before[pk] + down_before[pk]
        line["in_cost"] += (ZERO if owned_at_start else asset.cost) + added_in[pk]
        line["depreciation"] += dep_in[pk]
        line["written_down"] += down_in[pk]
        gone = asset.disposed_on is not None and start <= asset.disposed_on <= end
        total_cost = asset.cost + added_before[pk] + added_in[pk]
        total_dep = dep_before[pk] + dep_in[pk] + down_before[pk] + down_in[pk]
        if gone:
            line["out_cost"] += total_cost
            line["out_depreciation"] += total_dep
        else:
            line["close_cost"] += total_cost
            line["close_depreciation"] += total_dep
    result = []
    for line in sorted(lines.values(), key=lambda row: row["name"]):
        for key in keys:
            line[key] = quantize(line[key])
        line["open_book"] = quantize(line["open_cost"] - line["open_depreciation"])
        line["close_book"] = quantize(line["close_cost"] - line["close_depreciation"])
        result.append(line)
    total = {key: quantize(sum((line[key] for line in result), ZERO)) for key in keys}
    total["open_book"] = quantize(total["open_cost"] - total["open_depreciation"])
    total["close_book"] = quantize(total["close_cost"] - total["close_depreciation"])
    return {"start": start, "end": end, "lines": result, "total": total}


def _replacement(asset: Asset, settings, on: date) -> Decimal:
    """What buying it again will cost on `on`: its cost grown by the planning inflation."""
    bought = _acquired(asset)
    years = Decimal(max((on - bought).days, 0)) / Decimal("365.25")
    growth = (1 + float(settings.replacement_inflation) / 100) ** float(years)
    return quantize(asset.cost * Decimal(str(growth)))


def planning(company, *, branch_ids: list[int] | None, today: date | None = None) -> dict:
    """What an owner should plan for: replacements as assets reach the end of their life
    (with the cost grown by inflation, by quarter), assets whose repairs approach the price of
    a new one, money sleeping in idle or mothballed assets, old ones that still work for free,
    upkeep coming up and things given out but never confirmed."""
    today = today or posting.local_today(company)
    settings = conf.get_settings(company)
    month = engine.first_of(today)
    horizon = engine.add_months(month, 36)
    live = with_values(scoped(company, branch_ids=branch_ids).filter(LIVE)).select_related(
        "category", "branch", "company", "custodian"
    )
    replacements, quarters = [], defaultdict(lambda: {"count": 0, "amount": ZERO})
    repairs_since = today - timedelta(days=365)
    repair_costs = dict(
        AssetEvent.objects.filter(
            company=company, kind=AssetEvent.Kind.REPAIR, on__gte=repairs_since
        )
        .values("asset")
        .annotate(total=Sum("amount"))
        .values_list("asset", "total")
    )
    repair_watch, idle, free = [], [], []
    for asset in live:
        if asset.category.kind == AssetCategory.Kind.LOW_VALUE:
            continue
        end = None
        if asset.depreciates and asset.in_service_on:
            rows = posting.schedule_of(asset, settings=settings)
            if rows and "final" in rows[-1].notes:
                end = rows[-1].month
        if end is not None and end <= horizon and asset.status != Asset.Status.SUSPENDED:
            due = max(end, month)
            estimate = _replacement(asset, settings, due)
            quarter = f"{due.year}-Q{(due.month - 1) // 3 + 1}"
            quarters[quarter]["count"] += 1
            quarters[quarter]["amount"] += estimate
            replacements.append({"asset": asset, "end_month": end, "estimate": estimate})
        if asset.book <= asset.salvage_value and asset.status == Asset.Status.IN_USE and end:
            free.append(asset)
        spent = repair_costs.get(asset.pk) or ZERO
        if spent:
            new_price = _replacement(asset, settings, today)
            share = (spent / new_price * 100) if new_price else ZERO
            if share >= 50 or spent >= asset.book:
                repair_watch.append(
                    {
                        "asset": asset,
                        "repairs": quantize(spent),
                        "replacement": new_price,
                        "share": quantize(share),
                    }
                )
        if asset.status in (Asset.Status.IN_STORAGE, Asset.Status.SUSPENDED):
            # Idle since it was mothballed, or since it last came back or arrived.
            kinds = (
                (AssetEvent.Kind.SUSPENDED,)
                if asset.status == Asset.Status.SUSPENDED
                else (AssetEvent.Kind.CREATED, AssetEvent.Kind.RETURNED, AssetEvent.Kind.NOTE)
            )
            since = (
                asset.events.filter(kind__in=kinds)
                .order_by("-on")
                .values_list("on", flat=True)
                .first()
            )
            if since is None or (today - since).days >= 60:
                idle.append(asset)
    upkeep = []
    soon = today + timedelta(days=max(settings.remind_days, 30))
    for asset in live:
        for what, day in (
            ("service", asset.next_service_on),
            ("verification", asset.next_verification_on),
            ("warranty", asset.warranty_until),
            ("insurance", asset.insurance_until),
        ):
            if day is None:
                continue
            if what in ("warranty", "insurance") and day < today:
                continue
            if day <= soon:
                upkeep.append({"asset": asset, "what": what, "day": day, "overdue": day < today})
    upkeep.sort(key=lambda item: item["day"])
    unconfirmed = list(
        AssetAssignment.objects.filter(
            company=company,
            returned_on__isnull=True,
            acknowledged_at__isnull=True,
            issued_on__lte=today - timedelta(days=3),
            asset__in=scoped(company, branch_ids=branch_ids),
        ).select_related("asset", "membership")
    )
    replacements.sort(key=lambda item: item["end_month"])
    return {
        "replacements": replacements,
        "quarters": [
            {"quarter": key, "count": value["count"], "amount": quantize(value["amount"])}
            for key, value in sorted(quarters.items())
        ],
        "replacement_total": quantize(sum((value["amount"] for value in quarters.values()), ZERO)),
        "repairs": sorted(repair_watch, key=lambda item: -item["share"]),
        "idle": idle,
        "idle_value": quantize(sum((asset.book for asset in idle), ZERO)),
        "free": free,
        "upkeep": upkeep,
        "unconfirmed": unconfirmed,
        "inflation": settings.replacement_inflation,
    }


def custody(company, *, branch_ids: list[int] | None) -> list[dict]:
    """Who holds what now, by person, with the value of it."""
    rows = with_values(
        scoped(company, branch_ids=branch_ids).filter(LIVE, custodian__isnull=False)
    ).select_related("custodian", "category")
    people: dict[int, dict] = {}
    open_by_asset = {
        assignment.asset_id: assignment
        for assignment in AssetAssignment.objects.filter(company=company, returned_on__isnull=True)
    }
    for asset in rows:
        person = people.setdefault(
            asset.custodian_id,
            {"membership": asset.custodian, "assets": [], "value": ZERO, "unconfirmed": 0},
        )
        assignment = open_by_asset.get(asset.pk)
        person["assets"].append({"asset": asset, "assignment": assignment})
        person["value"] += asset.book
        if assignment is not None and assignment.acknowledged_at is None:
            person["unconfirmed"] += 1
    return sorted(people.values(), key=lambda row: str(row["membership"]))


def purchases(company, *, branch_ids: list[int] | None, limit: int = 50) -> list:
    """Expenses that look like equipment (an equipment category, or above the company's
    threshold) and aren't an asset yet: "turn this purchase into an asset"."""
    if not company.has_feature("finance"):
        return []
    from apps.finance.models import Transaction

    settings = conf.get_settings(company)
    since = posting.local_today(company) - timedelta(days=550)
    rows = Transaction.objects.for_company(company).filter(
        kind=Transaction.Kind.EXPENSE,
        status__in=(Transaction.Status.POSTED, Transaction.Status.PENDING),
        is_contra=False,
        capitalized=False,
        occurred_on__gte=since,
        fixed_assets__isnull=True,
    )
    looks = Q(category__is_capex=True)
    if settings.capitalization_threshold:
        looks |= Q(base_amount__lte=-settings.capitalization_threshold)
    rows = rows.filter(looks)
    if branch_ids is not None:
        rows = rows.filter(branch_id__in=branch_ids)
    return list(
        rows.select_related("category", "counterparty", "account", "branch").order_by(
            "-occurred_on", "-pk"
        )[:limit]
    )


def mine(membership) -> list[AssetAssignment]:
    """What the person holds now (the mini app's "My equipment")."""
    return list(
        AssetAssignment.objects.filter(
            company=membership.company, membership=membership, returned_on__isnull=True
        )
        .select_related("asset__category", "asset__branch")
        .prefetch_related("asset__files")
        .order_by("-issued_on")
    )
