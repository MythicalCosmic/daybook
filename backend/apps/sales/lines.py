"""Sale lines from the cash-register software (docs/PLAN-OWNER.md §14.7).

`process(import_id)` (run by `sales.tasks.process_import`) reads an import's file through its
profile and writes what it finds:

- one receipt per (branch, register, business day, receipt number): a `Sale` with
  `source=import` and `shift=None`, its cashier from the program's code (`PosCashier`), and
  `external_id = "<profile>:<register>:<business day>:<receipt number>"` (its SHA-1 when longer
  than 64 characters), because programs restart receipt numbers per register and day. A receipt
  already imported (by any earlier file) is left out and counted as duplicates, so importing the
  same file twice adds nothing;
- each line whose item code the catalogue knows (`inventory.queries.match_code`) takes its stock
  through the stock contract: a sale `deduct`s (FEFO, the file's series when it has one) and is
  stored one row per returned allocation, a refund `restock`s into quarantine (medicines sold
  are never resold, §14.4) with the original receipt's allocations when the file names it, and
  a prescription line with a prescription number goes to the prescription log (`record_rx`);
- a line the catalogue doesn't know waits in the match list. Matching its code by hand
  (`match`) remembers the code (`remember_code`) and settles every waiting line with it.

**Imported receipts are line facts, not money**: nothing here books the ledger, and
`DailySales` never counts them (`Sale.objects.money()`). The day check compares what an import
brought per branch and business day with the tills' totals (`DailySales.net`), and the legal
price check flags each prescription line sold above its cap (`inventory.queries.price_cap`: the
batch's cost plus the legal markup, never above the reference price) and tells the people who
run sales once per branch and day.

Each receipt is written in its own transaction, so a big file never holds the stock's row locks
for long and one bad receipt never loses the others.
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import IntegrityError, transaction
from django.db.models import Count, Sum
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.audit import services as audit
from apps.companies.models import Branch, Feature
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.inbox.services import notify
from apps.inventory import queries as stock_queries
from apps.inventory import services as stock
from apps.inventory.models import Product, StockBatch
from apps.inventory.services import Allocation
from apps.sales import alerts, importer
from apps.sales import bot_messages as msg
from apps.sales.audit_actions import SalesAction
from apps.sales.conf import get_settings
from apps.sales.days import business_day
from apps.sales.models import (
    DailySales,
    PosCashier,
    Sale,
    SaleLine,
    SalesImport,
    SalesImportProfile,
    SalesSettings,
)

logger = logging.getLogger(__name__)

ZERO = Decimal(0)
CENT = Decimal("0.01")
PART = Decimal("0.001")
GAP_PERCENT = Decimal("1")  # the day check flags a gap above this share of the tills' totals
MAX_PROBLEMS = 50
SALE_DOCUMENT = "sales.sale"
LINE_DOCUMENT = "sales.saleline"

PULSE_LINES = "sales.lines"
PULSE_UNMATCHED = "sales.unmatched"

Status = SaleLine.Status


@dataclass
class Outcome:
    """What one run wrote, counted in receipt lines."""

    receipts: int = 0
    matched: int = 0
    unmatched: int = 0
    duplicates: int = 0
    problems: list = field(default_factory=list)
    days: set = field(default_factory=set)  # (branch id, business day)

    def problem(self, row: int | None, message: str) -> None:
        if len(self.problems) < MAX_PROBLEMS:
            self.problems.append({"row": row, "message": str(message)})


def external_id(profile_id: int, register: str, day: date, number: str) -> str:
    """`<profile>:<register>:<business day>:<receipt number>`, or its SHA-1 past 64 characters."""
    value = f"{profile_id}:{register}:{day.isoformat()}:{number}"
    if len(value) > 64:
        value = hashlib.sha1(value.encode()).hexdigest()
    return value


def register_key(profile: SalesImportProfile, branch_id: int, register: str) -> str:
    """The register part of a receipt's external id. A profile fixed to one pharmacy uses the
    program's register as it is; a file with a pharmacy column prefixes the branch, because two
    pharmacies' tills are often both called "1" and both restart their numbers every day."""
    return register if profile.branch_id else f"{branch_id}/{register}"


