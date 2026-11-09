"""Attendance reports (docs/DAVOMAT.md §1.6): per person, department and branch over a period,
the daily trend and the punctuality ranking, from the shifts and the check-in records.

One pass classifies each person's each day once (a `DayFact`); every figure is a sum over those
facts, so the people table, the department and branch tables, the trend, the ranking and the
totals always agree. The rules, as they apply to one person on one day:

- Only days up to today count: the future hasn't happened. Today counts once the person came in
  or is on leave, so nobody is absent before the day is over.
- Expected work is a published shift (planned, or turned into leave) that day, as on the board
  and the timesheet: no shift, no absence. Never on a holiday or while suspended.
- Present: a check-in that day (still in, checked out or closed automatically), expected or not.
  Leave: an expected day under approved time off or a leave shift. Excused: an expected day a
  manager excused. Absent: any other expected day.
- A day belongs to the branch of its shift, else of its check-in, else the person's home
  branch. Branch scope (§2.6) and the branch filter keep the days of those branches; a person
  appears where they have days.
- Lateness, early leave, worked time and overtime come from the records (`rules.compute`);
  someone still in has worked until now. Rejected overtime doesn't count. Punctuality is the
  share of check-ins for a shift that were on time.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, fields
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q
from django.utils import timezone

from apps.attendance import clock, queries, rules
from apps.attendance.models import AttendanceRecord, WorkShift
from apps.companies.models import Branch, Company
from apps.members import scope
from apps.members.departments import Org
from apps.members.models import Department, Membership

PRESENT, ABSENT, LEAVE, EXCUSED = "present", "absent", "leave", "excused"
KINDS = ("summary", "departments", "branches", "trend", "punctuality")


@dataclass
class DayFact:
    """One person's one day."""

    member_id: int
    day: date
    branch_id: int | None
    status: str
    expected: bool
    worked_minutes: int = 0
    late_count: int = 0
    late_minutes: int = 0
    early_leave_count: int = 0
    early_leave_minutes: int = 0
    overtime_minutes: int = 0
    # Check-ins for a shift (where lateness is measured), and those on time.
    arrivals: int = 0
    on_time: int = 0


@dataclass
class Figures:
    """The sums every report row shows."""

    days_scheduled: int = 0
    days_present: int = 0
    days_absent: int = 0
    days_leave: int = 0
    days_excused: int = 0
    worked_minutes: int = 0
    late_count: int = 0
    late_minutes: int = 0
    early_leave_count: int = 0
    early_leave_minutes: int = 0
    overtime_minutes: int = 0
    arrivals: int = 0
    on_time: int = 0
    # Expected days the person came on (the attendance rate's numerator).
    expected_present: int = 0
    members: set[int] = field(default_factory=set)

    def add(self, fact: DayFact) -> None:
        self.members.add(fact.member_id)
        self.days_scheduled += fact.expected
        self.days_present += fact.status == PRESENT
        self.days_absent += fact.status == ABSENT
        self.days_leave += fact.status == LEAVE
        self.days_excused += fact.status == EXCUSED
        self.expected_present += fact.expected and fact.status == PRESENT
        for name in (
            "worked_minutes",
            "late_count",
            "late_minutes",
            "early_leave_count",
            "early_leave_minutes",
            "overtime_minutes",
            "arrivals",
            "on_time",
        ):
            setattr(self, name, getattr(self, name) + getattr(fact, name))

    @property
    def punctuality_percent(self) -> float | None:
        return percent(self.on_time, self.arrivals)

    @property
    def attendance_percent(self) -> float | None:
        """Expected days the person came, of the expected days not on leave or excused."""
        due = self.days_scheduled - self.days_leave - self.days_excused
        return percent(self.expected_present, due)

    def as_dict(self) -> dict:
        data = {
            item.name: getattr(self, item.name)
            for item in fields(self)
            if item.name not in ("members", "expected_present")
        }
        data["punctuality_percent"] = self.punctuality_percent
        data["attendance_percent"] = self.attendance_percent
        return data


