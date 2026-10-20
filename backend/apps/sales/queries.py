"""Read functions of sales and cash, for other apps, the dashboard and the AI tools.

A function returning branch-bound data takes the required keyword
`branch_ids: list[int] | None` (callers pass `apps.members.scope.branch_ids(member)`).

Money comes back as strings ("48120000.00"), never floats. Analytics follow the shared shape of
docs/PLAN-OWNER.md §4 (`range`, `compare`, `currency`, `totals`, `previous`, `series`,
`breakdown`), so the dashboard's KPI and chart cards and package N can read them without
knowing sales.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db.models import F, OuterRef, Q, QuerySet, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.companies.models import Branch
from apps.console import contracts
from apps.console.registry import OffboardStep, QueueAction, QueueItem, SearchHit, StreamItem
from apps.core.money import MoneyField, quantize
from apps.finance.models import MoneyAccount
from apps.members import scope
from apps.members.models import Membership
from apps.sales import bot_messages as msg
from apps.sales import cash
from apps.sales.conf import get_settings
from apps.sales.days import business_day, local
from apps.sales.models import (
    CashMovement,
    CashShift,
    DailySales,
    PaymentMethod,
    Register,
    Sale,
    SalesTarget,
    ShiftPayment,
)
from apps.sales.rollup import avg

ZERO = Decimal(0)
Status = CashShift.Status
CLOSED_STATUSES = (Status.CLOSED, Status.VERIFIED, Status.DISPUTED)
GROUPS = ("day", "week", "month", "branch", "cashier", "method", "hour", "weekday_hour")


def m(value) -> str:
    """Money as the API sends it."""
    return str(quantize(value if value is not None else ZERO))


def person(membership: Membership | None) -> dict | None:
    if membership is None:
        return None
    return {"id": membership.pk, "name": str(membership)}


def restrict(queryset: QuerySet, branch_ids: list[int] | None, field: str = "branch") -> QuerySet:
    return scope.restrict(queryset, branch_ids, field=field)


# Shifts --------------------------------------------------------------------------------


def with_net(queryset: QuerySet[CashShift]) -> QuerySet[CashShift]:
    """Shifts annotated with `net`, `sales_total` and `refunds_total` from their payments."""
    payments = ShiftPayment.objects.filter(shift=OuterRef("pk")).values("shift")
    zero = Value(ZERO, output_field=MoneyField())
    return queryset.annotate(
        sales_total=Coalesce(Subquery(payments.annotate(t=Sum("sales")).values("t")), zero),
        refunds_total=Coalesce(Subquery(payments.annotate(t=Sum("refunds")).values("t")), zero),
    ).annotate(net=F("sales_total") - F("refunds_total"))


def shifts(company, filters: dict, limit: int | None, *, branch_ids: list[int] | None):
    """Shifts of `company` inside the scope, newest first. Filters: branch (ids), register,
    cashier, status (list), from/to (business days), has_difference (bool), q (code or
    cashier name), mismatch (AI)."""
    rows = with_net(
        restrict(CashShift.objects.for_company(company), branch_ids).select_related(
            "branch", "register", "cashier__user", "verified_by", "closed_by"
        )
    )
    if branches := filters.get("branch"):
        rows = rows.filter(branch_id__in=branches)
    if register := filters.get("register"):
        rows = rows.filter(register_id=register)
    if cashier := filters.get("cashier"):
        rows = rows.filter(cashier_id__in=cashier if isinstance(cashier, list) else [cashier])
    if statuses := filters.get("status"):
        rows = rows.filter(status__in=statuses)
    if start := filters.get("from"):
        rows = rows.filter(business_day__gte=start)
    if end := filters.get("to"):
        rows = rows.filter(business_day__lte=end)
    has_difference = filters.get("has_difference")
    if has_difference is True:
        rows = rows.exclude(difference=0).exclude(difference__isnull=True)
    elif has_difference is False:
        rows = rows.filter(Q(difference=0) | Q(difference__isnull=True))
    if filters.get("mismatch"):
        rows = rows.filter(ai_mismatch=True)
    if q := (filters.get("q") or "").strip():
        rows = rows.filter(_shift_text(q))
    rows = rows.order_by("-opened_at", "-pk")
    return rows[:limit] if limit else rows


def _shift_text(q: str) -> Q:
    code, _sep, number = q.rpartition("-")
    match = (
        Q(cashier__first_name__icontains=q)
        | Q(cashier__last_name__icontains=q)
        | Q(register__name__icontains=q)
        | Q(z_number__icontains=q)
    )
    if q.isdigit():
        match |= Q(number=int(q))
    elif number.isdigit() and code:
        match |= Q(number=int(number), branch__code__iexact=code)
    return match


def shift_for(member: Membership, shift_id: int) -> CashShift | None:
    """One shift of the member's company inside their scope (else None: 404)."""
    rows = shifts(member.company, {}, None, branch_ids=scope.branch_ids(member))
    return (
        rows.select_related("company", "register__cash_account")
        .prefetch_related("payments__method")
        .filter(pk=shift_id)
        .first()
    )


def shift_timeline(shift: CashShift, member: Membership) -> list[dict]:
    """What happened to a shift, in order: opened, movements, closed, AI, verified/disputed and
    corrections (from the audit log, filtered to what the member may see)."""
    from apps.audit import queries as audit_queries

    events: list[dict] = [
        {
            "at": shift.opened_at.isoformat(),
            "kind": "opened",
            "actor": person(shift.cashier),
            "amount": m(shift.opening_float),
        }
    ]
    for movement in shift.movements.select_related("receiver", "created_by").order_by("created_at"):
        events.append(
            {
                "at": movement.created_at.isoformat(),
                "kind": f"movement.{movement.kind}",
                "actor": person(movement.created_by),
                "amount": m(movement.amount),
                "status": movement.status,
                "receiver": person(movement.receiver),
                "text": movement.reason,
            }
        )
        if movement.confirmed_at and movement.kind == CashMovement.Kind.HANDOVER:
            events.append(
                {
                    "at": movement.confirmed_at.isoformat(),
                    "kind": "handover.confirmed",
                    "actor": person(movement.confirmed_by),
                    "amount": m(movement.amount),
                }
            )
        if movement.declined_at:
            events.append(
                {
                    "at": movement.declined_at.isoformat(),
                    "kind": "handover.declined",
                    "actor": person(movement.receiver),
                    "amount": m(movement.amount),
                    "text": movement.decline_reason,
                }
            )
    if shift.closed_at:
        events.append(
            {
                "at": shift.closed_at.isoformat(),
                "kind": "force_closed" if shift.forced else "closed",
                "actor": person(shift.closed_by),
                "amount": m(shift.counted_cash) if shift.counted_cash is not None else None,
                "text": shift.note if shift.forced else shift.cashier_note,
            }
        )
    seen = {"sales.shift_opened", "sales.shift_closed", "sales.shift_force_closed"}
    for row in audit_queries.events(member, target_type="cashshift", target_id=shift.pk):
        if row.action in seen:
            continue
        details = row.details or {}
        events.append(
            {
                "at": row.created_at.isoformat(),
                "kind": row.action.removeprefix("sales.shift_"),
                "actor": {"id": row.actor_id, "name": str(row.actor)} if row.actor_id else None,
                "amount": details.get("difference"),
                "text": details.get("reason") or details.get("note") or "",
            }
        )
    events.sort(key=lambda event: event["at"])
    return events