def layout(profile: SalesImportProfile) -> importer.Layout:
    return importer.Layout(
        file_kind=profile.file_kind,
        encoding=profile.encoding,
        delimiter=profile.delimiter,
        header_row=profile.header_row,
        columns=profile.columns,
        date_format=profile.date_format,
        default_unit=profile.default_unit,
    )


def lines_on(company) -> bool:
    """Sale lines are imported: the sales module is on and the company chose imports."""
    return (
        company.has_feature(Feature.SALES)
        and get_settings(company).sales_lines == SalesSettings.Lines.IMPORT
    )


# The import ------------------------------------------------------------------------------


def process(import_id: int) -> SalesImport | None:
    """Read one queued import (idempotent: anything but a queued import is left alone)."""
    imp = _claim(import_id)
    if imp is None:
        return None
    company = imp.company
    try:
        with translation.override(company.default_language):
            if not lines_on(company):
                raise DomainError(_("Sale line imports are switched off in the sales settings."))
            with imp.file.open("rb") as handle:
                data = handle.read()
            rows, unreadable = importer.rows(
                data,
                layout(imp.profile),
                timezone=company.timezone,
                needs_branch=imp.profile.branch_id is None,
            )
            outcome = Outcome()
            for problem in unreadable:
                outcome.problem(problem["row"], problem["message"])
            _write(imp, rows, outcome)
            _finish(
                imp,
                rows=len(rows) + len(unreadable),
                lines=len(rows),
                outcome=outcome,
                unreadable=len(unreadable),
            )
    except DomainError as exc:
        _fail(imp, str(exc))
    except Exception:
        logger.exception("sales import %s failed", import_id)
        with translation.override(company.default_language):
            _fail(imp, _("The file couldn't be read. Check the profile and try again."))
    return SalesImport.objects.filter(pk=import_id).first()


def _claim(import_id: int) -> SalesImport | None:
    with transaction.atomic():
        imp = (
            SalesImport.objects.select_for_update(of=("self",))
            .select_related("company", "profile__branch", "created_by")
            .filter(pk=import_id)
            .first()
        )
        if imp is None or imp.status != SalesImport.Status.QUEUED:
            return None
        imp.status = SalesImport.Status.PROCESSING
        imp.started_at = timezone.now()
        imp.save(update_fields=["status", "started_at", "updated_at"])
    return imp


class _Branches:
    """The file's branch column read against the company's branches: the profile's map first,
    then a branch's code or name (any case)."""

    def __init__(self, profile: SalesImportProfile):
        self.fixed = profile.branch
        company_branches = list(
            Branch.objects.for_company(profile.company_id).filter(is_active=True)
        )
        self.by_id = {branch.pk: branch for branch in company_branches}
        self.by_word = {}
        for branch in company_branches:
            for word in (branch.code, branch.name):
                if word:
                    self.by_word.setdefault(word.strip().lower(), branch)
        self.mapped = {
            str(word).strip().lower(): self.by_id.get(_int(branch_id))
            for word, branch_id in (profile.branch_map or {}).items()
        }

    def get(self, value: str) -> Branch | None:
        if self.fixed is not None:
            return self.fixed
        word = (value or "").strip().lower()
        return self.mapped.get(word) or self.by_word.get(word)


def _int(value) -> int | None:
    try:
        return int(value)
    except TypeError, ValueError:
        return None


