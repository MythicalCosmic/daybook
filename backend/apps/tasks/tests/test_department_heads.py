"""Department heads and tasks: a head gives their people work, sees it, checks it and answers
their requests, without the role permissions for it; late work reaches the person's head."""

from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.members import departments
from apps.members.models import Membership
from apps.reminders.policies import escalation_recipients
from apps.tasks import queries, rules, services
from apps.tasks.models import Proof, Task

pytestmark = pytest.mark.django_db


@pytest.fixture
def org(company, member):
    """Savdo (head Bekzod, an Employee by role) with Alisher; Ombor with Otabek (no head);
    the owner heads Rahbariyat above both."""
    owner = member.registered(company, "Owner")
    bekzod = member.registered(company, first_name="Bekzod")
    alisher = member.registered(company, first_name="Alisher")
    otabek = member.registered(company, first_name="Otabek")
    top = departments.create_department(company, by=owner, name="Rahbariyat", head=owner)
    sales = departments.create_department(company, by=owner, name="Savdo", parent=top, head=bekzod)
    stock = departments.create_department(company, by=owner, name="Ombor", parent=top)
    departments.place(sales, by=owner, people=[bekzod, alisher])
    departments.place(stock, by=owner, people=[otabek])
    return {
        "owner": fresh(owner),
        "bekzod": fresh(bekzod),
        "alisher": fresh(alisher),
        "otabek": fresh(otabek),
    }


def fresh(member: Membership) -> Membership:
    return Membership.objects.select_related("role", "company", "user").get(pk=member.pk)


def test_a_head_gives_work_to_their_people_without_the_role_permission(
    org, sent_messages, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        task = services.create_task(
            by=org["bekzod"], assignee=org["alisher"], title="Vitrinani tartibga keltirish"
        )

    assert task.kind == Task.Kind.ASSIGNED
    assert task.created_by == org["bekzod"]
    assert any(m["chat_id"] == org["alisher"].user.telegram_id for m in sent_messages)


def test_a_head_cant_give_work_outside_their_department(org):
    with pytest.raises(PermissionDenied):
        services.create_task(by=org["bekzod"], assignee=org["otabek"], title="Omborni sanash")


def test_the_head_above_gives_work_to_everyone_below(org):
    task = services.create_task(by=org["owner"], assignee=org["alisher"], title="Hisobot")

    assert task.assignee == org["alisher"]


def test_a_head_sees_their_peoples_tasks_but_not_others(org):
    theirs = services.create_task(by=org["owner"], assignee=org["alisher"], title="Alisherga")
    others = services.create_task(by=org["owner"], assignee=org["otabek"], title="Otabekka")
    personal = services.create_task(by=org["alisher"], title="O‘zimga")

    visible = set(queries.visible_tasks(fresh(org["bekzod"])))

    assert theirs in visible
    assert others not in visible
    assert personal not in visible  # someone's personal tasks stay theirs


def test_a_head_checks_their_peoples_finished_work(org):
    task = services.create_task(
        by=org["owner"],
        assignee=org["alisher"],
        title="Muzlatgich harorati",
        proof=Proof.TEXT,
        needs_confirmation=True,
    )
    task = services.complete_task(task, by=org["alisher"], proof_text="+5")
    assert task.status == Task.Status.REVIEW
    head = fresh(org["bekzod"])

    assert task in queries.awaiting_review_by(head)
    assert rules.can_review(task, head)
    assert services.confirm_task(task, by=head).status == Task.Status.DONE


def test_routine_work_waiting_for_a_check_goes_to_the_persons_head(org):
    task = Task.objects.create(
        company=org["alisher"].company,
        kind=Task.Kind.DAILY,
        title="Kassani ochish",
        assignee=org["alisher"],
        status=Task.Status.REVIEW,
        needs_confirmation=True,
        for_date=timezone.localdate(),
    )

    assert queries.reviewers(task) == [org["bekzod"]]


def test_a_head_answers_their_peoples_cant_do_it(org):
    task = services.create_task(by=org["owner"], assignee=org["alisher"], title="Dori buyurtmasi")

    assert services.can_decide(task, fresh(org["bekzod"]))
    assert not services.can_decide(task, fresh(org["otabek"]))


def test_a_head_nudges_their_people(org):
    task = services.create_task(
        by=org["owner"], assignee=org["alisher"], title="Narxlarni yangilash"
    )

    assert rules.can_nudge(task, fresh(org["bekzod"]))
    assert not rules.can_nudge(task, fresh(org["otabek"]))


def test_a_head_hands_work_they_gave_to_another_of_their_people(company, member, org):
    lola = member.registered(company, first_name="Lola")
    sales = org["bekzod"].headed_departments.get()
    departments.place(sales, by=org["owner"], people=[lola])
    task = services.create_task(by=org["bekzod"], assignee=org["alisher"], title="Yetkazish")

    moved = services.reassign_task(task, by=fresh(org["bekzod"]), assignee=fresh(lola))

    assert moved.assignee_id == lola.pk
    with pytest.raises(PermissionDenied):
        services.reassign_task(moved, by=fresh(org["bekzod"]), assignee=org["otabek"])


def test_late_work_reaches_the_persons_head_too(org):
    task = services.create_task(
        by=org["owner"],
        assignee=org["alisher"],
        title="Kun yakuni hisoboti",
        due_at=timezone.now() + timedelta(hours=1),
    )
    Task.objects.filter(pk=task.pk).update(due_at=timezone.now() - timedelta(hours=1))
    task.refresh_from_db()

    assert escalation_recipients(task) == [org["owner"], org["bekzod"]]


def test_late_work_a_head_gave_isnt_escalated_to_them_twice(org):
    task = services.create_task(by=org["bekzod"], assignee=org["alisher"], title="Polkalar")

    assert escalation_recipients(task) == [org["bekzod"]]


def test_someones_personal_tasks_dont_reach_their_head(org):
    task = services.create_task(by=org["alisher"], title="Shaxsiy ish")

    assert org["bekzod"] not in escalation_recipients(task)
