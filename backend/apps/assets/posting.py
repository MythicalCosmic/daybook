"""Posting depreciation: from the engine's schedule to `DepreciationEntry` rows and the ledger.

    post_asset(asset, through=date(2026, 10, 1))   # entries for every finished month up to October
    book_company(company)                          # what is not in Finance yet, one row per branch

A month is posted once it is over (its last day has passed in the company's timezone); its
entry is never edited again, so the engine computes every later month from it. Months before
the asset was entered here are posted as `opening` entries: they happened in the old books and
are never booked (unless the purchase itself is in this ledger, then every month is booked).

Finance gets one non-cash row per month and branch ("Depreciation, November 2026: 12 assets"),
dated the month's last day, or the first open day when the books are already closed up to it.
A later entry for a month already booked (an asset entered late) goes in a row of its own.
"""

import calendar
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.assets import conf, engine
from apps.assets.models import Asset, AssetEvent, AssetSettings, DepreciationEntry
from apps.companies.models import Feature

SOURCE_RUN = "assets.assetsettings"  # finance source of the monthly rows (id: the settings row)
SOURCE_ASSET = "assets.asset"  # finance source of one asset's own rows (write-offs, sales)
MONTHS = {
    "uz": (
        "yanvar",
        "fevral",
        "mart",
        "aprel",
        "may",
        "iyun",
        "iyul",
        "avgust",
        "sentabr",
        "oktabr",
        "noyabr",
        "dekabr",
    ),
    "ru": (
        "январь",
        "февраль",
        "март",
        "апрель",
        "май",
        "июнь",
        "июль",
        "август",
        "сентябрь",
        "октябрь",
        "ноябрь",
        "декабрь",
    ),
}


def zone_of(company) -> ZoneInfo:
    return ZoneInfo(company.timezone)


def local_today(company) -> date:
    return timezone.localtime(timezone.now(), zone_of(company)).date()


def last_closed_month(company, today: date | None = None) -> date:
    """The first day of the last month that is over."""
    today = today or local_today(company)
    return engine.add_months(engine.first_of(today), -1)


def month_end(month: date) -> date:
    return month.replace(day=calendar.monthrange(month.year, month.month)[1])


def tracked_from(asset: Asset) -> date:
    """The first month this app keeps for real: the month the asset was entered, or its first
    month when its purchase is in this ledger."""
    if asset.purchase_transaction_id and asset.purchase_transaction.capitalized:
        return engine.first_of(asset.purchase_transaction.occurred_on)
    return engine.first_of(timezone.localtime(asset.created_at, zone_of(asset.company)).date())


def changes_of(events) -> tuple[tuple[engine.Change, ...], dict]:
    """The engine's changes from an asset's events, and the facts as they were before the first
    change of estimate (each estimate keeps what it replaced)."""
    changes: list[engine.Change] = []
    original: dict = {}
    for event in events:
        kind = event.kind
        if kind == AssetEvent.Kind.ADDITION and event.amount:
            changes.append(engine.Change("addition", event.on, amount=event.amount))
        elif kind == AssetEvent.Kind.IMPAIRMENT and event.amount:
            changes.append(engine.Change("impairment", event.on, amount=event.amount))
        elif kind == AssetEvent.Kind.SUSPENDED:
            changes.append(engine.Change("suspend", event.on))
        elif kind == AssetEvent.Kind.RESUMED:
            changes.append(engine.Change("resume", event.on))
        elif kind == AssetEvent.Kind.USAGE and event.units is not None:
            changes.append(engine.Change("usage", event.on, units=event.units))
        elif kind == AssetEvent.Kind.ESTIMATE:
            new = event.details.get("new", {})
            old = event.details.get("old", {})
            for key, value in old.items():
                original.setdefault(key, value)
            changes.append(
                engine.Change(
                    "estimate",
                    event.on,
                    life_months=new.get("life_months"),
                    salvage=Decimal(new["salvage_value"]) if "salvage_value" in new else None,
                    method=new.get("method"),
                )
            )
    return tuple(changes), original


def facts_of(asset: Asset, *, settings: AssetSettings | None = None, events=None, entries=None):
    """The engine's facts of `asset`, with its posted months as history."""
    settings = settings or conf.get_settings(asset.company)
    events = list(asset.events.all()) if events is None else events
    entries = list(asset.entries.all()) if entries is None else entries
    changes, original = changes_of(events)
    lump = asset.opening_accumulated is not None
    lump_month = engine.add_months(_opening_month(asset), -1) if lump else None
    # The old books' sum is the opening, not a month of its own.
    posted = {
        entry.month: entry.amount
        for entry in entries
        if not (lump and entry.opening and entry.month == lump_month)
    }
    method = original.get("method", asset.method)
    if not asset.depreciates:
        method = engine.NONE
    return engine.Facts(
        cost=asset.cost,
        life_months=original.get("life_months", asset.life_months),
        method=method,
        start=asset.in_service_on,
        rule=settings.start_rule,
        salvage=Decimal(original.get("salvage_value", asset.salvage_value)),
        factor=asset.declining_factor,
        total_units=asset.total_units,
        disposed_on=asset.disposed_on,
        changes=changes,
        posted=posted,
        opening_accumulated=asset.opening_accumulated,
        opening_month=_opening_month(asset) if lump else None,
    )


def _opening_month(asset: Asset) -> date:
    return engine.first_of(timezone.localtime(asset.created_at, zone_of(asset.company)).date())


def schedule_of(asset: Asset, *, until: date | None = None, settings=None) -> list[engine.Month]:
    today = local_today(asset.company)
    return engine.schedule(
        facts_of(asset, settings=settings), until=until, actual_until=engine.first_of(today)
    )