def _write(imp: SalesImport, rows: list[importer.Row], outcome: Outcome) -> None:
    company = imp.company
    settings = get_settings(company)
    branches = _Branches(imp.profile)
    receipts: dict[tuple, list[importer.Row]] = defaultdict(list)
    for row in rows:
        branch = branches.get(row.branch)
        if branch is None:
            outcome.problem(
                row.number, _("Unknown branch %(branch)s.") % {"branch": row.branch or "—"}
            )
            continue
        day = business_day(company, row.sold_at, ends_at=settings.business_day_ends_at)
        receipts[(branch.pk, row.register, day, row.receipt)].append(row)
    cache = _Cache(company)
    for (branch_id, till, day, number), found in receipts.items():
        branch = branches.by_id[branch_id]
        register = register_key(imp.profile, branch_id, till)
        sold = [row for row in found if not row.refund]
        returned = [row for row in found if row.refund]
        if sold:
            _receipt(
                imp,
                branch,
                day,
                number,
                Sale.Kind.SALE,
                sold,
                outcome,
                cache,
                external_id(imp.profile_id, register, day, number),
            )
        if returned:
            # A receipt that both sells and takes back keeps the two apart.
            key = f"{number}:R" if sold else number
            _receipt(
                imp,
                branch,
                day,
                number,
                Sale.Kind.REFUND,
                returned,
                outcome,
                cache,
                external_id(imp.profile_id, register, day, key),
            )


class _Cache:
    """Products by code and cashiers by code, looked up once per run."""

    def __init__(self, company):
        self.company = company
        self.products: dict[str, Product | None] = {}
        self.cashiers: dict[str, PosCashier] = {}

    def product(self, code: str) -> Product | None:
        if code not in self.products:
            self.products[code] = stock_queries.match_code(self.company, code)
        return self.products[code]

    def cashier(self, code: str) -> PosCashier | None:
        code = (code or "").strip()[:32]
        if not code:
            return None
        if code not in self.cashiers:
            try:
                with transaction.atomic():
                    found, _created = PosCashier.objects.get_or_create(
                        company=self.company, code=code
                    )
            except IntegrityError:
                found = PosCashier.objects.get(company=self.company, code=code)
            self.cashiers[code] = found
        return self.cashiers[code]


def _receipt(imp, branch, day, number, kind, rows, outcome: Outcome, cache: _Cache, key) -> None:
    company = imp.company
    if Sale.objects.filter(company=company, source=Sale.Source.IMPORT, external_id=key).exists():
        outcome.duplicates += len(rows)
        return
    total = sum((row.total for row in rows), ZERO)
    if total <= 0:
        outcome.problem(
            rows[0].number, _("Receipt %(number)s adds up to nothing.") % {"number": number}
        )
        return
    pos = cache.cashier(rows[0].cashier)
    try:
        with transaction.atomic():
            sale = Sale.objects.create(
                company=company,
                branch=branch,
                shift=None,
                register=None,
                cashier=pos.membership if pos is not None else None,
                performed_by=None,
                sold_at=min(row.sold_at for row in rows),
                business_day=day,
                kind=kind,
                number=number[:32],
                total=total,
                discount=sum((row.discount for row in rows), ZERO),
                source=Sale.Source.IMPORT,
                external_id=key,
                sales_import=imp,
                pos_cashier=pos,
                payment_label=rows[0].payment[:50],
            )
            for line_number, row in enumerate(rows, start=1):
                product = cache.product(row.code)
                if product is None:
                    _waiting(sale, line_number, row)
                    outcome.unmatched += 1
                    continue
                settle(
                    sale,
                    product,
                    line_number=line_number,
                    row=row,
                    by=imp.created_by,
                    outcome=outcome,
                )
                outcome.matched += 1
    except IntegrityError:
        # The same receipt arrived from a file read at the same moment.
        outcome.duplicates += len(rows)
        return
    outcome.receipts += 1
    outcome.days.add((branch.pk, day))


def _waiting(sale: Sale, line_number: int, row: importer.Row) -> SaleLine:
    """A line whose code the catalogue doesn't know: its quantity stays in the file's unit
    (`parts_per_pack` 1) until the code is matched."""
    return SaleLine.objects.create(
        sale=sale,
        line_number=line_number,
        status=Status.WAITING,
        code=row.code,
        name=row.name,
        unit=row.unit,
        quantity=row.quantity.quantize(PART),
        parts_per_pack=1,
        price=row.price,
        discount=row.discount,
        total=row.total,
        series=row.series,
        rx_number=row.rx_number,
    )