def percent(part: int, whole: int) -> float | None:
    if not whole:
        return None
    value = Decimal(part * 100) / Decimal(whole)
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class Period:
    start: date
    end: date
    # The last day counted: the end, or today when the period runs on past it.
    until: date
    today: date

    def as_dict(self) -> dict:
        return {
            "range": {"from": self.start.isoformat(), "to": self.end.isoformat()},
            "counted_until": self.until.isoformat() if self.until >= self.start else None,
            "today": self.today.isoformat(),
        }


@dataclass
class Report:
    company: Company
    period: Period
    people: dict[int, Membership]
    facts: list[DayFact]
    branches: dict[int, Branch]

    def figures(self, facts: Iterable[DayFact] | None = None) -> Figures:
        total = Figures()
        for fact in self.facts if facts is None else facts:
            total.add(fact)
        return total

    def grouped(self, key: Callable[[DayFact], object]) -> dict[object, Figures]:
        groups: dict[object, Figures] = defaultdict(Figures)
        for fact in self.facts:
            groups[key(fact)].add(fact)
        return groups


def build(
    company: Company,
    start: date,
    end: date,
    *,
    branch_ids: list[int] | None,
    department_ids: list[int] | None = None,
    member_ids: list[int] | None = None,
    now: datetime | None = None,
) -> Report:
    """Every person's every counted day from `start` to `end` in `branch_ids` (the caller's
    scope narrowed by the branch filter; None: every branch). `department_ids` keeps people in
    those departments (and the ones below them); `member_ids` keeps those people."""
    now = now or timezone.now()
    today = clock.today(company, now)
    period = Period(start, end, min(end, today), today)
    branches = {
        branch.pk: branch for branch in Branch.objects.filter(company=company).order_by("pk")
    }
    if period.until < start:
        return Report(company, period, {}, [], branches)
    until = period.until
    people = _people(company, start, until, branch_ids, department_ids, member_ids)
    ids = list(people)

    shifts: dict[tuple[int, date], list[WorkShift]] = defaultdict(list)
    for shift in (
        WorkShift.objects.live()
        .filter(company=company, date__range=(start, until), membership_id__in=ids)
        .filter(status__in=(WorkShift.Status.PLANNED, WorkShift.Status.LEAVE))
        .order_by("starts_at", "pk")
    ):
        shifts[(shift.membership_id, shift.date)].append(shift)
    records: dict[tuple[int, date], list[AttendanceRecord]] = defaultdict(list)
    for record in (
        AttendanceRecord.objects.filter(
            company=company, date__range=(start, until), membership_id__in=ids
        )
        .select_related("shift")
        .order_by("check_in_at", "pk")
    ):
        records[(record.membership_id, record.date)].append(record)
    away = queries.leave_days(company, start, until, ids)
    days_off = set(queries.holidays(company, start, until))

    facts = []
    for member_id, member in people.items():
        for day in clock.days(start, until):
            fact = _fact(
                member,
                day,
                today,
                now,
                shifts.get((member_id, day), []),
                records.get((member_id, day), []),
                day in away.get(member_id, {}),
                day in days_off,
            )
            if fact is not None and scope.allows(branch_ids, fact.branch_id):
                facts.append(fact)
    present = {fact.member_id for fact in facts}
    return Report(
        company,
        period,
        {pk: member for pk, member in people.items() if pk in present},
        facts,
        branches,
    )


def _people(company, start, until, branch_ids, department_ids, member_ids):
    """Current staff of those branches, and anyone with a shift or a check-in there in the
    period (people who left keep their days)."""
    current = Membership.objects.for_company(company).filter(status__in=queries.STAFF_STATUSES)
    if branch_ids is not None:
        current = current.filter(Q(branches__in=branch_ids) | Q(home_branch_id__in=branch_ids))
    ids = set(current.values_list("pk", flat=True))
    for rows in (
        WorkShift.objects.live().filter(company=company, date__range=(start, until)),
        AttendanceRecord.objects.filter(company=company, date__range=(start, until)),
    ):
        rows = scope.restrict(rows.exclude(membership__isnull=True), branch_ids)
        ids |= set(rows.values_list("membership_id", flat=True))
    people = Membership.objects.filter(company=company, pk__in=ids).select_related(
        "user", "position", "department", "home_branch"
    )
    if department_ids is not None:
        people = people.filter(department_id__in=department_ids)
    if member_ids is not None:
        people = people.filter(pk__in=member_ids)
    return {member.pk: member for member in sorted(people, key=lambda m: (name(m).lower(), m.pk))}


