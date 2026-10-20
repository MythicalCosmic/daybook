from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from functools import partial
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied
from django.core.files import File
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.core import uploads
from apps.core.exceptions import DomainError
from apps.groups import tasks as group_jobs
from apps.members.models import Membership, Position
from apps.members.permissions import Perm
from apps.members.scope import branch_ids
from apps.reminders.models import ReminderPolicy
from apps.reminders.policies import policy_for
from apps.reminders.schedule import first_reminder_at
from apps.tasks import queries, rules
from apps.tasks import tasks as jobs
from apps.tasks.audit_actions import TasksAction
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

EDITABLE_FIELDS = frozenset({"title", "description", "due_at", "priority", "reward"})
# One create, one bulk action: enough for a big team, small enough to stay one request.
MAX_PEOPLE = 200
MAX_BULK = 200
# "Nudge now" at most this often per task, so nobody is spammed by a nervous manager.
NUDGE_COOLDOWN = timedelta(minutes=10)
MAX_REWARD = Decimal("1000000000")


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
    reward: Decimal | None = None,
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
        _ensure_in_scope(by, assignee)
        kind = Task.Kind.ASSIGNED
    if repeat != Repeat.NONE:
        if kind != Task.Kind.PERSONAL:
            raise DomainError(_("Repeating tasks for others are set up as daily tasks."))
        if due_at is None:
            raise DomainError(_("Pick a time for a repeating task."))
    if reward is not None and kind == Task.Kind.PERSONAL:
        raise DomainError(_("A reward is for work you give to someone else."))

    task = Task(
        company_id=by.company_id,
        kind=kind,
        assignee=assignee,
        created_by=by,
        priority=priority,
        proof=proof,
        needs_confirmation=needs_confirmation,
        # Where the work happens: the assignee's branch today, kept even if they move later.
        branch_id=assignee.home_branch_id,
    )
    _apply_changes(
        task, {"title": title, "description": description, "due_at": due_at, "reward": reward}
    )
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
        if not uploads.is_sanitized(proof_photo):
            proof_photo = uploads.sanitize_image(proof_photo)  # every caller, the bot included
        task.proof_photo.save(proof_photo.name, proof_photo, save=False)
        task.proof_thumb = ""  # the old preview, if any, belongs to the old photo
        transaction.on_commit(partial(jobs.make_proof_thumb.delay, task.pk))
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


def cancel_routine_tasks(member: Membership, *, since: date) -> int:
    """Cancel the member's open daily tasks for `since` and later, e.g. when a suspension
    starts after today's were made. Their own repeating personal tasks stay. Returns how
    many were cancelled."""
    return Task.objects.filter(
        assignee=member,
        kind=Task.Kind.DAILY,
        status__in=Task.OPEN_STATUSES,
        for_date__gte=since,
    ).update(status=Task.Status.CANCELLED, next_reminder_at=None, updated_at=timezone.now())


@transaction.atomic
def resume_reminders(member: Membership) -> int:
    """Pick the reminders of the member's open tasks up again, e.g. after a suspension (the
    reminder engine stops them while someone isn't an approved member). A task whose
    reminders had all been sent stays quiet. Returns how many tasks will be reminded."""
    now = timezone.now()
    tasks = (
        Task.objects.select_for_update(of=("self",))
        .select_related("company", "reminder_policy", "template__reminder_policy")
        .filter(
            assignee=member,
            status__in=Task.OPEN_STATUSES,
            due_at__isnull=False,
            next_reminder_at__isnull=True,
        )
    )
    resumed = 0
    for task in tasks:
        if task.due_at <= now and not _reminders_left(task):
            continue
        task.next_reminder_at = _resume_reminders_at(task)
        task.save(update_fields=["next_reminder_at", "updated_at"])
        resumed += 1
    return resumed


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


# Owner console (docs/PLAN-OWNER.md §1.3, §4.5) --------------------------------------------


@transaction.atomic
def create_for_many(*, by: Membership, people: list[Membership], **task_fields) -> list[Task]:
    """The same task for each of `people`: one task per person, each with its own reminders,
    notification and audit row. Everyone must be someone `by` may give work to, or nothing is
    created."""
    unique = list({person.pk: person for person in people}.values())
    if not unique:
        raise DomainError(_("Pick at least one person."))
    if len(unique) > MAX_PEOPLE:
        raise DomainError(_("Give it to at most %(max)d people at once.") % {"max": MAX_PEOPLE})
    checklist = list(task_fields.pop("checklist", ()))
    return [
        create_task(by=by, assignee=person, checklist=checklist, **task_fields) for person in unique
    ]


