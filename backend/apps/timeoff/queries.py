from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Q, QuerySet

from apps.companies.models import Company
from apps.members import scope
from apps.members.models import Membership
from apps.members.queries import branch_ref, person_ref
from apps.timeoff.models import Holiday, TimeOff

# What the calendar shows: decided leave and requests still waiting.
SHOWN = (TimeOff.Status.PENDING, TimeOff.Status.APPROVED)


@dataclass(frozen=True)
class LeaveDay:
    """One day of approved leave."""

    day: date
    time_off_id: int
    kind: str  # the leave type's kind: annual, sick, unpaid, day_off, study, maternity, other
    paid: bool
    pay_percent: int  # how much of a normal day's pay it earns, 0 to 100


@dataclass(frozen=True)
class LeaveSummary:
    """A member's approved leave inside a period, day by day (company holidays left out:
    they are never counted against leave)."""

    membership_id: int
    days: tuple[LeaveDay, ...]

    @property
    def paid_days(self) -> Decimal:
        return Decimal(sum(1 for day in self.days if day.paid))

    @property
    def unpaid_days(self) -> Decimal:
        return Decimal(sum(1 for day in self.days if not day.paid))

    def on(self, day: date) -> LeaveDay | None:
        return next((leave for leave in self.days if leave.day == day), None)


def leave_summary(
    company: Company, start: date, end: date, *, member_ids: Iterable[int] | None = None
) -> dict[int, LeaveSummary]:
    """Approved leave from `start` to `end` (inclusive) per membership id; members without any
    are left out. Payroll reads it to prorate pay.

    Until leave types exist (package L), every approved day is a paid "day off" at 100%.
    """
    rows = TimeOff.objects.filter(
        company=company, status=TimeOff.Status.APPROVED, first_day__lte=end, last_day__gte=start
    )
    if member_ids is not None:
        rows = rows.filter(membership_id__in=list(member_ids))
    holidays = set(
        Holiday.objects.filter(company=company, date__range=(start, end)).values_list(
            "date", flat=True
        )
    )
    days: dict[int, dict[date, LeaveDay]] = {}
    for time_off in rows.order_by("first_day", "pk"):
        day = max(time_off.first_day, start)
        while day <= min(time_off.last_day, end):
            if day not in holidays:
                days.setdefault(time_off.membership_id, {}).setdefault(
                    day, LeaveDay(day, time_off.pk, "day_off", True, 100)
                )
            day += timedelta(days=1)
    return {
        member_id: LeaveSummary(member_id, tuple(by_day[day] for day in sorted(by_day)))
        for member_id, by_day in days.items()
    }


def balance(membership: Membership, *, kind: str = "annual", on: date) -> Decimal:
    """Days of leave of `kind` the member has left on `on`.

    Until leave balances exist (package L), nobody accrues leave, so it is always 0.
    """
    return Decimal("0")


def days_off(member: Membership, first: date, last: date) -> set[date]:
    """The member's days off from `first` to `last`: company holidays and approved time off."""
    off = set(
        Holiday.objects.filter(company_id=member.company_id, date__range=(first, last)).values_list(
            "date", flat=True
        )
    )
    approved = TimeOff.objects.filter(
        membership=member, status=TimeOff.Status.APPROVED, first_day__lte=last, last_day__gte=first
    ).values_list("first_day", "last_day")
    for start, end in approved:
        day = max(start, first)
        while day <= min(end, last):
            off.add(day)
            day += timedelta(days=1)
    return off


def is_holiday(company: Company, day: date) -> bool:
    return Holiday.objects.filter(company=company, date=day).exists()


def members_off(company: Company, day: date) -> set[int]:
    """Ids of the members with approved time off on `day`."""
    return set(
        TimeOff.objects.filter(
            company=company, status=TimeOff.Status.APPROVED, first_day__lte=day, last_day__gte=day
        ).values_list("membership_id", flat=True)
    )


def off_today(member: Membership, today: date) -> dict | None:
    """Why the member has the day off, for the app's home screen."""
    holiday = Holiday.objects.filter(company_id=member.company_id, date=today).first()
    if holiday is not None:
        return {"kind": "holiday", "name": holiday.name, "until": today}
    time_off = (
        TimeOff.objects.filter(
            membership=member,
            status=TimeOff.Status.APPROVED,
            first_day__lte=today,
            last_day__gte=today,
        )
        .order_by("-last_day")
        .first()
    )
    if time_off is not None:
        return {"kind": "time_off", "name": "", "until": time_off.last_day}
    return None


# Owner console ----------------------------------------------------------------------------


def visible(viewer: Membership) -> QuerySet[TimeOff]:
    """Time off `viewer` may see in the console: of people sharing one of the branches they see
    (everyone with every branch), and always their own."""
    rows = TimeOff.objects.filter(company_id=viewer.company_id)
    branches = scope.branch_ids(viewer)
    if branches is not None:
        shared = TimeOff.objects.filter(
            company_id=viewer.company_id, membership__branches__in=branches
        )
        rows = rows.filter(Q(pk__in=shared.values("pk")) | Q(membership=viewer))
    return rows