# Settling one line against the stock -------------------------------------------------------


def parts(quantity: Decimal, unit: str, product: Product) -> tuple[Decimal, int]:
    """The line's quantity in parts and the product's parts per pack. A third of a pack of
    three is one part, whatever the program rounded it to."""
    per_pack = max(int(product.units_per_pack or 1), 1)
    found = quantity * per_pack if unit == SalesImportProfile.Unit.PACK else quantity
    whole = found.to_integral_value(ROUND_HALF_UP)
    if whole > 0 and abs(found - whole) <= Decimal("0.05"):
        found = whole
    return found.quantize(PART), per_pack


def settle(
    sale: Sale,
    product: Product,
    *,
    line_number: int,
    row: importer.Row | None = None,
    waiting: SaleLine | None = None,
    by=None,
    outcome: Outcome | None = None,
) -> list[SaleLine]:
    """Take (or give back) the line's stock and store it one row per batch. Either a fresh
    `row` from the file, or a `waiting` line being matched (which becomes the first row)."""
    source = row if row is not None else waiting
    quantity, per_pack = parts(source.quantity, source.unit, product)
    series = (source.series or "").strip()
    rx_number = (source.rx_number or "").strip()
    total, discount = source.total, source.discount
    if sale.kind == Sale.Kind.SALE:
        allocations = _deduct(
            sale, product, quantity, series=series, by=by, outcome=outcome, row=row
        )
    else:
        refund_of = row.refund_of if row is not None else ""
        allocations = _restock(
            sale, product, quantity, refund_of=refund_of, by=by, outcome=outcome, row=row
        )
    batches = StockBatch.objects.in_bulk([a.batch_id for a in allocations if a.batch_id])
    stored: list[SaleLine] = []
    left_total, left_discount = total, discount
    for index, allocation in enumerate(allocations):
        last = index == len(allocations) - 1
        share = allocation.quantity / quantity
        part_total = left_total if last else (total * share).quantize(CENT)
        part_discount = left_discount if last else (discount * share).quantize(CENT)
        left_total -= part_total
        left_discount -= part_discount
        batch = batches.get(allocation.batch_id)
        cap = None
        if sale.kind == Sale.Kind.SALE and product.rx_required:
            cap = stock_queries.price_cap(product, batch=batch)
        line = waiting if index == 0 and waiting is not None else SaleLine(sale=sale)
        line.line_number = line_number
        line.status = Status.MATCHED
        line.product = product
        line.batch = batch
        line.code = (source.code or "")[:64]
        line.name = (source.name or product.name)[:200]
        line.unit = source.unit
        line.quantity = allocation.quantity
        line.parts_per_pack = per_pack
        line.price = source.price
        line.discount = part_discount
        line.total = part_total
        line.cost = (
            (allocation.unit_cost * allocation.quantity).quantize(CENT)
            if allocation.unit_cost is not None
            else None
        )
        line.cap = cap
        line.over_cap = cap is not None and pack_price(line) > cap
        line.series = series[:40]
        line.rx_number = rx_number[:40]
        line.save()
        stored.append(line)
    if sale.kind == Sale.Kind.SALE and product.rx_required and rx_number and stored:
        try:
            with transaction.atomic():
                stock.record_rx(
                    by=by,
                    branch=sale.branch,
                    product=product,
                    quantity=quantity,
                    document=(LINE_DOCUMENT, stored[0].pk),
                    prescription_number=rx_number[:40],
                )
        except DomainError as exc:
            if outcome is not None:
                outcome.problem(row.number if row else None, str(exc))
    return stored


def pack_price(line: SaleLine) -> Decimal:
    """What one pack cost the customer on this line, after its discount."""
    if not line.quantity:
        return ZERO
    return (line.total / line.quantity * line.parts_per_pack).quantize(CENT, rounding=ROUND_HALF_UP)