@transaction.atomic
def reassign_task(task: Task, *, by: Membership, assignee: Membership) -> Task:
    """Give open work to someone else. The task keeps its branch (where the work is), and the new
    person's reminders start from scratch."""
    task = _lock(task)
    if not rules.can_reassign(task, by):
        raise PermissionDenied(_("You can't give this task to someone else."))
    if assignee.pk == task.assignee_id:
        raise DomainError(_("%(name)s already has this task.") % {"name": assignee})
    if assignee.company_id != task.company_id or not _is_registered(assignee):
        raise DomainError(_("Tasks can only go to registered members of your company."))
    _ensure_in_scope(by, assignee)
    previous = task.assignee
    task.assignee = assignee
    if task.status == Task.Status.IN_PROGRESS:
        task.status = Task.Status.TODO  # the new person hasn't started it
        task.started_at = None
    task.snooze_count = 0
    task.last_reminder_message_id = None
    task.last_nudged_at = None
    _restart_reminders(task)
    try:
        with transaction.atomic():
            task.save()
    except IntegrityError:
        raise DomainError(
            _("%(name)s already has this routine task for that day.") % {"name": assignee}
        ) from None
    _add_to_feed(Activity.Kind.ASSIGNED, task, [assignee], by)
    audit.record(
        TasksAction.REASSIGNED,
        company_id=task.company_id,
        actor=by.user,
        target=task,
        changes={"assignee": [str(previous), str(assignee)]},
    )
    transaction.on_commit(partial(jobs.notify_task_assigned.delay, task.pk))
    return task


@transaction.atomic
def nudge(task: Task, *, by: Membership) -> None:
    """Send the assignee a reminder now, from `by`, at most once per `NUDGE_COOLDOWN`."""
    task = _lock(task)
    if not rules.can_nudge(task, by):
        raise PermissionDenied(_("You can't nudge anyone about this task."))
    person = task.assignee
    if person.status != Membership.Status.APPROVED or person.user.telegram_id is None:
        raise DomainError(_("%(name)s can't get messages from the bot.") % {"name": person})
    if person.user.employee_bot_blocked_at is not None:
        raise DomainError(_("%(name)s has blocked the bot.") % {"name": person})
    now = timezone.now()
    if task.last_nudged_at is not None and now - task.last_nudged_at < NUDGE_COOLDOWN:
        raise DomainError(_("Nudged a few minutes ago. Give them a moment."))
    task.last_nudged_at = now
    task.save(update_fields=["last_nudged_at", "updated_at"])
    audit.record(TasksAction.NUDGED, company_id=task.company_id, actor=by.user, target=task)
    transaction.on_commit(partial(jobs.notify_nudge.delay, task.pk, by.pk))


@transaction.atomic
def move_task(task: Task, *, by: Membership, to: str, reason: str = "") -> Task:
    """A card dragged to another board column: the one transition that column means for it."""
    if to not in rules.board_moves(task, by):
        raise DomainError(_("This card can't go there."))
    if to == rules.Column.IN_PROGRESS:
        return start_task(task, by=by)
    if to == rules.Column.RETURNED:
        return return_task(task, by=by, reason=reason)
    if to == rules.Column.DONE and task.status == Task.Status.REVIEW:
        return confirm_task(task, by=by)
    return complete_task(task, by=by)


@dataclass(frozen=True)
class BulkResult:
    id: int
    ok: bool
    error: str = ""


class BulkAction:
    REASSIGN = "reassign"
    RESCHEDULE = "reschedule"
    PRIORITY = "priority"
    CANCEL = "cancel"
    CONFIRM = "confirm"
    NUDGE = "nudge"

    ALL = (REASSIGN, RESCHEDULE, PRIORITY, CANCEL, CONFIRM, NUDGE)


