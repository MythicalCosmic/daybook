from functools import partial

from django.core.exceptions import PermissionDenied
from django.core.files import File
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.tasks import rules
from apps.tasks import tasks as jobs
from apps.tasks.models import ChecklistItem, Proof, Task, TaskComment
from apps.tasks.queries import TASK_RELATIONS

EDITABLE_FIELDS = frozenset({"title", "description", "due_at", "priority"})


@transaction.atomic
def create_task(
    *,
    by: Membership,
    title: str,
    description: str = "",
    assignee: Membership | None = None,
    due_at=None,
    priority: str = Task.Priority.NORMAL,
    proof: str = Proof.NONE,
    needs_confirmation: bool = False,
    checklist: list[str] = (),
) -> Task:
    _ensure_registered(by)
    assignee = assignee or by
    if assignee.pk == by.pk:
        kind = Task.Kind.PERSONAL
        needs_confirmation = False
    else:
        if not by.has_perm(Perm.TASKS_ASSIGN):
            raise PermissionDenied(_("You can't assign tasks to others."))
        if assignee.company_id != by.company_id or not _is_registered(assignee):
            raise DomainError(_("Tasks can only go to registered members of your company."))
        kind = Task.Kind.ASSIGNED

    task = Task(
        company_id=by.company_id,
        kind=kind,
        assignee=assignee,
        created_by=by,
        priority=priority,
        proof=proof,
        needs_confirmation=needs_confirmation,
    )
    _apply_changes(task, {"title": title, "description": description, "due_at": due_at})
    task.save()
    ChecklistItem.objects.bulk_create(
        ChecklistItem(task=task, text=text.strip()[:200], order=index)
        for index, text in enumerate(checklist)
        if text.strip()
    )
    if kind == Task.Kind.ASSIGNED:
        transaction.on_commit(partial(jobs.notify_task_assigned.delay, task.pk))
    return task


@transaction.atomic
def update_task(task: Task, *, by: Membership, **changes) -> Task:
    if unknown := changes.keys() - EDITABLE_FIELDS:
        raise ValueError(f"Not editable: {sorted(unknown)}")
    task = _lock(task)
    if not rules.can_manage(task, by):
        raise PermissionDenied(_("You can't change this task."))
    if not task.is_open:
        raise DomainError(_("Only open tasks can be changed."))
    _apply_changes(task, changes)
    task.save()
    return task


@transaction.atomic
def start_task(task: Task, *, by: Membership) -> Task:
    task = _lock(task)
    _ensure_assignee(task, by)
    if task.status not in (Task.Status.TODO, Task.Status.RETURNED):
        raise DomainError(_("This task has already been started."))
    task.status = Task.Status.IN_PROGRESS
    task.started_at = timezone.now()
    task.save()
    return task


@transaction.atomic
def complete_task(
    task: Task, *, by: Membership, proof_text: str = "", proof_photo: File | None = None
) -> Task:
    task = _lock(task)
    _ensure_assignee(task, by)
    if not task.is_open:
        raise DomainError(_already(task))
    proof_text = proof_text.strip()
    if problem := _missing_proof(task.proof, proof_text, proof_photo):
        raise DomainError(problem)

    task.proof_text = proof_text
    if proof_photo is not None:
        task.proof_photo.save(proof_photo.name or "proof.jpg", proof_photo, save=False)
    task.completed_at = timezone.now()
    task.status = Task.Status.REVIEW if task.needs_confirmation else Task.Status.DONE
    task.save()
    transaction.on_commit(partial(jobs.notify_task_completed.delay, task.pk))
    return task


@transaction.atomic
def confirm_task(task: Task, *, by: Membership) -> Task:
    task = _lock(task)
    _ensure_reviewable(task, by)
    task.status = Task.Status.DONE
    task.confirmed_by = by
    task.confirmed_at = timezone.now()
    task.save()
    transaction.on_commit(partial(jobs.notify_task_reviewed.delay, task.pk))
    return task


@transaction.atomic
def return_task(task: Task, *, by: Membership, reason: str) -> Task:
    task = _lock(task)
    _ensure_reviewable(task, by)
    reason = reason.strip()
    if not reason:
        raise DomainError(_("Say what needs to be fixed."))
    task.status = Task.Status.RETURNED
    task.completed_at = None
    task.save()
    TaskComment.objects.create(task=task, author=by, text=reason)
    transaction.on_commit(partial(jobs.notify_task_reviewed.delay, task.pk))
    return task


@transaction.atomic
def cancel_task(task: Task, *, by: Membership) -> Task:
    task = _lock(task)
    if not rules.can_manage(task, by):
        raise PermissionDenied(_("You can't cancel this task."))
    if task.status in (Task.Status.DONE, Task.Status.CANCELLED):
        raise DomainError(_already(task))
    task.status = Task.Status.CANCELLED
    task.save()
    return task


@transaction.atomic
def toggle_checklist_item(item: ChecklistItem, *, by: Membership, done: bool) -> ChecklistItem:
    task = _lock(item.task)
    _ensure_assignee(task, by)
    if not task.is_open:
        raise DomainError(_already(task))
    item.is_done = done
    item.save(update_fields=["is_done"])
    return item


def add_comment(task: Task, *, by: Membership, text: str) -> TaskComment:
    text = text.strip()
    if not text:
        raise DomainError(_("A comment can't be empty."))
    return TaskComment.objects.create(task=task, author=by, text=text)


def _apply_changes(task: Task, changes: dict) -> None:
    if "title" in changes:
        title = changes["title"].strip()
        if not title:
            raise DomainError(_("Give the task a title."))
        task.title = title
    if "description" in changes:
        task.description = changes["description"].strip()
    if "due_at" in changes:
        due_at = changes["due_at"]
        if due_at is not None and due_at <= timezone.now():
            raise DomainError(_("The deadline must be in the future."))
        task.due_at = due_at
    if "priority" in changes:
        task.priority = changes["priority"]


def _missing_proof(proof: str, text: str, photo: File | None) -> str | None:
    if proof == Proof.PHOTO and photo is None:
        return _("Attach a photo to complete this task.")
    if proof == Proof.TEXT and not text:
        return _("Write a short report to complete this task.")
    if proof == Proof.ANY and photo is None and not text:
        return _("Attach a photo or write a short report to complete this task.")
    return None


def _lock(task: Task) -> Task:
    return (
        Task.objects.select_for_update(of=("self",)).select_related(*TASK_RELATIONS).get(pk=task.pk)
    )


def _already(task: Task) -> str:
    return _("This task is already %(status)s.") % {"status": task.get_status_display().lower()}


def _ensure_assignee(task: Task, by: Membership) -> None:
    if not rules.is_assignee(task, by):
        raise PermissionDenied(_("Only the person this task is for can do that."))


def _ensure_reviewable(task: Task, by: Membership) -> None:
    if not rules.can_review(task, by):
        raise PermissionDenied(_("You can't confirm this task."))
    if task.status != Task.Status.REVIEW:
        raise DomainError(_("This task isn't waiting for confirmation."))


def _is_registered(member: Membership) -> bool:
    return member.status == Membership.Status.APPROVED and member.is_onboarded


def _ensure_registered(member: Membership) -> None:
    if not _is_registered(member):
        raise PermissionDenied(_("Finish registration first."))
