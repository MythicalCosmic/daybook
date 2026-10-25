"""Who sees which task (docs/PLAN-OWNER.md §3.2), the branch a task belongs to, and the
registries other apps narrow visibility and daily generation with."""

from datetime import date, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.companies.tests.factories import BranchFactory
from apps.members.models import AccessRole
from apps.members.permissions import Perm
from apps.reminders.policies import escalation_recipients
from apps.tasks import offdays, queries, services, visibility
from apps.tasks.generation import generate_daily_tasks
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory, TaskTemplateFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def branches(company):
    return company.branches.get(), BranchFactory(company=company, name="Yunusobod")


def visible(member) -> set[int]:
    return set(queries.visible_tasks(member).values_list("pk", flat=True))


def scoped_role(company, name, perms):
    return AccessRole.objects.create(company=company, name=name, permissions=perms)


def test_view_all_within_a_branch_sees_that_branch_and_their_own(company, member, branches):
    here, there = branches
    scoped_role(company, "Branch lead", [Perm.TASKS_VIEW_ALL, Perm.TASKS_ASSIGN])
    lead = member.registered(company, "Branch lead")
    lead.branches.set([here])
    owner = member.registered(company, "Owner")
    worker = member.registered(company)
    in_here = TaskFactory(assignee=worker, created_by=owner, branch=here)
    in_there = TaskFactory(assignee=worker, created_by=owner, branch=there)
    no_branch = TaskFactory(assignee=worker, created_by=owner)
    handed_out = TaskFactory(assignee=worker, created_by=lead, branch=there)
    own = TaskFactory(assignee=lead, created_by=owner, branch=there)

    assert visible(lead) == {in_here.pk, handed_out.pk, own.pk}
    assert in_there.pk not in visible(lead) and no_branch.pk not in visible(lead)


def test_every_branch_sees_everything_shared(company, member, branches):
    here, there = branches
    manager = member.registered(company, "Manager")  # branches.all
    owner = member.registered(company, "Owner")
    worker = member.registered(company)
    shared = [
        TaskFactory(assignee=worker, created_by=owner, branch=here),
        TaskFactory(assignee=worker, created_by=owner, branch=there),
        TaskFactory(assignee=worker, created_by=owner),
    ]

    assert visible(manager) == {task.pk for task in shared}


def test_no_branches_and_no_branches_all_means_no_branch_bound_tasks(company, member, branches):
    here, _there = branches
    scoped_role(company, "Viewer", [Perm.TASKS_VIEW_ALL])
    viewer = member.registered(company, "Viewer")  # no branches at all
    owner = member.registered(company, "Owner")
    TaskFactory(assignee=member.registered(company), created_by=owner, branch=here)
    own = TaskFactory(assignee=viewer, created_by=owner, branch=here)

    assert visible(viewer) == {own.pk}


def test_personal_tasks_are_excluded_before_every_other_rule(company, member):
    manager = member.registered(company, "Manager")
    worker = member.registered(company)
    personal = TaskFactory(assignee=worker)
    from_template = TaskFactory(assignee=worker, kind=Task.Kind.PERSONAL, created_by=None)
    mine = TaskFactory(assignee=manager)

    assert visible(manager) == {mine.pk}
    assert visible(worker) == {personal.pk, from_template.pk}
    assert personal.pk not in set(queries.awaiting_review_by(manager).values_list("pk", flat=True))


def test_registered_filters_narrow_what_people_see(company, member, monkeypatch):
    monkeypatch.setattr(visibility, "_filters", {})
    manager = member.registered(company, "Manager")
    owner = member.registered(company, "Owner")
    worker = member.registered(company)
    secret = TaskFactory(assignee=worker, created_by=owner, title="Secret project card")
    public = TaskFactory(assignee=worker, created_by=owner, title="Shelves")
    seen = []

    def hide_secret(tasks, member):
        seen.append(member.pk)
        return tasks.exclude(title__startswith="Secret")

    visibility.register_task_visibility_filter("projects.members", hide_secret)

    assert visible(manager) == {public.pk}
    assert visible(owner) == {public.pk}
    assert secret.pk not in visible(worker)
    assert seen == [manager.pk, owner.pk, worker.pk]


def test_filter_registration_rules(monkeypatch):
    monkeypatch.setattr(visibility, "_filters", {})
    visibility.register_task_visibility_filter("projects.members", lambda tasks, m: tasks)

    with pytest.raises(visibility.DuplicateTaskFilter):
        visibility.register_task_visibility_filter("projects.members", lambda tasks, m: tasks)
    with pytest.raises(ValueError):
        visibility.register_task_visibility_filter("nodot", lambda tasks, m: tasks)
    with pytest.raises(ValueError, match="installed app"):
        visibility.register_task_visibility_filter("nosuchapp.x", lambda tasks, m: tasks)
    assert visibility.registered_keys() == ["projects.members"]