@transaction.atomic
def post_asset(asset: Asset, *, through: date | None = None) -> int:
    """Post every finished month of `asset` not posted yet, up to `through` (a month). Returns
    the number of entries made."""
    asset = Asset.objects.select_for_update().select_related("company", "category").get(pk=asset.pk)
    company = asset.company
    through = engine.first_of(through) if through else last_closed_month(company)
    if asset.disposed_on is not None:
        through = max(through, engine.first_of(asset.disposed_on))
    settings = conf.get_settings(company)
    entries = list(asset.entries.all())
    have = {entry.month for entry in entries}
    made = 0
    lump = asset.opening_accumulated
    if lump is not None and lump > 0 and not any(entry.opening for entry in entries):
        # What the old books had depreciated: one opening entry for the months before.
        lump_month = engine.add_months(_opening_month(asset), -1)
        DepreciationEntry.objects.create(
            company=company,
            asset=asset,
            month=lump_month,
            amount=lump,
            book_value=engine.money(asset.cost - lump),
            opening=True,
        )
        made += 1
        have.add(lump_month)
    rows = engine.schedule(
        facts_of(asset, settings=settings),
        until=through,
        actual_until=engine.first_of(local_today(company)),
    )
    start = tracked_from(asset)
    for row in rows:
        if row.month in have or row.month > through:
            continue
        DepreciationEntry.objects.create(
            company=company,
            asset=asset,
            month=row.month,
            amount=row.amount,
            book_value=row.closing,
            opening=row.month < start,
        )
        made += 1
    return made


def post_company(company, *, through: date | None = None) -> int:
    """Post every asset of the company up to the last finished month (the nightly job)."""
    made = 0
    for asset in Asset.objects.for_company(company).exclude(in_service_on=None).iterator():
        if (
            asset.disposed_on is not None
            and asset.entries.filter(month__gte=engine.first_of(asset.disposed_on)).exists()
        ):
            continue
        made += post_asset(asset, through=through)
    return made


def books_open_from(company) -> date | None:
    """The first day Finance takes new rows on (the day after its period lock), or None."""
    from apps.finance import conf as finance_conf

    locked = finance_conf.get_settings(company).locked_until
    return locked + timedelta(days=1) if locked else None


def booking_day(company, day: date) -> date:
    open_from = books_open_from(company)
    return max(day, open_from) if open_from else day


def finance_on(company) -> bool:
    return company.has_feature(Feature.FINANCE)


def book_company(company) -> int:
    """Book what is posted and not in Finance yet: one non-cash row per month and branch.
    Returns the number of ledger rows made. Nothing without the Finance module."""
    if not finance_on(company):
        return 0
    from apps.finance import services as finance
    from apps.finance.sources import Source

    made = 0
    with transaction.atomic():
        settings = AssetSettings.objects.select_for_update().get(pk=conf.get_settings(company).pk)
        pending = (
            DepreciationEntry.objects.filter(
                company=company,
                transaction__isnull=True,
                opening=False,
                asset__books_depreciation=True,
                amount__gt=0,
            )
            .select_related("asset")
            .order_by("month", "asset__branch_id")
        )
        groups: dict[tuple[date, int | None], list[DepreciationEntry]] = defaultdict(list)
        for entry in pending:
            groups[(entry.month, entry.asset.branch_id)].append(entry)
        for (month, branch_id), entries in groups.items():
            batch = (
                DepreciationEntry.objects.filter(
                    company=company,
                    month=month,
                    asset__branch_id=branch_id,
                    transaction__isnull=False,
                )
                .values("transaction_id")
                .distinct()
                .count()
                + 1
            )
            total = sum((entry.amount for entry in entries), Decimal(0))
            day = booking_day(company, month_end(month))
            row = finance.book_non_cash(
                company,
                amount=total,
                occurred_on=day,
                category="depreciation",
                source=Source(SOURCE_RUN, settings.pk, f"d:{month:%Y-%m}:{branch_id or 0}:{batch}"),
                branch=entries[0].asset.branch,
                description=_run_text(company, month, len(entries)),
            )
            DepreciationEntry.objects.filter(pk__in=[entry.pk for entry in entries]).update(
                transaction=row, booked_on=day
            )
            made += 1
    return made


def _run_text(company, month: date, count: int) -> str:
    language = company.default_language
    names = MONTHS.get(language)
    when = f"{names[month.month - 1]} {month.year}" if names else month.strftime("%B %Y")
    return ngettext(
        "Depreciation, %(month)s: %(count)s asset",
        "Depreciation, %(month)s: %(count)s assets",
        count,
    ) % {"month": when, "count": count}


def book_asset_cost(asset: Asset, *, amount: Decimal, day: date, key: str, description: str):
    """One asset's own non-cash cost (its book value written off or written down)."""
    if not finance_on(asset.company) or not asset.books_depreciation or amount <= 0:
        return None
    from apps.finance import services as finance
    from apps.finance.sources import Source

    return finance.book_non_cash(
        asset.company,
        amount=amount,
        occurred_on=booking_day(asset.company, day),
        category="asset_disposal",
        source=Source(SOURCE_ASSET, asset.pk, key),
        branch=asset.branch,
        description=description,
    )


def text_written_off(asset: Asset) -> str:
    return _("Written off: %(asset)s") % {"asset": f"{asset.number} {asset.name}"}


def text_written_down(asset: Asset) -> str:
    return _("Value written down: %(asset)s") % {"asset": f"{asset.number} {asset.name}"}
