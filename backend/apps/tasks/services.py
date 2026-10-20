from datetime import timedelta
from functools import partial
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied
from django.core.files import File
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.groups import tasks as group_jobs
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.reminders.policies import policy_for
from apps.reminders.schedule import first_reminder_at
from apps.tasks import queries, rules
from apps.tasks import tasks as jobs
from apps.tasks.models import (
    Activity,
    ChecklistItem,
    Proof,
    Repeat,
    Task,
    TaskComment,
    TaskTemplate,
    Weekday,
)
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
    repeat: str = Repeat.NONE,
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
    if repeat != Repeat.NONE:
        if kind != Task.Kind.PERSONAL:
            raise DomainError(_("Repeating tasks for others are set up as daily tasks."))
        if due_at is None:
            raise DomainError(_("Pick a time for a repeating task."))

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
    _restart_reminders(task)
    task.save()
    ChecklistItem.objects.bulk_create(
        ChecklistItem(task=task, text=text.strip()[:200], order=index)
        for index, text in enumerate(checklist)
        if text.strip()
    )
    if repeat != Repeat.NONE:
        _repeat_personal_task(task, repeat)
    if kind == Task.Kind.ASSIGNED:
        _add_to_feed(Activity.Kind.ASSIGNED, task, [assignee], by)
        _audit(AuditLog.Action.TASK_ASSIGNED, task, by, assignee=str(assignee))
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
    before = {field: audit.plain(getattr(task, field)) for field in changes}
    _apply_changes(task, changes)
    if "due_at" in changes:
        _restart_reminders(task)
    task.save()
    after = {field: audit.plain(getattr(task, field)) for field in changes}
    if changed := audit.diff(before, after):
        _audit(AuditLog.Action.TASK_CHANGED, task, by, changes=changed)
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
    task.next_reminder_at = None
    task.save()
    if task.status == Task.Status.REVIEW:
        _add_to_feed(Activity.Kind.REVIEW, task, queries.reviewers(task), by)
    elif task.kind == Task.Kind.ASSIGNED:
        _add_to_feed(Activity.Kind.COMPLETED, task, [task.created_by], by)
    transaction.on_commit(partial(jobs.notify_task_completed.delay, task.pk))
    transaction.on_commit(partial(group_jobs.announce_task_done.delay, task.pk))
    return task


@transaction.atomic
def confirm_task(task: Task, *, by: Membership) -> Task:
    task = _lock(task)
    _ensure_reviewable(task, by)
    task.status = Task.Status.DONE
    task.confirmed_by = by
    task.confirmed_at = timezone.now()
    task.save()
    _add_to_feed(Activity.Kind.CONFIRMED, task, [task.assignee], by)
    _audit(AuditLog.Action.TASK_CONFIRMED, task, by)
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
    task.next_reminder_at = _resume_reminders_at(task)
    task.save()
    TaskComment.objects.create(task=task, author=by, text=reason)
    _add_to_feed(Activity.Kind.RETURNED, task, [task.assignee], by, reason)
    _audit(AuditLog.Action.TASK_RETURNED, task, by, reason=reason)
    transaction.on_commit(partial(jobs.notify_task_reviewed.delay, task.pk))
    return task


@transaction.atomic
def cancel_task(task: Task, *, by: Membership, stop_repeating: bool = False) -> Task:
    task = _lock(task)
    if not rules.can_manage(task, by):
        raise PermissionDenied(_("You can't cancel this task."))
    if task.status in (Task.Status.DONE, Task.Status.CANCELLED):
        raise DomainError(_already(task))
    task.status = Task.Status.CANCELLED
    task.next_reminder_at = None
    task.save()
    _audit(AuditLog.Action.TASK_CANCELLED, task, by)
    if stop_repeating and task.template is not None and task.template.personal:
        task.template.is_active = False
        task.template.save(update_fields=["is_active", "updated_at"])
    return task


