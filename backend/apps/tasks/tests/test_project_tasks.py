"""Tasks on a project's board through the task app's own contract (docs/PLAN-OWNER.md §13.3):
`create_task(project=, project_list=, milestone=)` and who may hand such work out."""

import pytest
from django.core.exceptions import PermissionDenied

from apps.companies.models import Branch
from apps.core.exceptions import DomainError
from apps.projects import services as project_services
from apps.projects.models import Card, ProjectMember
from apps.projects.tests.factories import lists, project, team
from apps.tasks import services
from apps.tasks import tasks as jobs
from apps.tasks.models import Activity, Task

pytestmark = pytest.mark.django_db


@pytest.fixture
def people(company, member):
    return team(company, member)


def without_assign(person):
    """`person`'s role without tasks.assign (a lead who isn't a manager)."""
    role = person.role
    role.permissions = [p for p in role.permissions if p != "tasks.assign"]
    role.save()
    person.refresh_from_db()
    return person


def told(callbacks) -> bool:
    return any(getattr(cb, "func", None) == jobs.notify_task_assigned.delay for cb in callbacks)


def test_a_task_made_on_a_board_is_a_numbered_card_in_the_first_list(company, people):
    reno = project(company, people["owner"], key="RENO")
    launch = project_services.create_milestone(reno, by=people["owner"], name="Launch")

    task = services.create_task(
        by=people["owner"],
        title="Order tiles",
        assignee=people["aziz"],
        project=reno,
        milestone=launch,
    )

    task.refresh_from_db()
    assert task.project == reno
    assert task.project_list == lists(reno)["Backlog"]
    assert task.milestone == launch
    assert Card.objects.get(task=task).number == 1
    # The person given the card joins the project.
    assert ProjectMember.objects.filter(project=reno, membership=people["aziz"]).exists()


def test_a_card_goes_to_the_end_of_the_list_it_was_made_in(company, people):
    reno = project(company, people["owner"])
    doing = lists(reno)["In progress"]

    first = services.create_task(by=people["owner"], title="A", project=reno, project_list=doing)
    second = services.create_task(by=people["owner"], title="B", project=reno, project_list=doing)

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.project_list == second.project_list == doing
    assert second.list_position > first.list_position


def test_a_card_for_yourself_is_shared_work_and_tells_nobody(
    company, people, django_capture_on_commit_callbacks
):
    reno = project(company, people["owner"])

    with django_capture_on_commit_callbacks() as callbacks:
        task = services.create_task(
            by=people["owner"], title="Sign the lease", project=reno, needs_confirmation=True
        )

    assert task.kind == Task.Kind.ASSIGNED
    assert not task.needs_confirmation
    assert not told(callbacks)
    assert not Activity.objects.filter(task=task, kind=Activity.Kind.ASSIGNED).exists()


def test_a_reward_is_still_only_for_someone_else(company, people):
    reno = project(company, people["owner"])

    with pytest.raises(DomainError):
        services.create_task(by=people["owner"], title="Mine", project=reno, reward=1000)


def test_the_board_list_and_milestone_are_checked(company, other_company, member, people):
    reno = project(company, people["owner"])
    other = project(company, people["owner"], name="Website relaunch")
    elsewhere = lists(other)["Backlog"]
    their_milestone = project_services.create_milestone(other, by=people["owner"], name="Go live")
    stranger = member.registered(other_company, "Owner")
    foreign = project(other_company, stranger, name="Their project")
    owner = people["owner"]

    with pytest.raises(DomainError):
        services.create_task(by=owner, title="X", project=reno, project_list=elsewhere)
    with pytest.raises(DomainError):
        services.create_task(by=owner, title="X", project=reno, milestone=their_milestone)
    with pytest.raises(DomainError):
        services.create_task(by=owner, title="X", project_list=elsewhere)
    with pytest.raises(DomainError):
        services.create_task(by=owner, title="X", project=foreign)
    project_services.archive_project(reno, by=owner)
    reno.refresh_from_db()
    with pytest.raises(DomainError, match="archived"):
        services.create_task(by=owner, title="X", project=reno)
    assert not Task.objects.filter(title="X").exists()


