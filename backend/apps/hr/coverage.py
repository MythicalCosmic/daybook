"""The pharmacist coverage rule: a qualified pharmacist whenever a pharmacy is open
(docs/PLAN-OWNER.md §14.4 row 5, §14.9).

Contracts other packages call (fixed signatures):

    planned_gaps(company, start, end, *, branch_ids, drafts=False, exclude_member_ids=())
        -> list[Gap]
    live(company, now) -> list[LiveGap]
    unqualified_sellers(company, day, *, branch_ids) -> list[dict]

The rule runs only while `apps.hr.conf.coverage_settings` says so (HR on, the rule on, the
pharmacist positions chosen) and only at pharmacy branches (`Branch.kind`), so a warehouse
never shows a gap. It reads attendance (`shifts_between`, `records_between`, `holidays`) and
sales (`shifts`) through their query contracts and never writes their rows.

- Open hours: `opens_at` to `closes_at` on `open_weekdays`, company holidays closed (an evening
  past midnight belongs to the day it opened); all day every day, holidays included, at a
  branch open around the clock (`open_24h`). A branch without an opening time has no hours to
  check.
- Planned: who has a planned shift there. Shifts on leave, open shifts without a person and
  cancelled ones never count; drafts only when asked (the roster). Each shift counts for its
  person's qualification on its own `date`, the night after midnight included.
- Live: who has an open attendance record there now. A branch where nobody has checked in for
  a week is left out: its live coverage isn't known.
"""

from __future__ import annotations

import itertools
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

from apps.companies.models import Branch, BranchKind
from apps.hr import conf
from apps.hr.queries import Qualifier, Verdict
from apps.members.models import Membership

# Live coverage looks back this far for the last qualified check-out, and leaves out a
# branch where nobody at all checked in for `UNTRACKED_DAYS`.
LOOKBACK = timedelta(days=2)
UNTRACKED_DAYS = 7
# Coverage pages and the AI read at most this many days at once.
MAX_DAYS = 62


@dataclass(frozen=True)
class Gap:
    """Part of a branch's open hours with fewer than `need` qualified people planned."""

    branch_id: int
    start: datetime
    end: datetime
    have: int
    need: int

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


@dataclass(frozen=True)
class LiveGap:
    """A branch open now with fewer than `need` qualified people checked in, since `since`."""

    branch_id: int
    since: datetime
    have: int
    need: int
    present: tuple[int, ...] = ()


@dataclass(frozen=True)
class Cover:
    """One shift of someone in a pharmacist position at the branch, and whether it counts."""

    shift_id: int
    member: Membership
    date: date
    start: datetime
    end: datetime
    published: bool
    verdict: Verdict


@dataclass
class DayPlan:
    """One branch on one day: its open hours (or why it is closed), the pharmacists planned
    there and the gaps."""

    date: date
    opens: datetime | None
    closes: datetime | None
    closed: str | None  # weekday, holiday or no_hours while closed; None when open
    covers: list[Cover] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)


@dataclass
class BranchPlan:
    branch: Branch
    days: list[DayPlan] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)  # merged across midnight
    shifts: int = 0  # every planned shift at the branch in the period (anyone's)


@dataclass
class Plan:
    """The coverage of a period: `state` is ok, or why nothing was checked (off: the rule is
    switched off or HR is; setup: no pharmacist positions chosen; no_roster: attendance off)."""

    state: str
    start: date
    end: date
    need: int
    branches: list[BranchPlan] = field(default_factory=list)

    @property
    def gaps(self) -> list[Gap]:
        return [gap for branch in self.branches for gap in branch.gaps]


OK, OFF, SETUP, NO_ROSTER = "ok", "off", "setup", "no_roster"
STATES = (OK, OFF, SETUP, NO_ROSTER)


def state(company) -> str:
    """Whether the rule runs for `company`, and if not, why (one of STATES)."""
    if not company.has_feature("hr"):
        return OFF
    settings = conf.get_settings(company)
    if not settings.coverage_enabled:
        return OFF
    if not conf.pharmacist_position_ids(settings):
        return SETUP
    if not company.has_feature("attendance"):
        return NO_ROSTER
    return OK


def pharmacies(company, *, branch_ids: list[int] | None) -> list[Branch]:
    """The company's active pharmacy branches in scope (warehouses and offices never count)."""
    rows = Branch.objects.filter(company=company, is_active=True, kind=BranchKind.PHARMACY)
    if branch_ids is not None:
        rows = rows.filter(pk__in=list(branch_ids))
    return list(rows.select_related("manager").order_by("order", "name", "pk"))