@transaction.atomic
def hand_back_work(member: Membership) -> None:
    """Someone has left: work they were given goes back to whoever gave it, as that person's
    own task, and their daily and personal tasks are cancelled."""
    handed_back: dict[int, list[int]] = {}
    open_tasks = (
        Task.objects.select_for_update(of=("self",))
        .filter(assignee=member, status__in=Task.OPEN_STATUSES)
        .select_related("created_by")
    )
    for task in open_tasks:
        giver = task.created_by
        if (
            task.kind == Task.Kind.ASSIGNED
            and giver is not None
            and giver.pk != member.pk
            and giver.status == Membership.Status.APPROVED
        ):
            task.assignee = giver
            task.kind = Task.Kind.PERSONAL
            task.status = Task.Status.TODO
            task.needs_confirmation = False
            task.started_at = None
            task.escalate_to = None
            task.snooze_count = 0
            task.last_reminder_message_id = None
            _restart_reminders(task)
            task.save()
            handed_back.setdefault(giver.pk, []).append(task.pk)
        else:
            task.status = Task.Status.CANCELLED
            task.next_reminder_at = None
            task.save(update_fields=["status", "next_reminder_at", "updated_at"])
    for template in member.task_templates.all():
        template.assignees.remove(member)
    TaskTemplate.objects.filter(personal=True, created_by=member).update(is_active=False)
    if handed_back:
        transaction.on_commit(
            partial(jobs.notify_work_handed_back.delay, member.pk, list(handed_back.items()))
        )


@transaction.atomic
def snooze_task(task: Task, *, by: Membership) -> Task:
    """Hold off the reminders for a while, a limited number of times per task."""
    task = _lock(task)
    _ensure_assignee(task, by)
    if not task.is_open or task.due_at is None:
        raise DomainError(_("Only open tasks with a deadline can be snoozed."))
    policy = policy_for(task)
    if task.snooze_count >= policy.max_snoozes:
        raise DomainError(_("No snoozes left for this task."))
    now = timezone.now()
    task.snoozed_until = now + timedelta(minutes=policy.snooze_minutes)
    task.next_reminder_at = task.snoozed_until
    task.snooze_count += 1
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


@transaction.atomic
def add_comment(task: Task, *, by: Membership, text: str) -> TaskComment:
    text = text.strip()
    if not text:
        raise DomainError(_("A comment can't be empty."))
    comment = TaskComment.objects.create(task=task, author=by, text=text)
    _add_to_feed(Activity.Kind.COMMENTED, task, [task.assignee, task.created_by], by, text)
    return comment


@transaction.atomic
def mark_feed_read(member: Membership) -> int:
    return Activity.objects.filter(recipient=member, read_at__isnull=True).update(
        read_at=timezone.now()
    )


def _add_to_feed(
    kind: str, task: Task, recipients, actor: Membership | None, text: str = ""
) -> None:
    """Put an entry in each recipient's feed, never in the feed of whoever did it."""
    unique = {r.pk: r for r in recipients if r is not None and (actor is None or r.pk != actor.pk)}
    Activity.objects.bulk_create(
        Activity(
            company_id=task.company_id,
            recipient=recipient,
            actor=actor,
            kind=kind,
            task=task,
            text=text[:300],
        )
        for recipient in unique.values()
    )


def _repeat_personal_task(task: Task, repeat: str) -> None:
    """Make `task` the first of a series: a personal template generates the next ones."""
    due = timezone.localtime(task.due_at, ZoneInfo(task.company.timezone))
    weekdays = {
        Repeat.DAILY: list(Weekday.values),
        Repeat.WEEKDAYS: [
            Weekday.MONDAY,
            Weekday.TUESDAY,
            Weekday.WEDNESDAY,
            Weekday.THURSDAY,
            Weekday.FRIDAY,
        ],
        Repeat.WEEKLY: [due.weekday()],
    }[repeat]
    template = TaskTemplate.objects.create(
        company_id=task.company_id,
        title=task.title,
        description=task.description,
        weekdays=weekdays,
        due_time=due.time().replace(second=0, microsecond=0),
        starts_on=due.date(),
        proof=task.proof,
        personal=True,
        created_by=task.created_by,
    )
    template.assignees.add(task.assignee)
    task.template = template
    task.for_date = due.date()
    task.save(update_fields=["template", "for_date", "updated_at"])


def _audit(action: AuditLog.Action, task: Task, by: Membership, **details) -> None:
    """Management of shared work is logged; someone's own personal tasks are theirs alone."""
    if task.kind != Task.Kind.PERSONAL:
        audit.record(action, company_id=task.company_id, actor=by.user, target=task, **details)


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


def _restart_reminders(task: Task) -> None:
    """Count reminders from scratch against the (new) deadline."""
    task.reminders_sent = 0
    task.escalated_at = None
    task.snoozed_until = None
    task.next_reminder_at = first_reminder_at(task.due_at, policy_for(task), timezone.now())


def _resume_reminders_at(task: Task):
    """A task sent back is open again: past its deadline the reminders pick up where they were."""
    now = timezone.now()
    policy = policy_for(task)
    if task.due_at is None:
        return None
    if task.due_at > now:
        return first_reminder_at(task.due_at, policy, now)
    return now + timedelta(minutes=policy.repeat_every_minutes)


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
