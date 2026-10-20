"""factory_boy factories for the models of attendance.

Shifts are built from a local day and wall-clock times (`shift_at`), the way the services make
them; records usually come from `services.check_in` in the tests themselves.
"""

from datetime import date, time

import factory
from factory.django import DjangoModelFactory

from apps.attendance import clock
from apps.attendance.models import (
    AttendanceRecord,
    MemberSchedule,
    ShiftTemplate,
    WorkSchedule,
    WorkScheduleDay,
    WorkShift,
)
from apps.companies.tests.factories import CompanyFactory


class WorkScheduleFactory(DjangoModelFactory):
    class Meta:
        model = WorkSchedule

    company = factory.SubFactory(CompanyFactory)
    name = factory.Sequence(lambda n: f"Schedule {n}")
    kind = WorkSchedule.Kind.WEEKLY


class ShiftTemplateFactory(DjangoModelFactory):
    class Meta:
        model = ShiftTemplate

    company = factory.SubFactory(CompanyFactory)
    name = factory.Sequence(lambda n: f"Template {n}")
    starts_at = time(9, 0)
    ends_at = time(18, 0)


def weekly_schedule(company, *, days=range(6), starts=time(9, 0), ends=time(18, 0), pause=60, **kw):
    schedule = WorkScheduleFactory(company=company, **kw)
    for day in days:
        WorkScheduleDay.objects.create(
            schedule=schedule, weekday=day, starts_at=starts, ends_at=ends, break_minutes=pause
        )
    return schedule


def assign(member, schedule, effective_from: date) -> MemberSchedule:
    return MemberSchedule.objects.create(
        company=member.company, membership=member, schedule=schedule, effective_from=effective_from
    )


def shift_at(
    member,
    day: date,
    starts: time = time(9, 0),
    ends: time = time(18, 0),
    *,
    company=None,
    published: bool = True,
    status=WorkShift.Status.PLANNED,
    branch=None,
    position=None,
    break_minutes: int = 60,
    source=WorkShift.Source.MANUAL,
) -> WorkShift:
    """A shift on `day` from `starts` to `ends` local time (an end before the start is the
    next day). `member=None` makes an open shift."""
    company = company or member.company
    start, end = clock.window(company, day, starts, ends)
    return WorkShift.objects.create(
        company=company,
        membership=member,
        date=day,
        starts_at=start,
        ends_at=end,
        break_minutes=break_minutes,
        branch=branch if branch is not None else (member.home_branch if member else None),
        position=position if position is not None else (member.position if member else None),
        status=status if member else WorkShift.Status.OPEN,
        source=source,
        published_at=start.replace(year=start.year - 1) if published else None,
    )


def absent(shift) -> AttendanceRecord:
    return AttendanceRecord.objects.create(
        company=shift.company,
        membership=shift.membership,
        shift=shift,
        date=shift.date,
        status=AttendanceRecord.Status.ABSENT,
        branch=shift.branch,
    )
