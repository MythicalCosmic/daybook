"""Department heads and tasks: the rules a review pinned down (a head hands blocked work only to
their own people, never checks their own head's work, gives work from the dashboard, stays out of
members-only projects; late routine work reaches the branch's checkers as well)."""

from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.companies.tests.factories import BranchFactory
from apps.core.exceptions import DomainError
from apps.members import departments
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.tests.factories import AccessRoleFactory
from apps.projects import services as project_services
from apps.reminders.policies import escalation_recipients
from apps.tasks import queries, rules, services
from apps.tasks.models import Proof, Task

pytestmark = pytest.mark.django_db


def fresh(member: Membership) -> Membership:
    return Membership.objects.select_related("role", "company", "user").get(pk=member.pk)


@pytest.fixture
def shop(company, member):
    """One pharmacy branch. Savdo: Bekzod (its head, an Employee by role) and Alisher.
    Otabek works in the same branch but in no department; the owner heads nothing."""
    branch = company.branches.first()
    owner = member.registered(company, "Owner")
    people = {}
    for name in ("Bekzod", "Alisher", "Otabek"):
        person = member.registered(company, first_name=name, home_branch=branch)
        person.branches.add(branch)
        people[name.lower()] = person
    sales = departments.create_department(company, by=owner, name="Savdo", head=people["bekzod"])
    departments.place(sales, by=owner, people=[people["bekzod"], people["alisher"]])
    return {"owner": fresh(owner), "sales": sales, **{k: fresh(v) for k, v in people.items()}}


def blocked_task(shop) -> Task:
    task = services.create_task(by=shop["owner"], assignee=shop["alisher"], title="Dori buyurtmasi")
    return services.report_blocker(task, by=shop["alisher"], reason_code=Task.Blocker.NO_STOCK)


# Answering a "can't do it" with "someone else" -------------------------------------------------


def test_a_head_answering_cant_do_it_gives_the_work_only_to_their_people(shop):
    """`can_decide` lets a head answer their person's "can't do it"; the "someone else" answer
    then checks the new person with `_colleague`, which only asks for the head's branch scope.
    A head without tasks.assign hands the work to anyone in their branch (Otabek is in no
    department), though `create_task` and `reassign_task` would refuse him."""
    task = blocked_task(shop)
    with pytest.raises(PermissionDenied):  # giving Otabek work directly is refused (passes)
        services.create_task(by=fresh(shop["bekzod"]), assignee=shop["otabek"], title="Sanash")

    with pytest.raises((PermissionDenied, DomainError)):
        services.resolve_blocker(
            task, by=fresh(shop["bekzod"]), action="reassign", assignee_id=shop["otabek"].pk
        )
    task.refresh_from_db()
    assert task.assignee_id == shop["alisher"].pk


def test_a_head_answering_cant_do_it_may_hand_it_to_their_person_in_another_branch(
    company, member, shop
):
    """The other side of the same check: the bot's "Someone else" picker (`_colleagues`, now
    `departments.assignable`) offers the head's people wherever they work, and the answer then
    fails with "works in a branch you don't manage" for one in another branch."""
    there = BranchFactory(company=company, name="Yunusobod")
    far = member.registered(company, first_name="Lola", home_branch=there)
    far.branches.add(there)
    departments.place(shop["sales"], by=shop["owner"], people=[far])
    task = blocked_task(shop)

    moved = services.resolve_blocker(
        task, by=fresh(shop["bekzod"]), action="reassign", assignee_id=far.pk
    )

    assert moved.assignee_id == far.pk


# A head sitting below their own department -----------------------------------------------------