def bulk(*, by: Membership, ids, action: str, payload: dict) -> list[BulkResult]:
    """Apply one action to many tasks, each on its own: one refusal never stops the others.
    Each change is audited by the service it goes through. `payload` holds what the action
    needs: `assignee` (a Membership), `due_at` (a moment) or `shift_days` (int), `priority`."""
    if action not in BulkAction.ALL:
        raise DomainError(_("Unknown action."))
    ids = list(dict.fromkeys(int(pk) for pk in ids))
    if not ids:
        raise DomainError(_("Pick at least one task."))
    if len(ids) > MAX_BULK:
        raise DomainError(_("Pick at most %(max)d tasks at once.") % {"max": MAX_BULK})
    found = {task.pk: task for task in queries.visible_tasks(by).filter(pk__in=ids)}
    results = []
    for pk in ids:
        task = found.get(pk)
        if task is None:
            results.append(BulkResult(pk, False, _("Not found.")))
            continue
        try:
            with transaction.atomic():
                _bulk_one(task, by=by, action=action, payload=payload)
        except (DomainError, PermissionDenied, ValueError) as exc:
            results.append(BulkResult(pk, False, str(exc)))
        else:
            results.append(BulkResult(pk, True))
    return results


def _bulk_one(task: Task, *, by: Membership, action: str, payload: dict) -> None:
    match action:
        case BulkAction.REASSIGN:
            reassign_task(task, by=by, assignee=payload["assignee"])
        case BulkAction.RESCHEDULE:
            if "due_at" in payload:
                due_at = payload["due_at"]
            else:
                if task.due_at is None:
                    raise DomainError(_("This task has no deadline to move."))
                due_at = task.due_at + timedelta(days=int(payload["shift_days"]))
            update_task(task, by=by, due_at=due_at)
        case BulkAction.PRIORITY:
            update_task(task, by=by, priority=payload["priority"])
        case BulkAction.CANCEL:
            cancel_task(task, by=by)
        case BulkAction.CONFIRM:
            confirm_task(task, by=by)
        case BulkAction.NUDGE:
            nudge(task, by=by)


# Routines (daily task templates) and onboarding templates ---------------------------------

TEMPLATE_FIELDS = frozenset(
    {
        "title",
        "description",
        "weekdays",
        "due_time",
        "starts_on",
        "proof",
        "needs_confirmation",
        "is_active",
        "reminder_policy",
        "escalate_to",
        "branch",
        "checklist",
        "onboarding",
        "due_after_days",
        "assignees",
        "positions",
    }
)


@transaction.atomic
def create_template(*, by: Membership, **fields) -> TaskTemplate:
    """A routine (made every day it's due, for everyone it names) or, with `onboarding=True`,
    an onboarding template (given once to each new person it names)."""
    _ensure_may_plan(by)
    if unknown := fields.keys() - TEMPLATE_FIELDS:
        raise ValueError(f"Not a template field: {sorted(unknown)}")
    assignees = list(fields.pop("assignees", ()))
    positions = list(fields.pop("positions", ()))
    template = TaskTemplate(company_id=by.company_id, created_by=by)
    _apply_template(template, by, fields)
    template.save()
    _set_template_people(template, by, assignees, positions)
    audit.record(
        AuditLog.Action.TEMPLATE_CREATED,
        company_id=template.company_id,
        actor=by.user,
        target=template,
    )
    return template


@transaction.atomic
def update_template(template: TaskTemplate, *, by: Membership, **fields) -> TaskTemplate:
    _ensure_may_plan(by)
    if unknown := fields.keys() - TEMPLATE_FIELDS:
        raise ValueError(f"Not a template field: {sorted(unknown)}")
    template = TaskTemplate.objects.select_for_update().get(pk=template.pk)
    _ensure_template_in_scope(template, by)
    before = audit.snapshot(template)
    assignees = fields.pop("assignees", None)
    positions = fields.pop("positions", None)
    _apply_template(template, by, fields)
    template.save()
    if assignees is not None or positions is not None:
        _set_template_people(
            template,
            by,
            template.assignees.all() if assignees is None else assignees,
            template.positions.all() if positions is None else positions,
        )
    if changes := audit.diff(before, audit.snapshot(template)):
        audit.record(
            AuditLog.Action.TEMPLATE_CHANGED,
            company_id=template.company_id,
            actor=by.user,
            target=template,
            changes=changes,
        )
    return template


@transaction.atomic
def delete_template(template: TaskTemplate, *, by: Membership) -> None:
    """Remove a routine. Tasks it already made stay (they lose the link)."""
    _ensure_may_plan(by)
    _ensure_template_in_scope(template, by)
    audit.record(
        AuditLog.Action.TEMPLATE_DELETED,
        company_id=template.company_id,
        actor=by.user,
        target=template,
    )
    template.delete()