def pending_for(viewer: Membership) -> QuerySet[TimeOff]:
    """Requests waiting for `viewer`'s decision: visible to them and not their own."""
    return visible(viewer).filter(status=TimeOff.Status.PENDING).exclude(membership=viewer)


def pending_count(viewer: Membership) -> int:
    return pending_for(viewer).count()


def calendar(
    company: Company,
    start: date,
    end: date,
    *,
    branch_ids: list[int] | None,
    include_everyone: bool = False,
    position_ids: list[int] | None = None,
) -> list[dict]:
    """Time off from `start` to `end` (inclusive) per person, for the month calendar:
    `[{"member": {id, name, photo_url}, "position", "home_branch", "items": [...]}]`, people
    with time off first. Branch-bound: people sharing one of `branch_ids` (None: everyone).
    `include_everyone` adds current members without time off as empty rows."""
    rows = (
        TimeOff.objects.filter(
            company=company, status__in=SHOWN, first_day__lte=end, last_day__gte=start
        )
        .select_related("membership__user", "membership__position", "membership__home_branch")
        .order_by("first_day", "pk")
    )
    people = Membership.objects.filter(company=company)
    if branch_ids is not None:
        in_scope = Membership.objects.filter(company=company, branches__in=branch_ids)
        rows = rows.filter(membership__in=in_scope.values("pk"))
        people = people.filter(pk__in=in_scope.values("pk"))
    if position_ids:
        rows = rows.filter(membership__position_id__in=position_ids)
        people = people.filter(position_id__in=position_ids)
    by_member: dict[int, dict] = {}
    for time_off in rows:
        member = time_off.membership
        entry = by_member.setdefault(member.pk, _calendar_row(member))
        entry["items"].append(
            {
                "id": time_off.pk,
                "first_day": time_off.first_day.isoformat(),
                "last_day": time_off.last_day.isoformat(),
                "status": time_off.status,
                "reason": time_off.reason,
                "recorded": time_off.recorded_by_id is not None,
                "days": time_off.days,
            }
        )
    result = sorted(by_member.values(), key=lambda row: row["member"]["name"].lower())
    if include_everyone:
        others = (
            people.filter(
                status__in=(Membership.Status.APPROVED, Membership.Status.SUSPENDED),
                onboarded_at__isnull=False,
            )
            .exclude(pk__in=list(by_member))
            .select_related("user", "position", "home_branch")
            .order_by("first_name", "last_name")
        )
        result += [_calendar_row(member) for member in others]
    return result


def _calendar_row(member: Membership) -> dict:
    return {
        "member": person_ref(member),
        "position": member.position.name if member.position_id else None,
        "home_branch": branch_ref(member.home_branch),
        "items": [],
    }


def holidays_between(company: Company, start: date, end: date) -> QuerySet[Holiday]:
    return Holiday.objects.filter(company=company, date__range=(start, end)).order_by("date")


def stats(viewer: Membership, today: date) -> dict:
    """The numbers above the time-off page, inside the viewer's scope."""
    rows = visible(viewer)
    approved = rows.filter(status=TimeOff.Status.APPROVED)
    week_end = today + timedelta(days=6 - today.weekday())
    month_start = today.replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    month_end = next_month - timedelta(days=1)
    off_today = approved.filter(first_day__lte=today, last_day__gte=today)
    days_this_month = 0
    for first, last in approved.filter(
        first_day__lte=month_end, last_day__gte=month_start
    ).values_list("first_day", "last_day"):
        days_this_month += (min(last, month_end) - max(first, month_start)).days + 1
    next_holiday = (
        Holiday.objects.filter(company_id=viewer.company_id, date__gte=today)
        .order_by("date")
        .first()
    )
    return {
        "pending": pending_count(viewer),
        "off_today": off_today.values("membership").distinct().count(),
        "off_this_week": approved.filter(first_day__lte=week_end, last_day__gte=today)
        .values("membership")
        .distinct()
        .count(),
        "days_this_month": days_this_month,
        "next_holiday": (
            {"date": next_holiday.date.isoformat(), "name": next_holiday.name}
            if next_holiday
            else None
        ),
    }


def off_on(company: Company, day: date, member_ids: list[int]) -> dict[int, dict]:
    """{member id: {"id", "until"}} for the given people on approved time off on `day`."""
    found = {}
    for time_off in TimeOff.objects.filter(
        company=company,
        status=TimeOff.Status.APPROVED,
        first_day__lte=day,
        last_day__gte=day,
        membership_id__in=member_ids,
    ).order_by("last_day"):
        found[time_off.membership_id] = {
            "id": time_off.pk,
            "until": time_off.last_day.isoformat(),
        }
    return found