def open_hours(
    branch: Branch, day: date, tz: ZoneInfo, holidays
) -> tuple[datetime, datetime] | str:
    """(opens, closes) of `branch` on `day`, or why it is closed: weekday, holiday or no_hours."""
    if branch.open_24h:
        return _at(day, time(0), tz), _at(day + timedelta(days=1), time(0), tz)
    if day.weekday() not in (branch.open_weekdays or []):
        return "weekday"
    if day in holidays:
        return "holiday"
    if branch.opens_at is None:
        return "no_hours"
    opens = _at(day, branch.opens_at, tz)
    if branch.closes_at is None:
        return opens, _at(day + timedelta(days=1), time(0), tz)
    if branch.closes_at > branch.opens_at:
        return opens, _at(day, branch.closes_at, tz)
    return opens, _at(day + timedelta(days=1), branch.closes_at, tz)  # open past midnight


def plan(
    company,
    start: date,
    end: date,
    *,
    branch_ids: list[int] | None,
    drafts: bool = False,
    exclude_member_ids=(),
) -> Plan:
    """The coverage of every pharmacy branch in scope from `start` to `end` (company-local days)."""
    from apps.attendance import queries as attendance
    from apps.attendance.models import WorkShift

    found = state(company)
    settings = conf.get_settings(company)
    result = Plan(found, start, end, settings.coverage_min)
    if found != OK or end < start:
        return result
    tz = ZoneInfo(company.timezone)
    branches = pharmacies(company, branch_ids=branch_ids)
    if not branches:
        return result
    holidays = set(attendance.holidays(company, start, end))
    excluded = {int(pk) for pk in exclude_member_ids or ()}
    # A night shift dated the day before covers this morning; an early one dated the next day
    # can open a branch that is open past midnight.
    shifts = [
        shift
        for shift in attendance.shifts_between(
            company,
            start - timedelta(days=1),
            end + timedelta(days=1),
            branch_ids=[branch.pk for branch in branches],
            drafts=drafts,
        )
        if shift.status == WorkShift.Status.PLANNED
        and shift.membership_id is not None
        and shift.membership_id not in excluded
    ]
    qualifier = Qualifier(company, {shift.membership_id for shift in shifts}, settings=settings)
    by_branch: dict[int, list] = defaultdict(list)
    for shift in shifts:
        by_branch[shift.branch_id].append(shift)
    need = settings.coverage_min
    for branch in branches:
        here = by_branch.get(branch.pk, [])
        counted = [
            (shift.starts_at, shift.ends_at, shift.membership_id)
            for shift in here
            if qualifier.counts(shift.membership_id, shift.date)
        ]
        row = BranchPlan(branch, shifts=sum(1 for shift in here if start <= shift.date <= end))
        day = start
        while day <= end:
            hours = open_hours(branch, day, tz, holidays)
            if isinstance(hours, str):
                today = DayPlan(day, None, None, hours)
            else:
                today = DayPlan(day, hours[0], hours[1], None)
                today.gaps = _gaps(branch.pk, hours[0], hours[1], counted, need)
            today.covers = [
                Cover(
                    shift.pk,
                    shift.membership,
                    shift.date,
                    shift.starts_at,
                    shift.ends_at,
                    shift.published_at is not None,
                    qualifier.verdict(shift.membership_id, shift.date),
                )
                for shift in here
                if shift.date == day and qualifier.is_pharmacist(shift.membership_id)
            ]
            row.days.append(today)
            day += timedelta(days=1)
        row.gaps = _merge([gap for today in row.days for gap in today.gaps])
        result.branches.append(row)
    return result


def planned_gaps(
    company,
    start: date,
    end: date,
    *,
    branch_ids: list[int] | None,
    drafts: bool = False,
    exclude_member_ids=(),
) -> list[Gap]:
    """The parts of the open hours of each pharmacy branch in scope, from `start` to `end`,
    when fewer than `coverage_min` qualified people have a planned shift there. Gaps that run
    on past midnight (a 24-hour branch's night) come as one. `exclude_member_ids` leaves
    people out, so leave can show the gap it would open (§14.15)."""
    return plan(
        company,
        start,
        end,
        branch_ids=branch_ids,
        drafts=drafts,
        exclude_member_ids=exclude_member_ids,
    ).gaps