def test_a_lead_hands_cards_to_the_people_on_their_project(
    company, people, django_capture_on_commit_callbacks
):
    lead = without_assign(people["manager"])
    reno = project(company, people["owner"], lead=lead)
    project_services.add_member(reno, people["aziz"], by=people["owner"])

    with django_capture_on_commit_callbacks() as callbacks:
        task = services.create_task(
            by=lead, title="Hang the sign", assignee=people["aziz"], project=reno
        )

    assert task.kind == Task.Kind.ASSIGNED and task.created_by == lead
    assert told(callbacks)
    assert Activity.objects.filter(task=task, kind=Activity.Kind.ASSIGNED).exists()
    # Not to someone who isn't on the project, and not on a task outside it.
    with pytest.raises(PermissionDenied):
        services.create_task(by=lead, title="X", assignee=people["madina"], project=reno)
    with pytest.raises(PermissionDenied):
        services.create_task(by=lead, title="X", assignee=people["aziz"])


def test_leading_one_project_gives_nothing_on_another(company, people):
    lead = without_assign(people["manager"])
    project(company, people["owner"], lead=lead, name="Mine")
    theirs = project(company, people["owner"], name="Theirs")
    project_services.add_member(theirs, lead, by=people["owner"])
    project_services.add_member(theirs, people["aziz"], by=people["owner"])

    with pytest.raises(PermissionDenied):
        services.create_task(by=lead, title="X", assignee=people["aziz"], project=theirs)


def test_a_plain_member_still_only_makes_cards_for_themselves(company, people):
    reno = project(company, people["owner"])
    project_services.add_member(reno, people["aziz"], by=people["owner"])
    project_services.add_member(reno, people["madina"], by=people["owner"])

    with pytest.raises(PermissionDenied):
        services.create_task(by=people["aziz"], title="X", assignee=people["madina"], project=reno)


def test_people_on_the_project_are_in_reach_whatever_their_branch(company, member, people):
    first = company.branches.order_by("order", "pk").first()
    far = Branch.objects.create(company=company, name="Yunusobod")
    scoped = member.registered(company, "Manager", home_branch=first)
    scoped.role.permissions = [p for p in scoped.role.permissions if p != "branches.all"]
    scoped.role.save()
    scoped.branches.set([first])
    far_worker = member.registered(company, home_branch=far)
    far_worker.branches.set([far])
    far_stranger = member.registered(company, home_branch=far)
    far_stranger.branches.set([far])
    reno = project(company, people["owner"], lead=scoped)
    project_services.add_member(reno, far_worker, by=people["owner"])

    task = services.create_task(by=scoped, title="Bring paint", assignee=far_worker, project=reno)

    assert task.assignee == far_worker
    with pytest.raises(DomainError, match="branch"):
        services.create_task(by=scoped, title="X", assignee=far_stranger, project=reno)


def test_a_lead_moves_a_card_only_between_their_projects_people(company, people):
    lead = without_assign(people["manager"])
    reno = project(company, people["owner"], lead=lead)
    project_services.add_member(reno, people["aziz"], by=people["owner"])
    project_services.add_member(reno, people["madina"], by=people["owner"])
    task = services.create_task(by=lead, title="Paint", assignee=people["aziz"], project=reno)
    project_services.remove_member(reno, people["madina"], by=people["owner"])

    with pytest.raises(PermissionDenied):
        services.reassign_task(task, by=lead, assignee=people["madina"])
    project_services.add_member(reno, people["madina"], by=people["owner"])
    moved = services.reassign_task(task, by=lead, assignee=people["madina"])

    assert moved.assignee == people["madina"]


def test_a_card_for_yourself_doesnt_let_you_hand_it_to_others(company, people):
    reno = project(company, people["owner"])
    project_services.add_member(reno, people["aziz"], by=people["owner"])
    own = services.create_task(by=people["aziz"], title="Mine", project=reno)

    with pytest.raises(PermissionDenied):
        services.reassign_task(own, by=people["aziz"], assignee=people["madina"])