def _deduct(sale, product, quantity, *, series, by, outcome, row) -> list[Allocation]:
    try:
        with transaction.atomic():
            found = stock.deduct(
                sale.branch,
                product,
                quantity,
                by=by,
                document=(SALE_DOCUMENT, sale.pk),
                kind="sale",
                series=series or None,
                at=sale.sold_at,
            )
    except DomainError as exc:
        # The sale happened at the counter: the line is kept even when the stock can't follow.
        if outcome is not None:
            outcome.problem(
                row.number if row else None,
                _("%(product)s: the stock wasn't moved (%(reason)s).")
                % {"product": product.name, "reason": exc},
            )
        found = []
    return _whole(found, quantity)


def _restock(sale, product, quantity, *, refund_of, by, outcome, row) -> list[Allocation]:
    allocations = _whole(_returned(sale, product, quantity, refund_of), quantity)
    try:
        with transaction.atomic():
            stock.restock(
                sale.branch,
                allocations,
                by=by,
                document=(SALE_DOCUMENT, sale.pk),
                kind="refund",
                status="quarantine",
            )
    except DomainError as exc:
        if outcome is not None:
            outcome.problem(
                row.number if row else None,
                _("%(product)s: the stock wasn't moved (%(reason)s).")
                % {"product": product.name, "reason": exc},
            )
    return allocations


def _returned(sale: Sale, product: Product, quantity: Decimal, refund_of: str):
    """The batches a refund goes back to: the original receipt's, when the file names it."""
    refund_of = (refund_of or "").strip()
    if not refund_of:
        return []
    original = (
        Sale.objects.imported()
        .filter(
            company_id=sale.company_id,
            branch_id=sale.branch_id,
            kind=Sale.Kind.SALE,
            number=refund_of,
            sold_at__lte=sale.sold_at,
            voided_at__isnull=True,
        )
        .order_by("-sold_at", "-pk")
        .first()
    )
    if original is None:
        return []
    found, left = [], quantity
    for line in original.lines.filter(product=product, status=Status.MATCHED).order_by(
        "line_number", "pk"
    ):
        if left <= 0:
            break
        take = min(line.quantity, left)
        unit_cost = (line.cost / line.quantity).quantize(CENT) if line.cost is not None else None
        found.append(Allocation(line.batch_id, take, unit_cost))
        left -= take
    return found


def _whole(allocations: list[Allocation], quantity: Decimal) -> list[Allocation]:
    """Allocations that add up to the line: whatever no batch covered has no batch (the
    stock module's shortfall, or a stub that keeps no stock yet)."""
    kept = [a for a in allocations if a.quantity and a.quantity > 0]
    covered = sum((a.quantity for a in kept), ZERO)
    if covered < quantity:
        kept.append(Allocation(None, quantity - covered, None))
    elif covered > quantity:
        # Never more than the line: trim from the end.
        trimmed, left = [], quantity
        for a in kept:
            if left <= 0:
                break
            take = min(a.quantity, left)
            trimmed.append(Allocation(a.batch_id, take, a.unit_cost))
            left -= take
        kept = trimmed
    return kept


# The match list ----------------------------------------------------------------------------


def waiting_lines(company, *, branch_ids: list[int] | None):
    rows = SaleLine.objects.filter(
        sale__company=company, status=Status.WAITING, sale__voided_at__isnull=True
    )
    if branch_ids is not None:
        rows = rows.filter(sale__branch_id__in=branch_ids)
    return rows