def test_a_head_cant_check_the_work_of_their_own_head(company, member):
    """The owner heads Rahbariyat and works in Savdo, which Bekzod heads under it: Bekzod's own
    head is the owner, yet he may accept the owner's finished work (and sees the owner's tasks
    and gives the owner work)."""
    owner = member.registered(company, "Owner")
    manager = member.registered(company, "Manager")
    bekzod = member.registered(company, first_name="Bekzod")
    top = departments.create_department(company, by=owner, name="Rahbariyat", head=owner)
    sales = departments.create_department(company, by=owner, name="Savdo", parent=top, head=bekzod)
    departments.place(sales, by=owner, people=[owner, bekzod])
    task = services.create_task(
        by=fresh(manager),
        assignee=fresh(owner),
        title="Litsenziyani yangilash",
        proof=Proof.TEXT,
        needs_confirmation=True,
    )
    task = services.complete_task(task, by=fresh(owner), proof_text="Topshirildi")
    assert task.status == Task.Status.REVIEW
    head = fresh(bekzod)

    assert departments.manager_of(fresh(bekzod)) == owner  # the owner is his head (passes)
    assert not rules.can_review(task, head)
    assert task not in queries.awaiting_review_by(head)
    with pytest.raises(PermissionDenied):
        services.create_task(by=fresh(bekzod), assignee=fresh(owner), title="Hisobot")


# The dashboard ----------------------------------------------------------------------------------


def test_a_head_gives_their_people_work_from_the_dashboard(owner_api, company, member):
    """The contract: a head gives tasks to their people "(bot, mini app, dashboard), even
    without the role permission". The owner tasks endpoint still requires tasks.assign for
    create (and its people picker, `options`, lists the branch scope only), so a head with
    dashboard access gets 403."""
    owner = member.registered(company, "Owner")
    role = AccessRoleFactory(company=company, permissions=[Perm.DASHBOARD_ACCESS])
    head = member.registered(company, role.name, first_name="Bekzod")
    alisher = member.registered(company, first_name="Alisher")
    sales = departments.create_department(company, by=owner, name="Savdo", head=head)
    departments.place(sales, by=owner, people=[alisher])
    api = owner_api(head)

    created = api.post(
        f"/api/v1/owner/companies/{company.pk}/tasks/",
        {"title": "Vitrinani tartibga keltirish", "assignee_ids": [alisher.pk]},
        format="json",
    )
    options = api.get(f"/api/v1/owner/companies/{company.pk}/tasks/options/")

    assert created.status_code == 201, created.data
    assert options.status_code == 200
    assert alisher.pk in {person["id"] for person in options.data["people"]}


# Members-only projects -------------------------------------------------------------------------


def test_a_head_outside_a_members_only_project_isnt_told_about_its_cards(shop):
    """Alisher's card on a members-only project is hidden from Bekzod, who isn't on it
    (projects.hide_private_project_tasks), yet `escalation_recipients` now always adds the
    assignee's head: the late alert, the "can't do it" and the "need more time" notices (with
    the card's title and note) reach him, and `can_decide` lets him answer the inbox's
    "Give more time" for a task he can't open."""
    project = project_services.create_project(
        shop["owner"].company,
        by=shop["owner"],
        name="Yangi filial",
        member_ids=[shop["alisher"].pk],
    )
    task = services.create_task(
        by=shop["owner"],
        assignee=shop["alisher"],
        title="Ijara shartnomasi",
        project=project,
        due_at=timezone.now() + timedelta(hours=3),
    )
    head = fresh(shop["bekzod"])
    assert not queries.visible_tasks(head).filter(pk=task.pk).exists()  # hidden (passes)

    assert head not in escalation_recipients(task)
    assert not services.can_decide(task, head)


# Late routine work: the head as well as, or instead of, the branch's checkers --------------------


def test_late_routine_work_reaches_the_branchs_checkers_as_well_as_the_head(company, member, shop):
    """The contract: "late-task escalations also go to the person's own head". For work nobody
    gave by hand (a routine, a card someone took) `escalation_recipients` returns the head
    instead: the branch's checkers (closest_confirmers) stop hearing once the person has a
    head, however junior the head's role. (Also: a task with a named escalation contact
    returns early, so the head isn't told at all.) If replacing is the intent, the contract
    needs the change instead."""
    checker = member.registered(company, "Manager")  # tasks.confirm, every branch
    task = Task.objects.create(
        company=company,
        kind=Task.Kind.DAILY,
        title="Kassani ochish",
        assignee=shop["alisher"],
        branch=company.branches.first(),
        for_date=timezone.localdate(),
        due_at=timezone.now() - timedelta(hours=1),
    )
    assert checker in queries.closest_confirmers(task)  # who heard before departments (passes)

    recipients = escalation_recipients(task)

    assert shop["bekzod"] in recipients
    assert checker in recipients, [str(r) for r in recipients]