def _fact(member, day, today, now, shifts, records, on_leave, holiday) -> DayFact | None:
    attended = [record for record in records if record.attended]
    planned = [shift for shift in shifts if shift.status == WorkShift.Status.PLANNED]
    suspended = queries.is_suspended_on(member, day)
    expected = bool(shifts) and not holiday and not suspended
    if attended:
        status = PRESENT
    elif expected and (on_leave or not planned):
        status = LEAVE  # approved time off, or only leave shifts that day
    elif expected and any(r.status == AttendanceRecord.Status.EXCUSED for r in records):
        status = EXCUSED
    elif expected and day < today:
        status = ABSENT
    else:
        return None  # nothing expected and nothing happened, or today not over yet
    branch_id = (
        (shifts[0].branch_id if shifts else None)
        or (attended[0].branch_id if attended else None)
        or member.home_branch_id
    )
    fact = DayFact(member.pk, day, branch_id, status, expected)
    for record in attended:
        fact.worked_minutes += _worked(record, now)
        if record.shift_id:
            fact.arrivals += 1
            fact.on_time += not record.is_late
        if record.is_late:
            fact.late_count += 1
            fact.late_minutes += record.late_minutes
        if record.early_leave_minutes:
            fact.early_leave_count += 1
            fact.early_leave_minutes += record.early_leave_minutes
        if record.overtime_status != AttendanceRecord.Overtime.REJECTED:
            fact.overtime_minutes += record.overtime_minutes
    return fact


def _worked(record: AttendanceRecord, now: datetime) -> int:
    """Worked minutes; someone still in has worked from their check-in until now."""
    if record.status != AttendanceRecord.Status.OPEN or record.check_in_at is None:
        return record.worked_minutes
    span = max(0, clock.minutes_between(record.check_in_at, now))
    pause = (
        record.shift.break_minutes if record.shift_id and span > rules.BREAK_AFTER_MINUTES else 0
    )
    return max(0, span - pause)


# Who and where ----------------------------------------------------------------------------


def name(member: Membership) -> str:
    user = member.user
    return member.full_name or user.get_full_name() or user.username


def employee(member: Membership) -> dict:
    """A person as every report row shows them."""
    user = member.user
    return {
        "id": member.pk,
        "name": name(member),
        "photo_url": user.photo.url if user.photo else None,
        "position": {"id": member.position_id, "name": member.position.name}
        if member.position_id
        else None,
        "department": {"id": member.department_id, "name": member.department.name}
        if member.department_id
        else None,
        "branch": {"id": member.home_branch_id, "name": member.home_branch.name}
        if member.home_branch_id
        else None,
    }


def departments_below(company: Company, picked: list[int]) -> list[int] | None:
    """The picked departments and every department below them (None: no filter)."""
    if not picked:
        return None
    return sorted(Org(company.pk).below(picked))


# The five reports -------------------------------------------------------------------------


def summary(report: Report) -> dict:
    """A row per person, with the totals."""
    per_person = report.grouped(lambda fact: fact.member_id)
    rows = [
        {"employee": employee(member), **per_person[pk].as_dict()}
        for pk, member in report.people.items()
    ]
    return {**report.period.as_dict(), "rows": rows, "totals": _totals(report)}


def departments(report: Report) -> dict:
    """A row per department (people without one last), with the totals."""
    groups = report.grouped(lambda fact: report.people[fact.member_id].department_id)
    known = Department.objects.filter(company=report.company, pk__in=[k for k in groups if k])
    order = {pk: index for index, pk in enumerate(Org(report.company.pk).in_tree_order())}
    rows = []
    for department in sorted(known, key=lambda d: (order.get(d.pk, len(order)), d.name)):
        ref = {"id": department.pk, "name": department.name}
        rows.append(_group_row("department", ref, groups[department.pk]))
    if None in groups:
        rows.append(_group_row("department", None, groups[None]))
    return {**report.period.as_dict(), "rows": rows, "totals": _totals(report)}


