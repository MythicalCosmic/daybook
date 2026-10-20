import re
from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image

from apps.core.exceptions import DomainError
from apps.members.models import Membership
from apps.tasks import rules, services
from apps.tasks.models import Proof, Task
from apps.tasks.rules import Action
from apps.tasks.tests.factories import TaskFactory, jpeg

pytestmark = pytest.mark.django_db


def in_hours(hours: int):
    return timezone.now() + timedelta(hours=hours)


def photo() -> ContentFile:
    return jpeg("shelf.png")


@pytest.fixture
def worker(company, member):
    return member.registered(company)


@pytest.fixture
def manager(company, member):
    return member.registered(company, "Manager")


# Creating


def test_member_creates_a_personal_task(worker):
    task = services.create_task(by=worker, title="  Order receipt rolls ", due_at=in_hours(2))

    assert task.kind == Task.Kind.PERSONAL
    assert task.title == "Order receipt rolls"
    assert task.assignee == worker == task.created_by


def test_personal_tasks_never_need_confirmation(worker):
    task = services.create_task(by=worker, title="Water the plants", needs_confirmation=True)

    assert not task.needs_confirmation


def test_manager_assigns_a_task_and_the_assignee_is_told(
    manager, worker, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks() as callbacks:
        task = services.create_task(
            by=manager, assignee=worker, title="Call the supplier", checklist=["Ask date", " "]
        )

    assert task.kind == Task.Kind.ASSIGNED
    assert [item.text for item in task.checklist.all()] == ["Ask date"]
    assert len(callbacks) == 1


def test_employee_cannot_assign_to_others(company, member, worker):
    colleague = member.registered(company)

    with pytest.raises(PermissionDenied):
        services.create_task(by=worker, assignee=colleague, title="Do my job")


@pytest.mark.parametrize("why", ["unregistered", "other company"])
def test_tasks_only_go_to_registered_colleagues(company, other_company, member, manager, why):
    # Unregistered: approved but never finished onboarding.
    assignee = member(company) if why == "unregistered" else member.registered(other_company)

    with pytest.raises(DomainError):
        services.create_task(by=manager, assignee=assignee, title="Hello")


def test_unregistered_member_cannot_create_tasks(company, member):
    with pytest.raises(PermissionDenied):
        services.create_task(by=member(company), title="Anything")


@pytest.mark.parametrize("title", ["", "   "])
def test_task_needs_a_title(worker, title):
    with pytest.raises(DomainError):
        services.create_task(by=worker, title=title)


def test_deadline_must_be_in_the_future(worker):
    with pytest.raises(DomainError):
        services.create_task(by=worker, title="Too late", due_at=in_hours(-1))


# Working on it


def test_assignee_starts_and_completes(worker, django_capture_on_commit_callbacks):
    task = TaskFactory(assignee=worker)

    services.start_task(task, by=worker)
    with django_capture_on_commit_callbacks() as callbacks:
        task = services.complete_task(task, by=worker)

    assert task.status == Task.Status.DONE
    assert task.started_at is not None
    assert task.completed_at is not None
    assert len(callbacks) == 2  # the creator hears about it, and so do the team's groups


def test_only_the_assignee_works_on_a_task(manager, worker):
    task = TaskFactory(assignee=worker, created_by=manager)

    with pytest.raises(PermissionDenied):
        services.complete_task(task, by=manager)


@pytest.mark.parametrize(
    ("proof", "text", "with_photo", "ok"),
    [
        (Proof.PHOTO, "", False, False),
        (Proof.PHOTO, "here", False, False),
        (Proof.PHOTO, "", True, True),
        (Proof.TEXT, "  ", False, False),
        (Proof.TEXT, "Counted 40 bottles", False, True),
        (Proof.ANY, "", False, False),
        (Proof.ANY, "", True, True),
        (Proof.ANY, "note", False, True),
    ],
)
def test_proof_rules(worker, proof, text, with_photo, ok):
    task = TaskFactory(assignee=worker, proof=proof)
    kwargs = {"proof_text": text, "proof_photo": photo() if with_photo else None}

    if ok:
        services.complete_task(task, by=worker, **kwargs)
    else:
        with pytest.raises(DomainError):
            services.complete_task(task, by=worker, **kwargs)


def test_proof_photo_is_stored_under_an_unguessable_name(worker):
    task = TaskFactory(assignee=worker, proof=Proof.PHOTO)

    task = services.complete_task(task, by=worker, proof_photo=photo())

    assert re.fullmatch(rf"proofs/{worker.company_id}/[0-9a-f]{{32}}\.jpg", task.proof_photo.name)
    assert Image.open(task.proof_photo).format == "JPEG"


def test_a_proof_that_is_not_a_picture_is_refused_by_the_service(worker):
    task = TaskFactory(assignee=worker, proof=Proof.PHOTO)
    svg = ContentFile(b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>', "a.jpg")

    with pytest.raises(DomainError, match="picture"):
        services.complete_task(task, by=worker, proof_photo=svg)

    task.refresh_from_db()
    assert task.status == Task.Status.TODO
    assert not task.proof_photo


def test_finished_task_cannot_be_completed_again(worker):
    task = TaskFactory(assignee=worker, status=Task.Status.DONE)

    with pytest.raises(DomainError):
        services.complete_task(task, by=worker)


# Review


def test_confirmation_flow(manager, worker):
    task = TaskFactory(assignee=worker, created_by=manager, needs_confirmation=True)

    task = services.complete_task(task, by=worker)
    assert task.status == Task.Status.REVIEW

    task = services.confirm_task(task, by=manager)
    assert task.status == Task.Status.DONE
    assert task.confirmed_by == manager


def test_sent_back_task_is_open_again_with_the_reason(manager, worker):
    task = TaskFactory(
        assignee=worker, created_by=manager, needs_confirmation=True, status=Task.Status.REVIEW
    )

    task = services.return_task(task, by=manager, reason="Retake in daylight")

    assert task.status == Task.Status.RETURNED
    assert task.is_open
    assert task.comments.get().text == "Retake in daylight"
    assert Action.START in rules.allowed_actions(task, worker)


def test_sending_back_needs_a_reason(manager, worker):
    task = TaskFactory(assignee=worker, created_by=manager, status=Task.Status.REVIEW)

    with pytest.raises(DomainError):
        services.return_task(task, by=manager, reason=" ")


def test_assignee_cannot_confirm_their_own_work(company, member):
    owner = member.registered(company, "Owner")
    task = TaskFactory(assignee=owner, status=Task.Status.REVIEW)

    with pytest.raises(PermissionDenied):
        services.confirm_task(task, by=owner)


def test_confirm_permission_covers_daily_tasks(company, member, worker):
    manager = member.registered(company, "Manager")  # Manager has tasks.confirm
    task = TaskFactory(assignee=worker, kind=Task.Kind.DAILY, status=Task.Status.REVIEW)

    assert services.confirm_task(task, by=manager).status == Task.Status.DONE


def test_colleague_cannot_confirm(company, member, worker):
    colleague = member.registered(company)
    task = TaskFactory(assignee=worker, kind=Task.Kind.DAILY, status=Task.Status.REVIEW)

    with pytest.raises(PermissionDenied):
        services.confirm_task(task, by=colleague)


# Managing


def test_creator_edits_and_cancels(manager, worker):
    task = TaskFactory(assignee=worker, created_by=manager)

    task = services.update_task(task, by=manager, title="New title", due_at=in_hours(5))
    assert task.title == "New title"

    task = services.cancel_task(task, by=manager)
    assert task.status == Task.Status.CANCELLED


def test_assignee_cannot_cancel_an_assigned_task(manager, worker):
    task = TaskFactory(assignee=worker, created_by=manager)

    with pytest.raises(PermissionDenied):
        services.cancel_task(task, by=worker)


def test_only_known_fields_are_editable(worker):
    task = TaskFactory(assignee=worker)

    with pytest.raises(ValueError, match="status"):
        services.update_task(task, by=worker, status=Task.Status.DONE)


def test_checklist_is_ticked_by_the_assignee(manager, worker):
    task = services.create_task(by=manager, assignee=worker, title="Open up", checklist=["Lights"])
    item = task.checklist.get()

    services.toggle_checklist_item(item, by=worker, done=True)
    item.refresh_from_db()
    assert item.is_done

    with pytest.raises(PermissionDenied):
        services.toggle_checklist_item(item, by=manager, done=False)


def test_nobody_acts_on_another_companys_task(other_company, member, worker):
    outsider_owner = member.registered(other_company, "Owner")
    task = TaskFactory(assignee=worker, status=Task.Status.REVIEW)

    with pytest.raises(PermissionDenied):
        services.confirm_task(task, by=outsider_owner)
    with pytest.raises(PermissionDenied):
        services.cancel_task(task, by=outsider_owner)
    assert not rules.allowed_actions(task, outsider_owner)


def test_left_member_is_not_registered_any_more(company, member):
    left = member.registered(company, status=Membership.Status.LEFT)

    with pytest.raises(PermissionDenied):
        services.create_task(by=left, title="Sneaky")