def match(company, code: str, product: Product, *, by) -> int:
    """`code` means `product` from now on: the stock module remembers it, and every waiting
    (or skipped) line with that code is settled. Returns how many lines were matched."""
    if product.company_id != company.pk:
        raise DomainError(_("Pick a product of this company."))
    code = (code or "").strip()[:64]
    if not code:
        raise DomainError(_("Pick a code to match."))
    stock.remember_code(product, by=by, kind="pos", code=code)
    pending = list(
        SaleLine.objects.filter(
            sale__company=company,
            code=code,
            status__in=(Status.WAITING, Status.SKIPPED),
            sale__voided_at__isnull=True,
        )
        .order_by("sale__sold_at", "sale_id", "line_number", "pk")
        .values_list("pk", flat=True)
    )
    done, days, imports = 0, set(), set()
    outcome = Outcome()
    for pk in pending:
        with transaction.atomic():
            line = (
                SaleLine.objects.select_for_update(of=("self",))
                .select_related("sale__branch", "sale__company")
                .filter(pk=pk, status__in=(Status.WAITING, Status.SKIPPED))
                .first()
            )
            if line is None:
                continue
            sale = line.sale
            settle(
                sale, product, line_number=line.line_number, waiting=line, by=by, outcome=outcome
            )
            done += 1
            days.add((sale.branch_id, sale.business_day))
            if sale.sales_import_id:
                imports.add(sale.sales_import_id)
    for import_id in imports:
        recount(import_id)
    audit.record(
        SalesAction.CODE_MATCHED,
        company_id=company.pk,
        actor=by.user if by is not None else None,
        target=product,
        code=code,
        lines=done,
    )
    if days:
        pairs = sorted(days)
        transaction.on_commit(lambda: notify_breaches(company.pk, pairs))
    transaction.on_commit(lambda: pulse.bump(company.pk, PULSE_LINES, PULSE_UNMATCHED))
    return done


def skip(company, code: str, *, by) -> int:
    """The waiting lines with `code` are not goods the stock keeps (a bag, a service)."""
    code = (code or "").strip()[:64]
    rows = SaleLine.objects.filter(
        sale__company=company, code=code, status=Status.WAITING, sale__voided_at__isnull=True
    )
    imports = set(
        rows.exclude(sale__sales_import=None).values_list("sale__sales_import_id", flat=True)
    )
    count = SaleLine.objects.filter(pk__in=list(rows.values_list("pk", flat=True))).update(
        status=Status.SKIPPED
    )
    for import_id in imports:
        recount(import_id)
    audit.record(
        SalesAction.CODE_SKIPPED,
        company_id=company.pk,
        actor=by.user if by is not None else None,
        target=company,
        code=code,
        lines=count,
    )
    transaction.on_commit(lambda: pulse.bump(company.pk, PULSE_LINES, PULSE_UNMATCHED))
    return count


def recount(import_id: int) -> None:
    """An import's matched and unmatched counts, in receipt lines, as they stand now."""
    found = defaultdict(set)
    for sale_id, line_number, status in SaleLine.objects.filter(
        sale__sales_import_id=import_id
    ).values_list("sale_id", "line_number", "status"):
        found[status].add((sale_id, line_number))
    SalesImport.objects.filter(pk=import_id).update(
        matched=len(found[Status.MATCHED]),
        unmatched=len(found[Status.WAITING]),
        breaches=SaleLine.objects.filter(sale__sales_import_id=import_id, over_cap=True)
        .values("sale_id", "line_number")
        .distinct()
        .count(),
        updated_at=timezone.now(),
    )


# The day check and the end of an import ------------------------------------------------------