def visible_count(member: Membership, **filters) -> int:
    return restrict(
        CashShift.objects.for_company(member.company).filter(**filters), scope.branch_ids(member)
    ).count()


def open_shifts_count(member: Membership) -> int:
    return visible_count(member, status=Status.OPEN)


def to_verify_count(member: Membership) -> int:
    return visible_count(member, status=Status.CLOSED)


def current_shift(member: Membership) -> CashShift | None:
    return (
        CashShift.objects.filter(cashier=member, status=Status.OPEN)
        .select_related("branch", "register__cash_account")
        .first()
    )


# Analytics -----------------------------------------------------------------------------


@dataclass
class Totals:
    sales: Decimal = ZERO
    refunds: Decimal = ZERO
    receipts: int = 0
    cash_net: Decimal = ZERO
    shifts: int = 0
    difference: Decimal = ZERO

    @property
    def net(self) -> Decimal:
        return self.sales - self.refunds

    def add(self, other: Totals) -> None:
        self.sales += other.sales
        self.refunds += other.refunds
        self.receipts += other.receipts
        self.cash_net += other.cash_net
        self.shifts += other.shifts
        self.difference += other.difference

    def as_dict(self) -> dict:
        net = self.net
        share = (self.cash_net / net * 100).quantize(Decimal("0.1")) if net else ZERO
        return {
            "net": m(net),
            "sales": m(self.sales),
            "refunds": m(self.refunds),
            "receipts": self.receipts,
            "avg_check": m(avg(net, self.receipts)),
            "cash_share": str(share),
            "shifts": self.shifts,
            "cash_difference": m(self.difference),
        }


def daily_rows(company, start: date, end: date, *, branch_ids: list[int] | None):
    rows = DailySales.objects.for_company(company).filter(day__range=(start, end))
    return restrict(rows, branch_ids).select_related("branch").order_by("day", "branch__order")


def _row_totals(row: DailySales) -> Totals:
    cash_net = sum(
        (
            Decimal(v["net"])
            for v in row.by_method.values()
            if v.get("kind") == PaymentMethod.Kind.CASH
        ),
        ZERO,
    )
    return Totals(row.sales, row.refunds, row.receipts, cash_net, row.shifts, row.cash_difference)


def totals(company, start: date, end: date, *, branch_ids: list[int] | None) -> Totals:
    found = Totals()
    for row in daily_rows(company, start, end, branch_ids=branch_ids):
        found.add(_row_totals(row))
    return found


def _period_key(day: date, group: str) -> date:
    if group == "week":
        return day - timedelta(days=day.weekday())
    if group == "month":
        return day.replace(day=1)
    return day


def _periods(start: date, end: date, group: str) -> list[date]:
    keys, day = [], start
    while day <= end:
        key = _period_key(day, group)
        if not keys or keys[-1] != key:
            keys.append(key)
        day += timedelta(days=1)
    return keys


def summary(
    company,
    start: date,
    end: date,
    group_by: str,
    *,
    branch_ids: list[int] | None,
    compare: tuple[date, date] | None = None,
) -> dict:
    """Sales for a range in the analytics shape. `group_by` day|week|month gives a series by
    period and a breakdown by branch; branch|cashier|method a daily series and a breakdown by
    that; hour and weekday_hour a series of hours (weekday x hour cells), estimated from shift
    hours where single receipts weren't recorded."""
    if group_by not in GROUPS:
        raise ValueError(f"group_by must be one of {GROUPS}.")
    rows = list(daily_rows(company, start, end, branch_ids=branch_ids))
    found = Totals()
    for row in rows:
        found.add(_row_totals(row))
    result = {
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "compare": None,
        "currency": company.base_currency,
        "totals": found.as_dict(),
        "previous": None,
        "series": [],
        "breakdown": [],
    }
    previous_rows: list[DailySales] = []
    if compare is not None:
        previous_rows = list(daily_rows(company, compare[0], compare[1], branch_ids=branch_ids))
        previous = Totals()
        for row in previous_rows:
            previous.add(_row_totals(row))
        result["compare"] = {"from": compare[0].isoformat(), "to": compare[1].isoformat()}
        result["previous"] = previous.as_dict()

    if group_by in ("hour", "weekday_hour"):
        series, estimated = _hours(
            company, start, end, branch_ids=branch_ids, by_weekday=group_by == "weekday_hour"
        )
        result["series"] = series
        result["estimated"] = estimated
        return result

    group = group_by if group_by in ("week", "month") else "day"
    by_period: dict[date, Totals] = defaultdict(Totals)
    for row in rows:
        by_period[_period_key(row.day, group)].add(_row_totals(row))
    result["series"] = [
        {"date": key.isoformat(), **_series_point(by_period.get(key, Totals()))}
        for key in _periods(start, end, group)
    ]
    if compare is not None:
        prev_by_period: dict[date, Totals] = defaultdict(Totals)
        for row in previous_rows:
            prev_by_period[_period_key(row.day, group)].add(_row_totals(row))
        prev_keys = _periods(compare[0], compare[1], group)
        for point, key in zip(result["series"], prev_keys, strict=False):
            point["previous_net"] = m(prev_by_period.get(key, Totals()).net)

    dimension = group_by if group_by in ("branch", "cashier", "method") else "branch"
    if dimension == "branch":
        result["breakdown"] = _by_branch(rows, previous_rows, found.net)
    elif dimension == "method":
        result["breakdown"] = _by_method(rows, previous_rows, found.net)
    else:
        result["breakdown"] = _by_cashier(company, start, end, compare, branch_ids, found.net)
    return result