def live(company, now: datetime | None = None) -> list[LiveGap]:
    """Pharmacy branches open now where fewer than `coverage_min` qualified people have an
    open attendance record; `since` is when that began (the last qualified check-out, or the
    opening)."""
    from apps.attendance import queries as attendance
    from apps.attendance.models import AttendanceRecord

    if state(company) != OK:
        return []
    now = now or timezone.now()
    settings = conf.get_settings(company)
    tz = ZoneInfo(company.timezone)
    local = timezone.localtime(now, tz)
    today = local.date()
    branches = pharmacies(company, branch_ids=None)
    if not branches:
        return []
    holidays = set(attendance.holidays(company, today - timedelta(days=1), today))
    # Every branch's records (a system read): a record without a branch is its shift's.
    records = list(
        attendance.records_between(
            company, today - timedelta(days=UNTRACKED_DAYS), today, branch_ids=None
        ).filter(check_in_at__isnull=False, check_in_at__lte=now)
    )
    qualifier = Qualifier(company, {record.membership_id for record in records}, settings=settings)
    by_branch: dict[int, list] = defaultdict(list)
    for record in records:
        branch_id = record.branch_id or (record.shift.branch_id if record.shift_id else None)
        by_branch[branch_id].append(record)
    found = []
    for branch in branches:
        here = by_branch.get(branch.pk, [])
        if not here:
            continue  # nobody checks in here: its live coverage isn't known
        window = _open_window(branch, local, tz, holidays)
        if window is None:
            continue
        present = sorted(
            {
                record.membership_id
                for record in here
                if _there(record, now, AttendanceRecord.Status.OPEN)
                and qualifier.counts(record.membership_id, record.date)
            }
        )
        if len(present) >= settings.coverage_min:
            continue
        left = [
            record.check_out_at
            for record in here
            if record.check_out_at is not None
            and now - LOOKBACK <= record.check_out_at <= now
            and qualifier.counts(record.membership_id, record.date)
        ]
        opened = window if window is not True else None
        since = max([moment for moment in (opened, *left) if moment is not None], default=None)
        if since is None:  # around the clock and nobody qualified lately: since the day began
            since = _at(today, time(0), tz)
        found.append(LiveGap(branch.pk, since, len(present), settings.coverage_min, tuple(present)))
    return found


def unqualified_sellers(company, day: date, *, branch_ids: list[int] | None) -> list[dict]:
    """Open or `day`'s cash shifts at pharmacy branches in scope whose cashier doesn't count as a
    qualified pharmacist on the shift's business day. Empty while the rule doesn't run, sales
    is off, or `unqualified_seller_alert` is off (cashiers there only take payment)."""
    if state(company) not in (OK, NO_ROSTER) or not company.has_feature("sales"):
        return []
    settings = conf.get_settings(company)
    if not settings.unqualified_seller_alert:
        return []
    from apps.sales import queries as sales

    ids = [branch.pk for branch in pharmacies(company, branch_ids=branch_ids)]
    if not ids:
        return []
    rows = {
        shift.pk: shift
        for filters in (
            {"branch": ids, "status": ["open"]},
            {"branch": ids, "from": day, "to": day},
        )
        for shift in sales.shifts(company, filters, None, branch_ids=branch_ids)
    }
    qualifier = Qualifier(company, {shift.cashier_id for shift in rows.values()}, settings=settings)
    found = []
    for shift in sorted(rows.values(), key=lambda row: (row.opened_at, row.pk)):
        verdict = qualifier.verdict(shift.cashier_id, shift.business_day)
        if verdict.counts:
            continue
        found.append(
            {
                "shift_id": shift.pk,
                "branch_id": shift.branch_id,
                "branch": shift.branch.name,
                "cashier_id": shift.cashier_id,
                "cashier": str(shift.cashier),
                "business_day": shift.business_day,
                "opened_at": shift.opened_at,
                "status": shift.status,
                "reason": verdict.reason,
            }
        )
    return found


# Helpers --------------------------------------------------------------------------------------


def _at(day: date, clock: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, clock, tzinfo=tz)


def _there(record, now: datetime, open_status: str) -> bool:
    """Checked in at `now`: in before it, and out only after it (or still open)."""
    if record.check_out_at is not None:
        return record.check_out_at > now
    return record.status == open_status


def _open_window(branch: Branch, local: datetime, tz: ZoneInfo, holidays):
    """When the open period holding `local` began: its opening moment, True for a branch open
    around the clock (no opening), or None while closed."""
    if branch.open_24h:
        return True
    day = local.date()
    for opened_on in (day, day - timedelta(days=1)):
        hours = open_hours(branch, opened_on, tz, holidays)
        if not isinstance(hours, str) and hours[0] <= local < hours[1]:
            return hours[0]
    return None


def _gaps(branch_id: int, start: datetime, end: datetime, intervals, need: int) -> list[Gap]:
    """The parts of [start, end) with fewer than `need` people from `intervals` ((start, end,
    person) of qualified shifts), one Gap per stretch with the same count."""
    points = {start, end}
    for first, last, _person in intervals:
        if first < end and last > start:
            points.update((max(first, start), min(last, end)))
    edges = sorted(points)
    gaps: list[Gap] = []
    for first, last in itertools.pairwise(edges):
        have = len(
            {person for begin, finish, person in intervals if begin <= first and finish >= last}
        )
        if have >= need:
            continue
        if gaps and gaps[-1].end == first and gaps[-1].have == have:
            gaps[-1] = Gap(branch_id, gaps[-1].start, last, have, need)
        else:
            gaps.append(Gap(branch_id, first, last, have, need))
    return gaps


def _merge(gaps: list[Gap]) -> list[Gap]:
    """Gaps that touch (a night across midnight) as one."""
    merged: list[Gap] = []
    for gap in sorted(gaps, key=lambda item: item.start):
        last = merged[-1] if merged else None
        if last is not None and last.end == gap.start and last.have == gap.have:
            merged[-1] = Gap(gap.branch_id, last.start, gap.end, gap.have, gap.need)
        else:
            merged.append(gap)
    return merged
