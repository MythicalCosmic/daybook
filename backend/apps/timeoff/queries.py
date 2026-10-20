from datetime import date, timedelta

from apps.companies.models import Company
from apps.members.models import Membership
from apps.timeoff.models import Holiday, TimeOff


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