def branches(report: Report) -> dict:
    """A row per branch where the days happened (days without a branch last)."""
    groups = report.grouped(lambda fact: fact.branch_id)
    known = sorted(
        (report.branches[pk] for pk in groups if pk in report.branches),
        key=lambda branch: (branch.order, branch.name, branch.pk),
    )
    rows = [
        _group_row(
            "branch",
            {"id": branch.pk, "name": branch.name, "code": branch.code},
            groups[branch.pk],
        )
        for branch in known
    ]
    if None in groups:
        rows.append(_group_row("branch", None, groups[None]))
    return {**report.period.as_dict(), "rows": rows, "totals": _totals(report)}


def trend(report: Report) -> dict:
    """Per day: people expected, present, late, absent, on leave and excused."""
    per_day: dict[date, list[DayFact]] = defaultdict(list)
    for fact in report.facts:
        per_day[fact.day].append(fact)
    days = []
    if report.period.until >= report.period.start:
        for day in clock.days(report.period.start, report.period.until):
            facts = per_day.get(day, [])
            figures = report.figures(facts)
            days.append(
                {
                    "date": day.isoformat(),
                    "scheduled": figures.days_scheduled,
                    "present": figures.days_present,
                    "late": sum(1 for fact in facts if fact.late_count),
                    "absent": figures.days_absent,
                    "leave": figures.days_leave,
                    "excused": figures.days_excused,
                    "worked_minutes": figures.worked_minutes,
                    "punctuality_percent": figures.punctuality_percent,
                }
            )
    return {**report.period.as_dict(), "days": days, "totals": _totals(report)}


def punctuality(report: Report) -> dict:
    """People who checked in for a shift, the most punctual first: punctuality, then fewer late
    minutes, then more arrivals. Equal punctuality and late minutes share a rank."""
    per_person = report.grouped(lambda fact: fact.member_id)
    ranked = sorted(
        (
            (member, per_person[pk])
            for pk, member in report.people.items()
            if per_person[pk].arrivals
        ),
        key=lambda item: (
            -(item[1].punctuality_percent or 0),
            item[1].late_minutes,
            -item[1].arrivals,
            name(item[0]).lower(),
        ),
    )
    rows = []
    previous = None
    for index, (member, figures) in enumerate(ranked, start=1):
        standing = (figures.punctuality_percent, figures.late_minutes)
        rank = rows[-1]["rank"] if standing == previous else index
        previous = standing
        rows.append(
            {
                "rank": rank,
                "employee": employee(member),
                "punctuality_percent": figures.punctuality_percent,
                "arrivals": figures.arrivals,
                "on_time": figures.on_time,
                "late_count": figures.late_count,
                "late_minutes": figures.late_minutes,
                "average_late_minutes": round(figures.late_minutes / figures.late_count)
                if figures.late_count
                else 0,
                "days_present": figures.days_present,
            }
        )
    totals = report.figures()
    return {
        **report.period.as_dict(),
        "average": totals.punctuality_percent,
        "rows": rows,
        "totals": _totals(report),
    }


def _group_row(name: str, ref: dict | None, figures: Figures) -> dict:
    return {name: ref, "people": len(figures.members), **figures.as_dict()}


def _totals(report: Report) -> dict:
    figures = report.figures()
    return {"people": len(figures.members), **figures.as_dict()}


BUILDERS: dict[str, Callable[[Report], dict]] = {
    "summary": summary,
    "departments": departments,
    "branches": branches,
    "trend": trend,
    "punctuality": punctuality,
}


def person(member: Membership, start: date, end: date, *, now: datetime | None = None) -> Figures:
    """One person's figures over a period, wherever they worked (their own `/me`)."""
    report = build(member.company, start, end, branch_ids=None, member_ids=[member.pk], now=now)
    return report.figures()