def test_a_new_task_belongs_to_its_assignees_branch_for_good(company, member, branches):
    here, there = branches
    manager = member.registered(company, "Manager", home_branch=here)
    worker = member.registered(company, home_branch=here)

    task = services.create_task(by=manager, title="Count the till", assignee=worker)
    own = services.create_task(by=worker, title="Call mum")
    worker.home_branch = there
    worker.save()
    services.update_task(task, by=manager, title="Count the till twice")

    task.refresh_from_db()
    assert task.branch == here  # moving branches later doesn't move the task
    assert own.branch == here


def test_daily_tasks_belong_to_the_branch_too(company, member, branches):
    here, _there = branches
    worker = member.registered(company, home_branch=here)
    nowhere = member.registered(company)
    template = TaskTemplateFactory(
        company=company, assignees=[worker, nowhere], due_time=time(23, 59)
    )

    generate_daily_tasks(company, timezone.localdate(timezone=ZoneInfo(company.timezone)))

    branches_by_person = dict(
        Task.objects.filter(template=template).values_list("assignee_id", "branch_id")
    )
    assert branches_by_person == {worker.pk: here.pk, nowhere.pk: None}


def test_offdays_providers_keep_people_out_of_daily_tasks(company, member, monkeypatch):
    monkeypatch.setattr(offdays, "_providers", [])
    worker = member.registered(company)
    rostered = member.registered(company)
    template = TaskTemplateFactory(
        company=company, assignees=[worker, rostered], due_time=time(23, 59)
    )
    asked = []

    def not_on_shift(company_, day):
        asked.append((company_.pk, day))
        return {worker.pk}

    offdays.register(not_on_shift)
    day = timezone.localdate(timezone=ZoneInfo(company.timezone))
    generate_daily_tasks(company, day)

    assert set(Task.objects.filter(template=template).values_list("assignee_id", flat=True)) == {
        rostered.pk
    }
    assert asked == [(company.pk, day)]


def test_providers_are_registered_once(monkeypatch):
    monkeypatch.setattr(offdays, "_providers", [])

    def provider(company, day):
        return set()

    offdays.register(provider)
    with pytest.raises(offdays.DuplicateProvider):
        offdays.register(provider)
    assert offdays.providers() == [provider]
    assert offdays.people_off(None, date(2026, 10, 20)) == set()


def test_cancel_routine_tasks_leaves_other_work(company, member):
    worker = member.registered(company)
    day = date(2026, 10, 20)
    today = TaskFactory(assignee=worker, kind=Task.Kind.DAILY, for_date=day)
    tomorrow = TaskFactory(assignee=worker, kind=Task.Kind.DAILY, for_date=day + timedelta(1))
    done = TaskFactory(assignee=worker, kind=Task.Kind.DAILY, for_date=day, status=Task.Status.DONE)
    personal = TaskFactory(assignee=worker, for_date=day)

    assert services.cancel_routine_tasks(worker, since=day) == 2

    statuses = {
        task.pk: Task.objects.get(pk=task.pk).status for task in (today, tomorrow, done, personal)
    }
    assert statuses == {
        today.pk: Task.Status.CANCELLED,
        tomorrow.pk: Task.Status.CANCELLED,
        done.pk: Task.Status.DONE,
        personal.pk: Task.Status.TODO,
    }


def test_review_requests_and_late_alerts_reach_only_confirmers_who_see_the_task(
    company, member, branches
):
    here, there = branches
    scoped_role(company, "Checker", [Perm.TASKS_CONFIRM])
    checker_here = member.registered(company, "Checker")
    checker_here.branches.set([here])
    checker_there = member.registered(company, "Checker")
    checker_there.branches.set([there])
    nowhere = member.registered(company, "Checker")  # no branches: no branch-bound work
    manager = member.registered(company, "Manager")  # tasks.confirm and branches.all
    worker = member.registered(company)
    routine = TaskFactory(
        assignee=worker, kind=Task.Kind.DAILY, branch=here, status=Task.Status.REVIEW
    )
    company_wide = TaskFactory(assignee=worker, kind=Task.Kind.DAILY)

    def pks(people):
        return {person.pk for person in people}

    # The branch's own checker first; the manager of every branch still sees it (audit X-11).
    assert pks(queries.reviewers(routine)) == {checker_here.pk}
    assert pks(escalation_recipients(routine)) == {checker_here.pk}
    assert manager.pk in pks(queries.confirmers(routine))
    assert pks(queries.reviewers(company_wide)) == {manager.pk}
    assert checker_there.pk not in pks(queries.confirmers(routine))
    assert nowhere.pk not in pks(queries.confirmers(routine))
    # Whoever the reviewers are, each can open the task they're asked about.
    for reviewer in queries.reviewers(routine):
        assert routine.pk in visible(reviewer)


def test_work_someone_gave_themselves_is_checked_by_someone_else(company, member):
    """Nobody can check their own work, so they aren't the one asked (nor told it was accepted
    after the wait): a board card a manager gave themselves goes to the other checkers."""
    manager = member.registered(company, "Manager")
    other = member.registered(company, "Manager")
    own = TaskFactory(
        assignee=manager, created_by=manager, kind=Task.Kind.ASSIGNED, status=Task.Status.REVIEW
    )

    reviewers = {person.pk for person in queries.reviewers(own)}

    assert manager.pk not in reviewers
    assert other.pk in reviewers