def _series_point(t: Totals) -> dict:
    net = t.net
    return {
        "net": m(net),
        "sales": m(t.sales),
        "refunds": m(t.refunds),
        "receipts": t.receipts,
        "avg_check": m(avg(net, t.receipts)),
    }


def _share(part: Decimal, whole: Decimal) -> str:
    return str((part / whole * 100).quantize(Decimal("0.1"))) if whole else "0.0"


def _by_branch(rows, previous_rows, total_net: Decimal) -> list[dict]:
    current: dict[int, Totals] = defaultdict(Totals)
    names: dict[int, str] = {}
    by_method: dict[int, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    for row in rows:
        current[row.branch_id].add(_row_totals(row))
        names[row.branch_id] = row.branch.name
        for key, value in row.by_method.items():
            by_method[row.branch_id][key] += Decimal(value["net"])
    previous: dict[int, Totals] = defaultdict(Totals)
    for row in previous_rows:
        previous[row.branch_id].add(_row_totals(row))
        names.setdefault(row.branch_id, row.branch.name)
    method_names = _method_names(rows)
    out = []
    for branch_id in sorted(names, key=lambda pk: -current[pk].net):
        t = current[branch_id]
        out.append(
            {
                "key": str(branch_id),
                "label": names[branch_id],
                **_series_point(t),
                "share": _share(t.net, total_net),
                "previous_net": m(previous[branch_id].net) if previous_rows else None,
                "methods": [
                    {"key": key, "label": method_names.get(key, key), "net": m(value)}
                    for key, value in sorted(by_method[branch_id].items(), key=lambda kv: -kv[1])
                ],
            }
        )
    return out


def _method_names(rows) -> dict[str, str]:
    names = {}
    for row in rows:
        for key, value in row.by_method.items():
            names[key] = value.get("name") or key
    return names


def _by_method(rows, previous_rows, total_net: Decimal) -> list[dict]:
    current: dict[str, dict] = {}
    for row in rows:
        for key, value in row.by_method.items():
            bucket = current.setdefault(
                key,
                {
                    "label": value.get("name", key),
                    "kind": value.get("kind", ""),
                    "sales": ZERO,
                    "refunds": ZERO,
                },
            )
            bucket["sales"] += Decimal(value["sales"])
            bucket["refunds"] += Decimal(value["refunds"])
    previous: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for row in previous_rows:
        for key, value in row.by_method.items():
            previous[key] += Decimal(value["net"])
    out = []
    for key, bucket in sorted(current.items(), key=lambda kv: -(kv[1]["sales"] - kv[1]["refunds"])):
        net = bucket["sales"] - bucket["refunds"]
        out.append(
            {
                "key": key,
                "label": bucket["label"],
                "kind": bucket["kind"],
                "net": m(net),
                "sales": m(bucket["sales"]),
                "refunds": m(bucket["refunds"]),
                "share": _share(net, total_net),
                "previous_net": m(previous[key]) if previous_rows else None,
            }
        )
    return out


def _closed_shifts(company, start: date, end: date, branch_ids: list[int] | None):
    return with_net(
        restrict(
            CashShift.objects.for_company(company).filter(
                business_day__range=(start, end), status__in=CLOSED_STATUSES
            ),
            branch_ids,
        )
    )


def _by_cashier(company, start, end, compare, branch_ids, total_net: Decimal) -> list[dict]:
    def collect(a: date, b: date) -> dict[int, dict]:
        found: dict[int, dict] = {}
        for shift in _closed_shifts(company, a, b, branch_ids).select_related("cashier"):
            row = found.setdefault(
                shift.cashier_id,
                {
                    "label": str(shift.cashier),
                    "net": ZERO,
                    "sales": ZERO,
                    "refunds": ZERO,
                    "receipts": 0,
                    "shifts": 0,
                },
            )
            row["net"] += shift.net
            row["sales"] += shift.sales_total
            row["refunds"] += shift.refunds_total
            row["receipts"] += shift.receipts
            row["shifts"] += 1
        return found

    current = collect(start, end)
    previous = collect(*compare) if compare else {}
    return [
        {
            "key": str(member_id),
            "label": row["label"],
            "net": m(row["net"]),
            "sales": m(row["sales"]),
            "refunds": m(row["refunds"]),
            "receipts": row["receipts"],
            "avg_check": m(avg(row["net"], row["receipts"])),
            "shifts": row["shifts"],
            "share": _share(row["net"], total_net),
            "previous_net": m(previous.get(member_id, {}).get("net", ZERO)) if compare else None,
        }
        for member_id, row in sorted(current.items(), key=lambda kv: -kv[1]["net"])
    ]


def _hours(company, start, end, *, branch_ids, by_weekday: bool) -> tuple[list[dict], bool]:
    """Net by hour (and weekday): recorded receipts at their time; shifts without receipts spread
    evenly over the minutes they were open (an estimate)."""
    cells: dict[tuple[int, int], dict] = defaultdict(lambda: {"net": ZERO, "receipts": Decimal(0)})
    estimated = False
    sales = restrict(
        Sale.objects.for_company(company).filter(
            business_day__range=(start, end), voided_at__isnull=True
        ),
        branch_ids,
    )
    with_receipts = set(sales.exclude(shift__isnull=True).values_list("shift_id", flat=True))
    for sale in sales.only("sold_at", "total", "kind"):
        at = local(company, sale.sold_at)
        key = (at.weekday() if by_weekday else 0, at.hour)
        sign = -1 if sale.kind == Sale.Kind.REFUND else 1
        cells[key]["net"] += sign * sale.total
        if sale.kind == Sale.Kind.SALE:
            cells[key]["receipts"] += 1
    for shift in _closed_shifts(company, start, end, branch_ids).exclude(pk__in=with_receipts):
        if not shift.closed_at or shift.closed_at <= shift.opened_at:
            continue
        estimated = True
        opened, closed = local(company, shift.opened_at), local(company, shift.closed_at)
        span = Decimal((closed - opened).total_seconds())
        cursor = opened
        while cursor < closed:
            next_hour = (cursor + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            piece_end = min(next_hour, closed)
            part = Decimal((piece_end - cursor).total_seconds()) / span
            key = (cursor.weekday() if by_weekday else 0, cursor.hour)
            cells[key]["net"] += shift.net * part
            cells[key]["receipts"] += Decimal(shift.receipts) * part
            cursor = piece_end
    series = []
    weekdays = range(7) if by_weekday else range(1)
    for weekday in weekdays:
        for hour in range(24):
            cell = cells.get((weekday, hour), {"net": ZERO, "receipts": Decimal(0)})
            point = {
                "hour": hour,
                "net": m(cell["net"]),
                "receipts": int(cell["receipts"].to_integral_value()),
            }
            if by_weekday:
                point["weekday"] = weekday
            series.append(point)
    return series, estimated


# Cashier scorecard -----------------------------------------------------------------------


def cashier_scorecard(
    company, start: date, end: date, *, branch_ids: list[int] | None
) -> list[dict]:
    """Per cashier: shifts, sales, average check, how often their cash matched (within the
    tolerance), shortages and surpluses, late openings, verification."""
    settings = get_settings(company)
    tolerance = settings.cash_tolerance
    rows: dict[int, dict] = {}
    shifts_qs = _closed_shifts(company, start, end, branch_ids).select_related("cashier", "branch")
    for shift in shifts_qs:
        row = rows.setdefault(
            shift.cashier_id,
            {
                "member": person(shift.cashier),
                "shifts": 0,
                "net": ZERO,
                "receipts": 0,
                "counted": 0,
                "accurate": 0,
                "shortages": 0,
                "surpluses": 0,
                "shortage_total": ZERO,
                "surplus_total": ZERO,
                "difference_total": ZERO,
                "verified": 0,
                "disputed": 0,
                "forced": 0,
                "late_opens": 0,
                "hours": Decimal(0),
                "last_shift_at": None,
                "branches": set(),
            },
        )
        row["shifts"] += 1
        row["net"] += shift.net
        row["receipts"] += shift.receipts
        row["branches"].add(shift.branch.name)
        if shift.difference is not None:
            row["counted"] += 1
            row["difference_total"] += shift.difference
            if abs(shift.difference) <= tolerance:
                row["accurate"] += 1
            elif shift.difference < 0:
                row["shortages"] += 1
            else:
                row["surpluses"] += 1
            if shift.difference < 0:
                row["shortage_total"] += shift.difference
            elif shift.difference > 0:
                row["surplus_total"] += shift.difference
        if shift.status == Status.VERIFIED:
            row["verified"] += 1
        elif shift.status == Status.DISPUTED:
            row["disputed"] += 1
        if shift.forced:
            row["forced"] += 1
        if _opened_late(shift, company, settings.late_open_minutes):
            row["late_opens"] += 1
        if shift.closed_at:
            row["hours"] += Decimal((shift.closed_at - shift.opened_at).total_seconds()) / 3600
        if row["last_shift_at"] is None or shift.opened_at > row["last_shift_at"]:
            row["last_shift_at"] = shift.opened_at
    out = []
    for row in rows.values():
        counted = row["counted"]
        out.append(
            {
                "member": row["member"],
                "branches": sorted(row["branches"]),
                "shifts": row["shifts"],
                "net": m(row["net"]),
                "avg_per_shift": m(row["net"] / row["shifts"]) if row["shifts"] else m(ZERO),
                "receipts": row["receipts"],
                "avg_check": m(avg(row["net"], row["receipts"])),
                "accuracy": str((Decimal(row["accurate"]) / counted * 100).quantize(Decimal("0.1")))
                if counted
                else None,
                "shortages": row["shortages"],
                "surpluses": row["surpluses"],
                "shortage_total": m(row["shortage_total"]),
                "surplus_total": m(row["surplus_total"]),
                "difference_total": m(row["difference_total"]),
                "verified": row["verified"],
                "disputed": row["disputed"],
                "forced": row["forced"],
                "late_opens": row["late_opens"],
                "avg_hours": str((row["hours"] / row["shifts"]).quantize(Decimal("0.1")))
                if row["shifts"]
                else "0.0",
                "last_shift_at": row["last_shift_at"].isoformat() if row["last_shift_at"] else None,
            }
        )
    out.sort(key=lambda row: -Decimal(row["net"]))
    return out


def _opened_late(shift: CashShift, company, grace_minutes: int) -> bool:
    opens = shift.branch.opens_at
    if opens is None:
        return False
    at = local(company, shift.opened_at)
    if at.date() != shift.business_day:
        return False
    due = at.replace(hour=opens.hour, minute=opens.minute, second=0, microsecond=0) + timedelta(
        minutes=grace_minutes
    )
    return at > due


# Today and cash ----------------------------------------------------------------------------


def _today_net(company, branch_ids: list[int] | None, day: date) -> dict[int, dict]:
    """Per branch for one business day: net and receipts of closed shifts, loose receipts and
    the receipts recorded in open shifts so far."""
    found: dict[int, dict] = defaultdict(lambda: {"net": ZERO, "receipts": 0})
    for shift in _closed_shifts(company, day, day, branch_ids):
        found[shift.branch_id]["net"] += shift.net
        found[shift.branch_id]["receipts"] += shift.receipts
    sales = restrict(
        Sale.objects.for_company(company).filter(business_day=day, voided_at__isnull=True),
        branch_ids,
    ).exclude(shift__status__in=CLOSED_STATUSES)
    for sale in sales.only("branch_id", "total", "kind"):
        sign = -1 if sale.kind == Sale.Kind.REFUND else 1
        found[sale.branch_id]["net"] += sign * sale.total
        if sale.kind == Sale.Kind.SALE:
            found[sale.branch_id]["receipts"] += 1
    return found


def cash_by_branch(company, branch_ids: list[int] | None) -> dict[int, dict]:
    """Per branch: each till now (with its open shift) and the safe's balance."""
    open_shifts = {
        shift.register_id: shift
        for shift in restrict(
            CashShift.objects.for_company(company).filter(status=Status.OPEN), branch_ids
        ).select_related("cashier", "register")
    }
    found: dict[int, dict] = defaultdict(lambda: {"tills": [], "safe": None, "total": ZERO})
    registers = restrict(
        Register.objects.for_company(company).filter(is_active=True), branch_ids
    ).select_related("cash_account", "branch")
    for register in registers:
        shift = open_shifts.get(register.pk)
        amount = cash.till_now(register, shift)
        found[register.branch_id]["tills"].append(
            {"register": register, "shift": shift, "amount": amount}
        )
        found[register.branch_id]["total"] += amount
    safes = restrict(
        MoneyAccount.objects.filter(company=company, kind=MoneyAccount.Kind.SAFE, is_active=True),
        branch_ids,
    )
    for safe in safes:
        if safe.branch_id is None:
            continue
        bucket = found[safe.branch_id]
        bucket["safe"] = safe
        bucket["total"] += safe.balance
    return found


def today(company, now: datetime, *, branch_ids: list[int] | None) -> list[dict]:
    """`GET sales/today/`: per branch, status, who opened it and when, open tills, sales so far,
    cash in the branch and what needs attention."""
    from apps.console.queries import branch_status
    from apps.timeoff.models import Holiday

    settings = get_settings(company)
    day = business_day(company, now, ends_at=settings.business_day_ends_at)
    at = local(company, now)
    holiday = Holiday.objects.filter(company=company, date=at.date()).exists()
    branches = restrict(
        Branch.objects.for_company(company).filter(is_active=True), branch_ids, field="id"
    )
    sales = _today_net(company, branch_ids, day)
    cash_rows = cash_by_branch(company, branch_ids)
    first_shifts = {}
    for shift in (
        restrict(CashShift.objects.for_company(company).filter(business_day=day), branch_ids)
        .select_related("cashier")
        .order_by("opened_at")
    ):
        first_shifts.setdefault(shift.branch_id, shift)
    differences = defaultdict(list)
    for shift in _closed_shifts(company, day, day, branch_ids).select_related("cashier"):
        if shift.difference is not None and abs(shift.difference) > settings.cash_tolerance:
            differences[shift.branch_id].append(shift)
    pending = defaultdict(lambda: [0, ZERO])
    for movement in restrict(
        CashMovement.objects.filter(cash.in_transit_filter(), company=company), branch_ids
    ):
        pending[movement.branch_id][0] += 1
        pending[movement.branch_id][1] += movement.amount
    month_targets = {
        target.branch_id: target
        for target in SalesTarget.objects.filter(
            company=company, month=day.replace(day=1), membership=None
        )
    }
    out = []
    for branch in branches.order_by("order", "name"):
        first = first_shifts.get(branch.pk)
        opened_at = local(company, first.opened_at).isoformat() if first else None
        card = {"sales": {"opened_at": opened_at}}
        status = branch_status(branch, at, holiday=holiday, card=card)
        tills = cash_rows[branch.pk]["tills"]
        alerts = []
        if status == "not_opened":
            alerts.append({"kind": "not_opened", "severity": "critical"})
        for shift in differences[branch.pk]:
            alerts.append(
                {
                    "kind": "difference",
                    "severity": "critical",
                    "shift": {"id": shift.pk, "code": shift.code},
                    "amount": m(shift.difference),
                }
            )
        if pending[branch.pk][0]:
            alerts.append(
                {
                    "kind": "in_transit",
                    "severity": "warning",
                    "count": pending[branch.pk][0],
                    "amount": m(pending[branch.pk][1]),
                }
            )
        if branch.cash_limit and cash_rows[branch.pk]["total"] > branch.cash_limit:
            alerts.append(
                {
                    "kind": "over_limit",
                    "severity": "warning",
                    "amount": m(cash_rows[branch.pk]["total"]),
                }
            )
        target = month_targets.get(branch.pk)
        out.append(
            {
                "id": branch.pk,
                "name": branch.name,
                "code": branch.code,
                "status": status,
                "opens_at": branch.opens_at.strftime("%H:%M") if branch.opens_at else None,
                "closes_at": branch.closes_at.strftime("%H:%M") if branch.closes_at else None,
                "opened_at": opened_at,
                "opened_by": person(first.cashier) if first else None,
                "open_tills": [
                    {
                        "register": {"id": till["register"].pk, "name": till["register"].name},
                        "shift": {
                            "id": till["shift"].pk,
                            "code": till["shift"].code,
                            "since": till["shift"].opened_at.isoformat(),
                        },
                        "cashier": person(till["shift"].cashier),
                        "amount": m(till["amount"]),
                    }
                    for till in tills
                    if till["shift"] is not None
                ],
                "tills": len(tills),
                "net": m(sales[branch.pk]["net"]),
                "receipts": sales[branch.pk]["receipts"],
                "cash_in_branch": m(cash_rows[branch.pk]["total"]),
                "cash_limit": m(branch.cash_limit) if branch.cash_limit else None,
                "target": _target_pace(target, company, day, branch_ids=[branch.pk])
                if target
                else None,
                "alerts": alerts,
            }
        )
    return out


def cash_positions(company, *, branch_ids: list[int] | None, now: datetime | None = None) -> dict:
    """ "Where is my cash": tills, safes, in transit, held by people, sent to the bank."""
    now = now or timezone.now()
    rows = cash_by_branch(company, branch_ids)
    branches = {
        b.pk: b
        for b in restrict(
            Branch.objects.for_company(company).filter(is_active=True), branch_ids, field="id"
        )
    }
    totals = {
        "tills": ZERO,
        "safes": ZERO,
        "in_transit": ZERO,
        "declined": ZERO,
        "people": ZERO,
        "to_bank": ZERO,
    }
    out_branches = []
    for branch_id, branch in sorted(branches.items(), key=lambda kv: (kv[1].order, kv[1].name)):
        bucket = rows.get(branch_id) or {"tills": [], "safe": None, "total": ZERO}
        tills_total = sum((till["amount"] for till in bucket["tills"]), ZERO)
        safe = bucket["safe"]
        totals["tills"] += tills_total
        totals["safes"] += safe.balance if safe else ZERO
        out_branches.append(
            {
                "id": branch_id,
                "name": branch.name,
                "code": branch.code,
                "cash_limit": m(branch.cash_limit) if branch.cash_limit else None,
                "tills": [
                    {
                        "register": {"id": till["register"].pk, "name": till["register"].name},
                        "amount": m(till["amount"]),
                        "shift": {
                            "id": till["shift"].pk,
                            "code": till["shift"].code,
                            "cashier": person(till["shift"].cashier),
                            "since": till["shift"].opened_at.isoformat(),
                        }
                        if till["shift"]
                        else None,
                    }
                    for till in bucket["tills"]
                ],
                "safe": {"account_id": safe.pk, "name": safe.name, "amount": m(safe.balance)}
                if safe
                else None,
                "total": m(bucket["total"]),
            }
        )
    movements = restrict(
        CashMovement.objects.filter(
            company=company,
            kind=CashMovement.Kind.HANDOVER,
            voided_at__isnull=True,
            confirmed_at__isnull=True,
        ),
        branch_ids,
    ).select_related("created_by", "receiver", "branch", "register")
    in_transit, declined = [], []
    for movement in movements.order_by("created_at"):
        row = {
            "id": movement.pk,
            "amount": m(movement.amount),
            "from": person(movement.created_by),
            "to": person(movement.receiver),
            "branch": {"id": movement.branch_id, "name": movement.branch.name},
            "register": {"id": movement.register_id, "name": movement.register.name},
            "since": movement.created_at.isoformat(),
            "hours": int((now - movement.created_at).total_seconds() // 3600),
            "reason": movement.reason,
        }
        if movement.declined_at:
            row["declined_at"] = movement.declined_at.isoformat()
            row["decline_reason"] = movement.decline_reason
            declined.append(row)
            totals["declined"] += movement.amount
        else:
            in_transit.append(row)
            totals["in_transit"] += movement.amount
    people = []
    held = restrict(
        MoneyAccount.objects.filter(
            company=company, kind=MoneyAccount.Kind.EMPLOYEE, is_active=True
        )
        .exclude(balance=0)
        .select_related("holder"),
        branch_ids,
    )
    for account in held.order_by("-balance"):
        people.append(
            {
                "member": person(account.holder),
                "account_id": account.pk,
                "amount": m(account.balance),
            }
        )
        totals["people"] += account.balance
    sent = restrict(
        CashMovement.objects.filter(
            company=company,
            kind=CashMovement.Kind.TO_BANK,
            voided_at__isnull=True,
            created_at__gte=now - timedelta(days=30),
        ),
        branch_ids,
    ).select_related("to_account", "created_by", "branch")
    to_bank = []
    for movement in sent.order_by("-created_at")[:20]:
        to_bank.append(
            {
                "id": movement.pk,
                "amount": m(movement.amount),
                "account": {"id": movement.to_account_id, "name": str(movement.to_account)}
                if movement.to_account_id
                else None,
                "at": movement.created_at.isoformat(),
                "by": person(movement.created_by),
                "branch": {"id": movement.branch_id, "name": movement.branch.name},
            }
        )
        totals["to_bank"] += movement.amount
    return {
        "currency": company.base_currency,
        "totals": {key: m(value) for key, value in totals.items()},
        "branches": out_branches,
        "in_transit": in_transit,
        "declined": declined,
        "people": people,
        "to_bank": to_bank,
        "oldest_pending": in_transit[0] if in_transit else None,
    }


# Targets ---------------------------------------------------------------------------------


def _month_days(month: date) -> int:
    return calendar.monthrange(month.year, month.month)[1]


def _target_pace(target: SalesTarget, company, day: date, *, branch_ids: list[int] | None) -> dict:
    month = target.month
    days = _month_days(month)
    if day < month:
        elapsed = 0
    elif day >= month.replace(day=days):
        elapsed = days
    else:
        elapsed = day.day
    end = month.replace(day=days)
    if target.membership_id is not None:
        actual = sum(
            (
                shift.net
                for shift in _closed_shifts(company, month, end, None).filter(
                    cashier_id=target.membership_id
                )
            ),
            ZERO,
        )
    else:
        scoped = [target.branch_id] if target.branch_id else branch_ids
        actual = totals(company, month, end, branch_ids=scoped).net
    amount = target.amount
    pace = amount * elapsed / days if days else ZERO
    projected = actual / elapsed * days if elapsed else ZERO
    remaining_days = days - elapsed
    return {
        "amount": m(amount),
        "actual": m(actual),
        "pace": m(pace),
        "projected": m(projected),
        "percent": str((actual / amount * 100).quantize(Decimal("0.1"))) if amount else "0.0",
        "days": days,
        "elapsed": elapsed,
        "per_day_needed": m(max(amount - actual, ZERO) / remaining_days)
        if remaining_days > 0
        else None,
        "ahead": actual >= pace,
    }


def targets(company, month: date, *, branch_ids: list[int] | None, today_day: date) -> list[dict]:
    """The month's targets the caller may see, each with its pacing."""
    rows = SalesTarget.objects.filter(company=company, month=month.replace(day=1)).select_related(
        "branch", "membership"
    )
    if branch_ids is not None:
        rows = rows.filter(
            Q(branch_id__in=branch_ids) | Q(membership__home_branch_id__in=branch_ids)
        )
    out = []
    for target in rows:
        out.append(
            {
                "id": target.pk,
                "month": target.month.isoformat(),
                "scope": "person"
                if target.membership_id
                else ("branch" if target.branch_id else "company"),
                "branch": {"id": target.branch_id, "name": target.branch.name}
                if target.branch_id
                else None,
                "member": person(target.membership),
                **_target_pace(target, company, today_day, branch_ids=branch_ids),
            }
        )
    order = {"company": 0, "branch": 1, "person": 2}
    out.sort(key=lambda row: (order[row["scope"]], -Decimal(row["amount"])))
    return out


def target_series(company, month: date, *, branch_ids: list[int] | None) -> list[dict]:
    """Cumulative net by day of the month (for the pacing chart)."""
    days = _month_days(month)
    end = month.replace(day=days)
    by_day: dict[date, Decimal] = defaultdict(lambda: ZERO)
    for row in daily_rows(company, month, end, branch_ids=branch_ids):
        by_day[row.day] += row.net
    running, out = ZERO, []
    for index in range(days):
        day = month + timedelta(days=index)
        running += by_day[day]
        out.append({"date": day.isoformat(), "net": m(by_day[day]), "cumulative": m(running)})
    return out


# Registry providers --------------------------------------------------------------------------


def branch_facts(company, day: date, now: datetime, branch_ids: list[int]) -> dict[int, dict]:
    """Branch cards (`contracts.SalesFacts`)."""
    if not branch_ids:
        return {}
    business = business_day(company, now)
    sales = _today_net(company, branch_ids, business)
    cash_rows = cash_by_branch(company, branch_ids)
    first: dict[int, CashShift] = {}
    open_tills: dict[int, int] = defaultdict(int)
    for shift in (
        CashShift.objects.filter(company=company, branch_id__in=branch_ids, business_day=business)
        .select_related("cashier")
        .order_by("opened_at")
    ):
        first.setdefault(shift.branch_id, shift)
        if shift.status == Status.OPEN:
            open_tills[shift.branch_id] += 1
    out: dict[int, dict] = {}
    for branch_id in branch_ids:
        shift = first.get(branch_id)
        facts: contracts.SalesFacts = {
            "opened_at": local(company, shift.opened_at).isoformat() if shift else None,
            "opened_by": person(shift.cashier) if shift else None,
            "open_tills": open_tills[branch_id],
            "net": m(sales[branch_id]["net"]),
            "cash_in_branch": m(cash_rows[branch_id]["total"])
            if branch_id in cash_rows
            else m(ZERO),
        }
        out[branch_id] = facts
    return out


def brief_section(company, day: date, now: datetime, branch_ids: list[int] | None) -> dict | None:
    """Sales for briefings and `/today`: the day so far against the same weekday last week."""
    settings = get_settings(company)
    sales = _today_net(company, branch_ids, day)
    week_ago = _today_net(company, branch_ids, day - timedelta(days=7))
    net = sum((row["net"] for row in sales.values()), ZERO)
    previous = sum((row["net"] for row in week_ago.values()), ZERO)
    receipts = sum(row["receipts"] for row in sales.values())
    open_count = restrict(
        CashShift.objects.filter(company=company, status=Status.OPEN), branch_ids
    ).count()
    closed = list(_closed_shifts(company, day, day, branch_ids).select_related("cashier", "branch"))
    if not net and not open_count and not closed:
        return None
    differences = [
        {"shift": shift.code, "cashier": str(shift.cashier), "difference": m(shift.difference)}
        for shift in closed
        if shift.difference is not None and abs(shift.difference) > settings.cash_tolerance
    ]
    transit = restrict(
        CashMovement.objects.filter(cash.in_transit_filter(), company=company), branch_ids
    )
    names = dict(
        restrict(Branch.objects.for_company(company), branch_ids, field="id").values_list(
            "pk", "name"
        )
    )
    lines = [
        _("Sales %(net)s (%(change)s vs last week)")
        % {"net": msg.money(net), "change": _percent(net, previous)},
    ]
    if differences:
        lines.append(_("%(count)s cash differences above tolerance") % {"count": len(differences)})
    if open_count:
        lines.append(_("%(count)s tills open") % {"count": open_count})
    return {
        "net": m(net),
        "prev_net": m(previous),
        "receipts": receipts,
        "avg_check": m(avg(net, receipts)),
        "open_shifts": open_count,
        "closed_shifts": len(closed),
        "difference_total": m(sum((s.difference or ZERO for s in closed), ZERO)),
        "differences": differences,
        "pending_handovers": transit.count(),
        "in_transit": m(transit.aggregate(t=Sum("amount"))["t"] or ZERO),
        "branches": [
            {"id": branch_id, "name": names.get(branch_id, ""), "net": m(row["net"])}
            for branch_id, row in sorted(sales.items(), key=lambda kv: -kv[1]["net"])
        ],
        "lines": lines,
    }


def _percent(current: Decimal, previous: Decimal) -> str:
    if not previous:
        return "—"
    return f"{(current - previous) / previous * 100:+.0f}%"


def company_facts(company, range, member: Membership) -> dict:
    """Portfolio cards (`contracts.SalesCompanyFacts`): net in the range and before it."""
    branch_ids = scope.branch_ids(member)
    net = totals(company, range.start, range.end, branch_ids=branch_ids).net
    if range.compare_start is not None:
        previous = totals(
            company, range.compare_start, range.compare_end, branch_ids=branch_ids
        ).net
    else:
        span = range.end - range.start + timedelta(days=1)
        previous = totals(company, range.start - span, range.end - span, branch_ids=branch_ids).net
    return {"net": m(net), "prev_net": m(previous)}


def search(member: Membership, q: str, limit: int) -> list[SearchHit]:
    q = (q or "").strip()
    if len(q) < 2:
        return []
    rows = shifts(member.company, {"q": q}, limit, branch_ids=scope.branch_ids(member))
    return [
        SearchHit(
            type="sales.shift",
            id=shift.pk,
            title=f"{shift.code} · {shift.cashier}",
            subtitle=(
                f"{shift.branch.name} · {shift.business_day:%d.%m.%Y} · {msg.money(shift.net)}"
            ),
            url=f"/c/{member.company_id}/sales/shifts?shift={shift.pk}",
        )
        for shift in rows
    ]


def stream(member: Membership, since: datetime | None, limit: int) -> list[StreamItem]:
    rows = with_net(
        restrict(
            CashShift.objects.for_company(member.company).filter(
                status__in=CLOSED_STATUSES, closed_at__isnull=False
            ),
            scope.branch_ids(member),
        )
    ).select_related("cashier", "branch")
    if since is not None:
        rows = rows.filter(closed_at__gt=since)
    return [
        StreamItem(
            at=shift.closed_at,
            kind="sales.shift_closed",
            actor={"id": shift.cashier_id, "name": str(shift.cashier)},
            title=_("Closed %(shift)s at %(branch)s · %(net)s")
            % {"shift": shift.code, "branch": shift.branch.name, "net": msg.money(shift.net)},
            url=f"/c/{member.company_id}/sales/shifts?shift={shift.pk}",
        )
        for shift in rows.order_by("-closed_at")[:limit]
    ]


def verify_count(member: Membership) -> int:
    return to_verify_count(member)


def verify_items(member: Membership, limit: int) -> list[QueueItem]:
    rows = (
        with_net(
            restrict(
                CashShift.objects.for_company(member.company).filter(status=Status.CLOSED),
                scope.branch_ids(member),
            )
        )
        .select_related("cashier", "branch")
        .order_by("closed_at")[:limit]
    )
    items = []
    for shift in rows:
        own = shift.cashier_id == member.pk and not (member.role and member.role.is_owner)
        difference = (
            _("no count")
            if shift.difference is None
            else _("difference %(d)s") % {"d": msg.signed(shift.difference)}
        )
        items.append(
            QueueItem(
                kind="sales.verify",
                id=shift.pk,
                title=f"{shift.code} · {shift.cashier}",
                subtitle=f"{shift.branch.name} · {msg.money(shift.net)} · {difference}",
                created_at=shift.closed_at,
                url=f"/c/{member.company_id}/sales/shifts?shift={shift.pk}",
                actions=()
                if own
                else (
                    QueueAction(
                        "verify", _("Verify"), "primary", "POST", f"sales/shifts/{shift.pk}/verify/"
                    ),
                    QueueAction(
                        "dispute",
                        _("Dispute"),
                        "danger",
                        "POST",
                        f"sales/shifts/{shift.pk}/dispute/",
                        needs_reason=True,
                    ),
                ),
            )
        )
    return items


def _my_handovers(member: Membership):
    return CashMovement.objects.filter(
        cash.in_transit_filter(), company=member.company, receiver=member
    )


def handover_count(member: Membership) -> int:
    return _my_handovers(member).count()


def handover_items(member: Membership, limit: int) -> list[QueueItem]:
    rows = (
        _my_handovers(member)
        .select_related("created_by", "branch", "register")
        .order_by("created_at")[:limit]
    )
    return [
        QueueItem(
            kind="sales.handover",
            id=movement.pk,
            title=_("%(person)s handed you %(amount)s")
            % {
                "person": movement.created_by,
                "amount": msg.money(movement.amount, movement.currency),
            },
            subtitle=f"{movement.branch.name} · {movement.register.name}"
            + (f" · {movement.reason}" if movement.reason else ""),
            created_at=movement.created_at,
            url=f"/c/{member.company_id}/sales/cash",
            actions=(
                QueueAction(
                    "received",
                    _("Received"),
                    "primary",
                    "POST",
                    f"sales/handovers/{movement.pk}/confirm/",
                ),
                QueueAction(
                    "not_received",
                    _("Not received"),
                    "danger",
                    "POST",
                    f"sales/handovers/{movement.pk}/decline/",
                    needs_reason=True,
                ),
            ),
        )
        for movement in rows
    ]


def pending_handovers_for(member: Membership):
    """Handovers waiting for `member` to confirm (the mini app's "Received?" card)."""
    return (
        _my_handovers(member)
        .select_related("created_by", "branch", "register")
        .order_by("created_at")
    )


def offboard_preview(membership: Membership) -> OffboardStep:
    """Sales' step in the offboarding wizard: an open till blocks; handovers waiting on the
    person (either way) are listed, and the ones they must still answer block too."""
    lines, blockers = [], []
    shift = (
        CashShift.objects.filter(cashier=membership, status=Status.OPEN)
        .select_related("branch")
        .first()
    )
    if shift is not None:
        blockers.append(
            _("Open till %(shift)s at %(branch)s must be closed first.")
            % {"shift": shift.code, "branch": shift.branch.name}
        )
    waiting = CashMovement.objects.filter(cash.in_transit_filter(), receiver=membership)
    if waiting.exists():
        total = waiting.aggregate(t=Sum("amount"))["t"]
        blockers.append(
            _("%(count)s cash handovers (%(amount)s) are waiting for them to confirm or decline.")
            % {"count": waiting.count(), "amount": msg.money(total)}
        )
    sent = CashMovement.objects.filter(cash.in_transit_filter(), created_by=membership)
    if sent.exists():
        total = sent.aggregate(t=Sum("amount"))["t"]
        lines.append(
            _("%(count)s handovers they made (%(amount)s) aren't confirmed by the receiver yet.")
            % {"count": sent.count(), "amount": msg.money(total)}
        )
    closed = CashShift.objects.filter(cashier=membership).exclude(status=Status.OPEN)
    unverified = closed.filter(status=Status.CLOSED).count()
    if closed.exists():
        lines.append(
            _("%(count)s shifts on record, %(unverified)s not verified yet.")
            % {"count": closed.count(), "unverified": unverified}
        )
    return OffboardStep(lines=lines, blockers=blockers, fields=[], defaults={})


def setup_done(company) -> bool:
    return (
        Register.objects.filter(company=company, is_active=True).exists()
        and CashShift.objects.filter(company=company).exists()
    )


# Exports ----------------------------------------------------------------------------------


def export_daily(member: Membership, params: dict):
    company = member.company
    end = _param_day(params.get("to")) or business_day(company)
    start = _param_day(params.get("from")) or end.replace(day=1)
    for row in daily_rows(company, start, end, branch_ids=scope.branch_ids(member)):
        cash_net = _row_totals(row).cash_net
        yield {
            "day": row.day,
            "branch": row.branch.name,
            "sales": row.sales,
            "refunds": row.refunds,
            "net": row.net,
            "cash": cash_net,
            "non_cash": row.net - cash_net,
            "receipts": row.receipts,
            "avg_check": row.avg_check,
            "shifts": row.shifts,
            "cash_difference": row.cash_difference,
        }


def export_shifts(member: Membership, params: dict):
    company = member.company
    filters = {key: params.get(key) for key in ("from", "to", "q") if params.get(key)}
    if params.get("branch"):
        filters["branch"] = [int(x) for x in str(params["branch"]).split(",") if x.isdigit()]
    if params.get("status"):
        filters["status"] = [s for s in str(params["status"]).split(",") if s in Status.values]
    for key in ("from", "to"):
        if key in filters:
            filters[key] = _param_day(filters[key])
    rows = shifts(company, filters, None, branch_ids=scope.branch_ids(member))
    for shift in rows.iterator(chunk_size=500):
        yield {
            "code": shift.code,
            "business_day": shift.business_day,
            "branch": shift.branch.name,
            "register": shift.register.name,
            "cashier": str(shift.cashier),
            "status": str(shift.get_status_display()),
            "opened_at": shift.opened_at,
            "closed_at": shift.closed_at,
            "opening_float": shift.opening_float,
            "net": shift.net,
            "receipts": shift.receipts,
            "expected_cash": shift.expected_cash,
            "counted_cash": shift.final_count,
            "difference": shift.difference,
            "z_number": shift.z_number,
            "verified_by": str(shift.verified_by) if shift.verified_by_id else "",
        }


def _param_day(value) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


__all__ = [
    "branch_facts",
    "brief_section",
    "cash_positions",
    "cashier_scorecard",
    "company_facts",
    "shifts",
    "summary",
    "targets",
    "today",
]