def day_check(company, pairs) -> list[dict]:
    """Per branch and business day: what the imports brought (net of refunds) against the
    tills' totals (`DailySales.net`). A gap above 1 % of the tills is flagged."""
    pairs = sorted(set(pairs), key=lambda pair: (pair[1], pair[0]))
    if not pairs:
        return []
    branch_ids = {branch_id for branch_id, _day in pairs}
    days = {day for _branch, day in pairs}
    imported: dict[tuple[int, date], Decimal] = defaultdict(lambda: ZERO)
    for row in (
        Sale.objects.imported()
        .filter(
            company=company,
            branch_id__in=branch_ids,
            business_day__in=days,
            voided_at__isnull=True,
        )
        .values("branch_id", "business_day", "kind")
        .annotate(total=Sum("total"))
    ):
        sign = -1 if row["kind"] == Sale.Kind.REFUND else 1
        imported[(row["branch_id"], row["business_day"])] += sign * row["total"]
    tills = {
        (row["branch_id"], row["day"]): row["net"]
        for row in DailySales.objects.filter(
            company=company, branch_id__in=branch_ids, day__in=days
        ).values("branch_id", "day", "net")
    }
    names = dict(Branch.objects.filter(pk__in=branch_ids).values_list("pk", "name"))
    out = []
    for branch_id, day in pairs:
        brought = imported[(branch_id, day)]
        net = tills.get((branch_id, day))
        coverage = gap = None
        flagged = True
        if net is not None:
            gap = brought - net
            if net > 0:
                coverage = (brought / net * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
                flagged = abs(gap) * 100 > net * GAP_PERCENT
            else:
                flagged = brought != 0
        out.append(
            {
                "branch": {"id": branch_id, "name": names.get(branch_id, "")},
                "day": day.isoformat(),
                "imported": str(brought.quantize(CENT)),
                "tills": str(net.quantize(CENT)) if net is not None else None,
                "gap": str(gap.quantize(CENT)) if gap is not None else None,
                "coverage": str(coverage) if coverage is not None else None,
                "flagged": flagged,
            }
        )
    return out


def _finish(imp: SalesImport, *, rows: int, lines: int, outcome: Outcome, unreadable: int) -> None:
    company = imp.company
    days = sorted(outcome.days)
    with transaction.atomic():
        locked = SalesImport.objects.select_for_update().get(pk=imp.pk)
        locked.status = SalesImport.Status.READY
        locked.error = ""
        locked.rows = rows
        locked.lines = lines
        locked.receipts = outcome.receipts
        locked.matched = outcome.matched
        locked.unmatched = outcome.unmatched
        locked.duplicates = outcome.duplicates
        locked.unreadable = unreadable
        locked.problems = outcome.problems
        locked.day_check = day_check(company, days)
        locked.first_day = min((day for _b, day in days), default=None)
        locked.last_day = max((day for _b, day in days), default=None)
        locked.breaches = (
            SaleLine.objects.filter(sale__sales_import=locked, over_cap=True)
            .values("sale_id", "line_number")
            .distinct()
            .count()
        )
        locked.finished_at = timezone.now()
        locked.save()
        audit.record(
            SalesAction.IMPORT_DONE,
            company_id=company.pk,
            actor=None,
            target=locked,
            receipts=locked.receipts,
            lines=lines,
            matched=locked.matched,
            unmatched=locked.unmatched,
            duplicates=locked.duplicates,
        )
        transaction.on_commit(lambda: notify_breaches(company.pk, days))
        transaction.on_commit(lambda: pulse.bump(company.pk, PULSE_LINES, PULSE_UNMATCHED))


def _fail(imp: SalesImport, message: str) -> None:
    company_id = imp.company_id
    with transaction.atomic():
        SalesImport.objects.filter(pk=imp.pk).update(
            status=SalesImport.Status.FAILED,
            error=(message or "")[:300],
            finished_at=timezone.now(),
            updated_at=timezone.now(),
        )
        audit.record(
            SalesAction.IMPORT_FAILED,
            company_id=company_id,
            actor=None,
            target=imp,
            error=(message or "")[:300],
        )
        pk = imp.pk
        transaction.on_commit(lambda: import_failed(pk))
        transaction.on_commit(lambda: pulse.bump(company_id, PULSE_LINES))


# Notifications -------------------------------------------------------------------------------


def lines_url(company_id: int, **params) -> str:
    query = "&".join(f"{key}={value}" for key, value in params.items() if value not in (None, ""))
    return f"/c/{company_id}/sales/lines" + (f"?{query}" if query else "")


def notify_breaches(company_id: int, pairs) -> int:
    """One `sales.price_cap_breach` per branch and business day with prescription lines sold
    above the legal price, to the people who run sales there (owners included). Returns how
    many branch-days were told."""
    from apps.companies.models import Company

    company = Company.objects.filter(pk=company_id).first()
    if company is None:
        return 0
    told = 0
    for branch_id, day in sorted(set(pairs)):
        key = f"sales.cap_breach:{branch_id}:{day.isoformat()}"
        if alerts.already_sent(company_id, key):
            continue
        rows = list(
            SaleLine.objects.filter(
                sale__company_id=company_id,
                sale__branch_id=branch_id,
                sale__business_day=day,
                sale__voided_at__isnull=True,
                over_cap=True,
            )
            .select_related("sale", "product")
            .order_by("sale__sold_at", "pk")
        )
        receipts_lines = {(row.sale_id, row.line_number) for row in rows}
        if not receipts_lines:
            continue
        branch = Branch.objects.filter(pk=branch_id).first()
        if branch is None:
            continue
        count = len(receipts_lines)
        examples = rows[:3]

        def title(member, count=count, branch=branch):
            return ngettext(
                "%(count)s sale above the legal price at %(branch)s",
                "%(count)s sales above the legal price at %(branch)s",
                count,
            ) % {"count": count, "branch": branch.name}

        def body(member, day=day, examples=examples):
            lines = [
                _("%(product)s: %(price)s a pack, the cap is %(cap)s")
                % {
                    "product": line.product.name if line.product_id else line.name,
                    "price": msg.money(pack_price(line), company.base_currency),
                    "cap": msg.money(line.cap, company.base_currency),
                }
                for line in examples
            ]
            head = _("Prescription medicines sold on %(day)s.") % {"day": day.strftime("%d.%m.%Y")}
            return "\n".join([head, *lines])

        made = notify(
            alerts.managers(company, branch_id),
            "sales.price_cap_breach",
            title=title,
            body=body,
            url=lines_url(company_id, cap=1, branch=branch_id, **{"from": day, "to": day}),
            target=branch,
            dedupe_key=key,
        )
        told += 1 if made else 0
    return told


def import_failed(import_id: int) -> None:
    imp = (
        SalesImport.objects.select_related("company", "profile", "created_by__user")
        .filter(pk=import_id)
        .first()
    )
    if imp is None:
        return
    people = [imp.created_by] if imp.created_by_id else alerts.owners(imp.company)
    name, error = imp.profile.name, imp.error
    notify(
        people,
        "sales.import_failed",
        title=lambda member: (
            _("The sale lines import didn't finish (%(profile)s)") % {"profile": name}
        ),
        body=lambda member: error,
        url=f"/c/{imp.company_id}/sales/import?import={imp.pk}",
        target=imp,
        dedupe_key=f"sales.import_failed:{imp.pk}",
    )


def waiting_count(company, *, branch_ids: list[int] | None) -> int:
    return waiting_lines(company, branch_ids=branch_ids).count()


def codes(company, *, branch_ids: list[int] | None, status: str = Status.WAITING, limit=200):
    """The match list: one row per code with its lines, first and last day and branches."""
    rows = SaleLine.objects.filter(
        sale__company=company, status=status, sale__voided_at__isnull=True
    )
    if branch_ids is not None:
        rows = rows.filter(sale__branch_id__in=branch_ids)
    grouped = (
        rows.values("code")
        .annotate(lines=Count("pk"), total=Sum("total"))
        .order_by("-lines", "code")[:limit]
    )
    found = []
    for group in grouped:
        sample = (
            rows.filter(code=group["code"])
            .select_related("sale__branch")
            .order_by("-sale__sold_at")
        )
        first = sample.last()
        latest = sample.first()
        branches = sorted(set(sample.values_list("sale__branch__name", flat=True)))
        found.append(
            {
                "code": group["code"],
                "name": latest.name if latest else group["code"],
                "lines": group["lines"],
                "total": str((group["total"] or ZERO).quantize(CENT)),
                "first_day": first.sale.business_day.isoformat() if first else None,
                "last_day": latest.sale.business_day.isoformat() if latest else None,
                "last_sold_at": latest.sale.sold_at if latest else None,
                "branches": branches,
            }
        )
    return found
