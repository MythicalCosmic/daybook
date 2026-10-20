from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from apps.companies.models import Company
from apps.members.models import Membership
from apps.timeoff.models import Holiday, TimeOff


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
