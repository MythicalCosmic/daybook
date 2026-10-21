"""One set of routine rules everywhere (apps.tasks.generation): the generator, the "who gets it"
preview, a routine's next run and "Give today's task now" agree on who gets a routine's task on
a day, and a routine made after today's deadline says it starts the next day it is due.

The clock is frozen on Wednesday 23 October 2030 in the company's timezone."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.companies.tests.factories import BranchFactory
from apps.core.exceptions import DomainError
from apps.members.models import Membership
from apps.members.tests.factories import PositionFactory
from apps.tasks import generation, offdays, services
from apps.tasks.generation import generate_daily_tasks
from apps.tasks.models import Activity, Task, TaskTemplate
from apps.tasks.tests.factories import TaskTemplateFactory, make_shop
from apps.timeoff.models import Holiday, TimeOff

pytestmark = pytest.mark.django_db

WED = date(2030, 10, 23)
THU, FRI = WED + timedelta(days=1), WED + timedelta(days=2)
MON = WED + timedelta(days=5)


@pytest.fixture
def tz(company):
    return ZoneInfo(company.timezone)


@pytest.fixture
def at(tz):
    def moment(day: date, hour: int, minute: int = 0) -> datetime:
        return datetime.combine(day, time(hour, minute), tzinfo=tz)

    return moment


@pytest.fixture
def clock(monkeypatch):
    """`clock(moment)`: `timezone.now()` answers `moment` from then on (created_at too)."""

    def set_now(moment: datetime) -> datetime:
        monkeypatch.setattr("django.utils.timezone.now", lambda: moment)
        return moment

    return set_now


def routine_of(**fields) -> TaskTemplate:
    made = TaskTemplateFactory(**fields)
    made.refresh_from_db()  # the factory leaves due_time a string
    return made


def made_for(routine, day) -> set[int]:
    return set(
        Task.objects.filter(template=routine, for_date=day).values_list("assignee_id", flat=True)
    )


def test_a_routine_made_after_todays_deadline_starts_the_next_day(company, member, clock, at):
    clock(at(WED, 12, 30))
    ali = member.registered(company)
    routine = routine_of(company=company, assignees=[ali], due_time="09:00")

    preview = generation.preview(routine, WED)
    assert preview["reason"] == generation.MADE_LATE
    assert preview["next_run"] == at(THU, 9)
    # Ali would get it on any other day: the day is what's skipped, not the person.
    assert [(row["member"], row["gets"], row["reason"]) for row in preview["people"]] == [
        (ali, False, None)
    ]
    generate_daily_tasks(company, WED)
    assert made_for(routine, WED) == set()
    assert generation.next_run(routine, timezone.now()) == at(THU, 9)

    status = generation.today_status(routine, timezone.now())
    assert status == {
        "date": WED,
        "reason": generation.MADE_LATE,
        "give": {"people": 1, "due_at": at(WED, 14, 30)},
        "given": 0,
    }

    # Tomorrow it runs like any routine, and the preview says Ali gets it.
    assert generation.preview(routine, THU)["people"][0]["gets"] is True
    generate_daily_tasks(company, THU)
    assert made_for(routine, THU) == {ali.pk}


def test_a_routine_made_before_its_time_runs_today(company, member, clock, at):
    clock(at(WED, 8, 0))
    ali = member.registered(company)
    routine = routine_of(company=company, assignees=[ali], due_time="09:00")

    assert generation.preview(routine, WED)["reason"] is None
    assert generation.next_run(routine, timezone.now()) == at(WED, 9)
    assert generation.today_status(routine, timezone.now())["give"] is None
    generate_daily_tasks(company, WED)
    assert made_for(routine, WED) == {ali.pk}


def test_the_preview_and_the_generator_agree_person_by_person(
    company, member, clock, at, monkeypatch
):
    clock(at(WED, 6, 0))
    here = company.branches.get()
    there = BranchFactory(company=company, name="Yunusobod", code="YNS")
    cashier = PositionFactory(company=company, name="Kassir")

    def cashier_at(branch, **kwargs):
        return member.registered(company, position=cashier, home_branch=branch, **kwargs)

    gets = cashier_at(here)
    away = cashier_at(here)
    no_shift = cashier_at(here)
    elsewhere = cashier_at(there)
    late_joiner = cashier_at(here, onboarded_at=at(WED, 18, 5))
    unregistered = member(company, position=cashier, home_branch=here)
    suspended = cashier_at(here, status=Membership.Status.SUSPENDED)
    left = member.registered(company, home_branch=here, status=Membership.Status.LEFT)
    TimeOff.objects.create(
        company=company,
        membership=away,
        first_day=WED,
        last_day=WED,
        status=TimeOff.Status.APPROVED,
    )
    # Another app's day off (attendance's "no shift that day"), for this test only.
    monkeypatch.setattr(offdays, "_providers", [lambda company, day: {no_shift.pk}])
    routine = TaskTemplateFactory(
        company=company, positions=[cashier], assignees=[left], branch=here, due_time="18:00"
    )
    TaskTemplate.objects.filter(pk=routine.pk).update(created_at=at(WED, 0, 0) - timedelta(days=9))
    routine.refresh_from_db()

    rows = {row["member"].pk: row for row in generation.preview(routine, WED)["people"]}
    assert {pk: row["reason"] for pk, row in rows.items()} == {
        gets.pk: None,
        away.pk: generation.TIME_OFF,
        no_shift.pk: generation.DAY_OFF,
        elsewhere.pk: generation.BRANCH,
        late_joiner.pk: generation.JOINED_LATER,
        unregistered.pk: generation.NOT_REGISTERED,
        suspended.pk: generation.SUSPENDED,
        left.pk: generation.LEFT,
    }
    generate_daily_tasks(company, WED)
    assert made_for(routine, WED) == {pk for pk, row in rows.items() if row["gets"]} == {gets.pk}

    # A paused routine: the preview says so and nobody gets it, like the generator.
    TaskTemplate.objects.filter(pk=routine.pk).update(is_active=False)
    routine.refresh_from_db()
    paused = generation.preview(routine, THU)
    assert paused["reason"] == generation.PAUSED and paused["next_run"] is None
    assert not any(row["gets"] for row in paused["people"])
    generate_daily_tasks(company, THU)
    assert made_for(routine, THU) == set()


def test_the_next_run_follows_days_holidays_and_the_start(company, member, clock, at):
    clock(at(WED, 10, 0))
    long_ago = at(WED, 0, 0) - timedelta(days=30)

    def routine(**fields):
        made = TaskTemplateFactory(company=company, **{"due_time": "09:00", **fields})
        TaskTemplate.objects.filter(pk=made.pk).update(created_at=long_ago)
        made.refresh_from_db()
        return made

    every_day = routine()
    afternoon = routine(due_time="15:00")
    mondays = routine(weekdays=[0])
    later = routine(starts_on=WED + timedelta(days=10))
    paused = routine(is_active=False)
    onboarding = routine(onboarding=True)
    now = timezone.now()

    assert generation.next_run(afternoon, now) == at(WED, 15)  # later today
    assert generation.next_run(every_day, now) == at(THU, 9)  # today's 09:00 is gone
    assert generation.next_run(mondays, now) == at(MON, 9)
    assert generation.next_run(later, now) == at(WED + timedelta(days=10), 9)
    assert generation.next_run(paused, now) is None
    assert generation.next_run(onboarding, now) is None

    Holiday.objects.create(company=company, date=THU, name="Mustaqillik kuni")
    assert generation.next_run(every_day, now) == at(FRI, 9)
    everything = [every_day, afternoon, mondays, later, paused, onboarding]
    assert generation.next_runs(everything, company, now) == {
        r.pk: generation.next_run(r, now) for r in everything
    }


@pytest.mark.parametrize(
    ("now", "due"),
    [((12, 20), (14, 30)), ((12, 30), (14, 30)), ((12, 31), (14, 45)), ((22, 10), (23, 59))],
)
def test_todays_task_given_now_is_due_in_two_hours_on_the_quarter(tz, at, now, due):
    assert generation.suggested_deadline(at(WED, *now), tz) == at(WED, *due)


def test_give_todays_task_now(company, member, clock, at, django_capture_on_commit_callbacks):
    clock(at(WED, 12, 30))
    shop = make_shop(company, member)
    cashier = PositionFactory(company=company, name="Kassir")
    ali = member.registered(company, position=cashier, home_branch=shop.here)
    away = member.registered(company, position=cashier, home_branch=shop.here)
    member.registered(
        company, position=cashier, home_branch=shop.here, status=Membership.Status.SUSPENDED
    )
    TimeOff.objects.create(
        company=company,
        membership=away,
        first_day=WED,
        last_day=WED,
        status=TimeOff.Status.APPROVED,
    )
    routine = services.create_template(
        by=shop.owner,
        title="Muzlatgich haroratini yozish",
        due_time=time(9, 0),
        positions=[cashier],
        assignees=[shop.owner],
        checklist=["+2…+8 °C", "Jurnalga yozish"],
    )
    generate_daily_tasks(company, WED)
    assert made_for(routine, WED) == set()
    before = generation.today_status(routine, timezone.now())
    assert (before["given"], before["give"]["people"]) == (0, 2)

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        tasks = services.give_routine_today(routine, by=shop.owner)
    assert {task.assignee_id for task in tasks} == {ali.pk, shop.owner.pk}
    for task in Task.objects.filter(template=routine, for_date=WED):
        assert task.kind == Task.Kind.DAILY and task.due_at == at(WED, 14, 30)
        assert task.created_by == shop.owner
        assert [item.text for item in task.checklist.all()] == ["+2…+8 °C", "Jurnalga yozish"]
    # Ali hears about it; the owner who gave it to themselves doesn't.
    assert list(Activity.objects.values_list("recipient_id", flat=True)) == [ali.pk]
    assert len(callbacks) == 2  # Ali's message and the dashboards' pulse
    assert AuditLog.objects.filter(action="task.assigned").count() == 2

    # Done once: the generator adds nothing today, and giving again finds nobody.
    generate_daily_tasks(company, WED)
    assert made_for(routine, WED) == {ali.pk, shop.owner.pk}
    with pytest.raises(DomainError):
        services.give_routine_today(routine, by=shop.owner)
    # Its page now says today's task went out by hand, and offers it no more.
    after = generation.today_status(routine, timezone.now())
    assert (after["reason"], after["given"], after["give"]) == (generation.MADE_LATE, 2, None)


def test_todays_task_is_given_only_when_the_routine_was_made_late(company, member, clock, at):
    clock(at(WED, 12, 30))
    shop = make_shop(company, member)

    def routine(**fields):
        return services.create_template(
            by=shop.owner, title="Kassa", assignees=[shop.worker], **fields
        )

    on_time = routine(due_time=time(15, 0))
    with pytest.raises(DomainError, match="by itself"):
        services.give_routine_today(on_time, by=shop.owner)
    not_today = routine(due_time=time(9, 0), weekdays=[0])
    with pytest.raises(DomainError, match="days"):
        services.give_routine_today(not_today, by=shop.owner)
    late = routine(due_time=time(9, 0))
    with pytest.raises(DomainError, match="later today"):
        services.give_routine_today(late, by=shop.owner, due_at=at(WED, 12, 0))
    with pytest.raises(DomainError, match="later today"):
        services.give_routine_today(late, by=shop.owner, due_at=at(THU, 10, 0))
    # Only who may plan routines, in their branches.
    with pytest.raises(PermissionDenied):
        services.give_routine_today(late, by=shop.worker)
    elsewhere = services.create_template(
        by=shop.owner, title="Yunusobod", assignees=[shop.colleague], due_time=time(9, 0)
    )
    TaskTemplate.objects.filter(pk=elsewhere.pk).update(branch=shop.there)
    with pytest.raises(PermissionDenied):
        services.give_routine_today(elsewhere, by=shop.lead)

    Holiday.objects.create(company=company, date=WED, name="Bayram")
    with pytest.raises(DomainError, match="holiday"):
        services.give_routine_today(late, by=shop.owner)
    Holiday.objects.all().delete()
    tasks = services.give_routine_today(late, by=shop.owner, due_at=at(WED, 13, 0))
    assert [task.due_at for task in tasks] == [at(WED, 13, 0)]