def _ensure_may_plan(by: Membership) -> None:
    if not by.has_perm(Perm.TASKS_TEMPLATES):
        raise PermissionDenied(_("You can't change routines."))


def _ensure_template_in_scope(template: TaskTemplate, by: Membership) -> None:
    scope = branch_ids(by)
    if scope is not None and template.branch_id not in scope:
        raise PermissionDenied(_("This routine belongs to a branch you don't manage."))


def _apply_template(template: TaskTemplate, by: Membership, fields: dict) -> None:
    if "title" in fields:
        title = (fields.pop("title") or "").strip()
        if not title:
            raise DomainError(_("Give the routine a title."))
        template.title = title[:200]
    if "description" in fields:
        template.description = (fields.pop("description") or "").strip()
    if "weekdays" in fields:
        weekdays = sorted({int(day) for day in fields.pop("weekdays")})
        if not weekdays or any(day not in Weekday.values for day in weekdays):
            raise DomainError(_("Pick at least one day of the week."))
        template.weekdays = weekdays
    if "checklist" in fields:
        template.checklist = [
            text.strip()[:200] for text in fields.pop("checklist") or () if text.strip()
        ][:50]
    if "due_after_days" in fields:
        days = int(fields.pop("due_after_days"))
        if not 0 <= days <= 90:
            raise DomainError(_("Pick between 0 and 90 days."))
        template.due_after_days = days
    for name in ("branch", "reminder_policy", "escalate_to"):
        if name in fields:
            _check_same_company(fields[name], by)
    scope = branch_ids(by)
    branch = fields.get("branch", template.branch if template.pk else None)
    if scope is not None and (branch is None or branch.pk not in scope):
        raise DomainError(_("Pick one of your branches for this routine."))
    escalate_to = fields.get("escalate_to")
    if escalate_to is not None and escalate_to.status != Membership.Status.APPROVED:
        raise DomainError(_("Pick someone who works here."))
    for name, value in fields.items():
        setattr(template, name, value)
    if template.due_time is None:
        raise DomainError(_("Pick the time it's due."))
    if template.onboarding:
        template.personal = False


def _set_template_people(template, by, assignees, positions) -> None:
    assignees, positions = list(assignees), list(positions)
    for person in assignees:
        _check_same_company(person, by)
        if person.status != Membership.Status.APPROVED:
            raise DomainError(_("%(name)s doesn't work here any more.") % {"name": person})
        _ensure_in_scope(by, person)
    for position in positions:
        _check_same_company(position, by)
    if not template.onboarding and not assignees and not positions:
        raise DomainError(_("Pick who does it: people or positions."))
    template.assignees.set(assignees)
    template.positions.set(positions)


def _check_same_company(value: Membership | Position | ReminderPolicy | None, by) -> None:
    """Branches, people, positions and policies picked for a routine are this company's."""
    if value is not None and value.company_id != by.company_id:
        raise DomainError(_("That isn't part of your company."))


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
    if "reward" in changes:
        reward = changes["reward"]
        if reward is not None:
            reward = Decimal(reward)
            if task.kind == Task.Kind.PERSONAL:
                raise DomainError(_("A reward is for work you give to someone else."))
            if reward <= 0 or reward >= MAX_REWARD:
                raise DomainError(_("A reward must be a positive amount."))
            reward = reward.quantize(Decimal("0.01"))
        task.reward = reward


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


def _reminders_left(task: Task) -> bool:
    """Whether a late task still has reminders to come (personal tasks get one)."""
    if task.kind == Task.Kind.PERSONAL:
        return task.reminders_sent == 0
    policy = policy_for(task)
    return policy.max_reminders == 0 or task.reminders_sent < policy.max_reminders


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


def in_scope(by: Membership, person: Membership) -> bool:
    """Whether `person` works in a branch `by` may see (docs/PLAN-OWNER.md §2.6): every branch,
    or their home branch or one of their branches is in `by`'s scope. Yourself always."""
    if person.pk == by.pk:
        return True
    scope = branch_ids(by)
    if scope is None:
        return True
    if person.home_branch_id in scope:
        return True
    return person.branches.filter(pk__in=scope).exists()


def _ensure_in_scope(by: Membership, person: Membership) -> None:
    if not in_scope(by, person):
        raise DomainError(_("%(name)s works in a branch you don't manage.") % {"name": person})


def _ensure_registered(member: Membership) -> None:
    if not _is_registered(member):
        raise PermissionDenied(_("Finish registration first."))
