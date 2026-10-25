from dataclasses import dataclass
from datetime import date, datetime, timedelta
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
from apps.console import pulse
from apps.core import uploads
from apps.core.exceptions import DomainError
from apps.groups import tasks as group_jobs
from apps.inbox import services as inbox
from apps.members.models import Membership, Position
from apps.members.permissions import Perm
from apps.members.scope import allows, branch_ids
from apps.reminders.models import ReminderPolicy
from apps.reminders.policies import escalation_recipients, policy_for
from apps.reminders.schedule import first_reminder_at
from apps.tasks import dates, generation, queries, rules
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
from apps.timeoff.queries import is_holiday

EDITABLE_FIELDS = frozenset({"title", "description", "due_at", "priority", "reward"})
# One create, one bulk action: enough for a big team, small enough to stay one request.
MAX_PEOPLE = 200
MAX_BULK = 200
# "Nudge now" at most this often per task, so nobody is spammed by a nervous manager.
NUDGE_COOLDOWN = timedelta(minutes=10)
MAX_REWARD = Decimal("1000000000")
# Done can be undone this long (research R2 T38); news of it waits as long, so an undone Done
# never reaches the group or the reviewer.
UNDO_WINDOW = rules.UNDO_WINDOW
# Snooze choices besides the policy's own length ("15m" and "1h" hold the reminders; the
# deadline stays). "tomorrow_morning" moves someone's own task instead.
SNOOZE_LENGTHS = {"15m": timedelta(minutes=15), "1h": timedelta(hours=1)}
TOMORROW_MORNING = "tomorrow_morning"
SNOOZE_PRESETS = (*SNOOZE_LENGTHS, TOMORROW_MORNING)
# More time asked for a task: at most this far past the current deadline.
MAX_EXTENSION = timedelta(days=30)
MAX_MENTIONS = 20


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
    project=None,
    project_list=None,
    milestone=None,
) -> Task:
    """A new task. With `project` (and optionally one of its lists and milestones) the task is
    a card on that board: shared work even when someone gives it to themselves, and
    `apps.projects` gives it its number and board place when it is saved (the first list when
    no list is given). The board's own rights (who may add cards) are the caller's to check;
    here a project only widens who may hand out the work (`_ensure_may_assign`)."""
    _ensure_registered(by)
    assignee = assignee or by
    _check_project(by, project, project_list, milestone)
    for_self = assignee.pk == by.pk
    if for_self:
        needs_confirmation = False
    else:
        _ensure_may_assign(by, assignee, project)
    # Board work is shared work: a card someone gives themselves is still the project's.
    kind = Task.Kind.PERSONAL if for_self and project is None else Task.Kind.ASSIGNED
    if repeat != Repeat.NONE:
        if kind != Task.Kind.PERSONAL:
            raise DomainError(_("Repeating tasks for others are set up as daily tasks."))
        if due_at is None:
            raise DomainError(_("Pick a time for a repeating task."))
    if reward is not None and for_self:
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
        project=project,
        project_list=project_list,
        milestone=milestone,
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
    if not for_self:
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
    old_due = task.due_at
    _apply_changes(task, changes)
    moved = "due_at" in changes and task.due_at != old_due
    if "due_at" in changes:
        _restart_reminders(task)
    if moved:
        # A new deadline answers "can't do it" and "need more time" alike.
        _clear_blocker(task, by, outcome=_("New deadline set"))
        _clear_extension(task, by, outcome=_("New deadline set"))
    task.save()
    after = {field: audit.plain(getattr(task, field)) for field in changes}
    if changed := audit.diff(before, after):
        _audit(AuditLog.Action.TASK_CHANGED, task, by, changes=changed)
    if moved and by.pk != task.assignee_id:
        old = old_due.isoformat() if old_due else None
        transaction.on_commit(partial(jobs.notify_due_changed.delay, task.pk, old, by.pk))
    _refresh_copies(task)
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
    _refresh_copies(task)
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
    _clear_blocker(task, by, outcome=_("Done"))
    _clear_extension(task, by, outcome=_("Done"))
    task.save()
    if task.status == Task.Status.REVIEW:
        _add_to_feed(Activity.Kind.REVIEW, task, queries.reviewers(task), by)
    elif task.kind == Task.Kind.ASSIGNED:
        _add_to_feed(Activity.Kind.COMPLETED, task, [task.created_by], by)
    # The reviewer's push and the group's post wait out the undo window, and only go if this
    # very completion still stands then (`reopen_task`).
    stamp = task.completed_at.isoformat()
    wait = int(UNDO_WINDOW.total_seconds())
    transaction.on_commit(
        partial(jobs.notify_task_completed.apply_async, (task.pk, stamp), countdown=wait)
    )
    transaction.on_commit(
        partial(group_jobs.announce_task_done.apply_async, (task.pk, stamp), countdown=wait)
    )
    _refresh_copies(task)
    return task


@transaction.atomic
def reopen_task(task: Task, *, by: Membership) -> Task:
    """Undo a Done (research R2 T38): only the person who did it, within `UNDO_WINDOW`, while
    nobody has confirmed it. The task is open again as it was (in progress once started), the
    proof stays, reminders pick up again, and the feed entries the Done made go away; the
    delayed pushes see it's open and stay quiet."""
    task = _lock(task)
    _ensure_assignee(task, by)
    if task.status not in (Task.Status.DONE, Task.Status.REVIEW) or task.completed_at is None:
        raise DomainError(_("This task isn't finished, so there's nothing to undo."))
    if task.confirmed_at is not None:
        raise DomainError(_("This task was already accepted, so it can't be undone."))
    if timezone.now() - task.completed_at > UNDO_WINDOW:
        raise DomainError(_("Too late to undo: it's been more than a minute."))
    completed_at = task.completed_at
    task.status = Task.Status.IN_PROGRESS if task.started_at else Task.Status.TODO
    task.completed_at = None
    task.next_reminder_at = _resume_reminders_at(task)
    task.save()
    Activity.objects.filter(
        task=task,
        actor=by,
        kind__in=(Activity.Kind.REVIEW, Activity.Kind.COMPLETED),
        created_at__gte=completed_at,
    ).delete()
    _audit(TasksAction.REOPENED, task, by)
    _refresh_copies(task)
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
    _refresh_copies(task)
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
    _refresh_copies(task)
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
    _clear_blocker(task, by, outcome=_("Task cancelled"))
    _clear_extension(task, by, outcome=_("Task cancelled"))
    task.save()
    _audit(AuditLog.Action.TASK_CANCELLED, task, by)
    if stop_repeating and task.template is not None and task.template.personal:
        task.template.is_active = False
        task.template.save(update_fields=["is_active", "updated_at"])
    if by.pk != task.assignee_id:
        transaction.on_commit(partial(jobs.notify_task_cancelled.delay, task.pk, by.pk))
    _refresh_copies(task)
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
            task.blocker, task.blocker_note, task.blocked_at = "", "", None
            task.extension_until, task.extension_note, task.extension_asked_at = None, "", None
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
            blocked_at__isnull=True,  # "can't do it" keeps them quiet until someone decides
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
def snooze_task(task: Task, *, by: Membership, preset: str | None = None) -> Task:
    """Hold off the reminders for a while, a limited number of times per task: the policy's own
    length, or a preset ("15m", "1h"). The deadline stays where it is (research R2 T15).

    "tomorrow_morning" is for someone's own task: it moves the deadline to 09:00 of the coming
    morning in the company's time, and doesn't use up a snooze."""
    task = _lock(task)
    _ensure_assignee(task, by)
    if not task.is_open or task.due_at is None:
        raise DomainError(_("Only open tasks with a deadline can be snoozed."))
    if preset is not None and preset not in SNOOZE_PRESETS:
        raise DomainError(_("Pick 15 minutes, an hour or tomorrow morning."))
    if task.blocked_at is not None:
        raise DomainError(_("Reminders are already paused: the task is waiting for a decision."))
    now = timezone.now()
    if preset == TOMORROW_MORNING:
        if task.kind != Task.Kind.PERSONAL:
            raise DomainError(_("Only your own tasks move to tomorrow. Ask for more time instead."))
        local_now = timezone.localtime(now, ZoneInfo(task.company.timezone))
        task.due_at = dates.tomorrow_morning(local_now)
        _restart_reminders(task)
        task.save()
        return task
    policy = policy_for(task)
    if task.snooze_count >= policy.max_snoozes:
        raise DomainError(_("No snoozes left for this task."))
    length = SNOOZE_LENGTHS[preset] if preset else timedelta(minutes=policy.snooze_minutes)
    task.snoozed_until = now + length
    upcoming = task.next_reminder_at
    # A reminder already planned for later than the snooze (a heads-up ahead of the deadline,
    # say) stays where it is; the snooze never brings one forward.
    if upcoming is None or upcoming <= task.snoozed_until:
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
def add_comment(
    task: Task, *, by: Membership, text: str, mentions: list[int] | tuple[int, ...] = ()
) -> TaskComment:
    """A comment, and it reaches people (research R2 T33/T34): the assignee, whoever gave the
    task and everyone `mentions` names (membership ids) get a bot message and a feed entry;
    the author never does. A mention must be someone on the task or working in its branch."""
    text = text.strip()
    if not text:
        raise DomainError(_("A comment can't be empty."))
    mentioned = _mentioned(task, by, mentions)
    comment = TaskComment.objects.create(task=task, author=by, text=text)
    recipients = [task.assignee, task.created_by, *mentioned]
    _add_to_feed(Activity.Kind.COMMENTED, task, recipients, by, text)
    transaction.on_commit(
        partial(jobs.notify_comment.delay, comment.pk, [person.pk for person in mentioned])
    )
    return comment


def mark_seen(task: Task, *, by: Membership) -> bool:
    """The first time the assignee opens their task (the app's task screen, the bot's card):
    `seen_at`, so whoever gave it sees "Seen 09:12" (research R2 T36). True when it was new."""
    if task.seen_at is not None or not rules.is_assignee(task, by):
        return False
    now = timezone.now()
    if not Task.objects.filter(pk=task.pk, seen_at__isnull=True).update(seen_at=now):
        return False
    task.seen_at = now
    transaction.on_commit(partial(pulse.bump, task.company_id, "tasks.tasks"))
    return True


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
    if assignee.pk != by.pk:
        # The same rule as handing it out: a lead moves a card only between their project's
        # people, someone with tasks.assign within their branches (or the project's people).
        _ensure_may_assign(by, assignee, task.project if task.project_id else None)
    return _reassign(task, by=by, assignee=assignee)


def _reassign(task: Task, *, by: Membership, assignee: Membership) -> Task:
    """The change itself, on a locked task whose new assignee was checked by the caller."""
    previous = task.assignee
    task.assignee = assignee
    if task.status == Task.Status.IN_PROGRESS:
        task.status = Task.Status.TODO  # the new person hasn't started it
        task.started_at = None
    task.snooze_count = 0
    task.last_reminder_message_id = None
    task.last_nudged_at = None
    task.seen_at = None  # the new person hasn't seen it yet
    _clear_blocker(task, by, outcome=_("Given to someone else"))
    _clear_extension(task, by, outcome=_("Given to someone else"))
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
    if previous.pk != by.pk:
        # The person who loses it hears so, and stops working to it (audit X-6).
        transaction.on_commit(
            partial(jobs.notify_task_taken_away.delay, task.pk, previous.pk, by.pk)
        )
    _refresh_copies(task)
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


# "Can't do it" and "Need more time" (research R2 T57, T17) --------------------------------


class BlockerAction:
    REASSIGN = "reassign"
    NEW_DUE = "new_due"
    CANCEL = "cancel"

    ALL = (REASSIGN, NEW_DUE, CANCEL)


@transaction.atomic
def report_blocker(task: Task, *, by: Membership, reason_code: str, note: str = "") -> Task:
    """The assignee can't do it (out of stock, no access, something broken, not theirs…): the
    reminders pause and whoever gave it (or its escalation contact) hears, with the choice to
    give it to someone else, set a new time or cancel it (`resolve_blocker`)."""
    task = _lock(task)
    _ensure_assignee(task, by)
    if not task.is_open:
        raise DomainError(_already(task))
    if task.kind == Task.Kind.PERSONAL:
        raise DomainError(_("This is your own task: change its deadline or cancel it instead."))
    if reason_code not in Task.Blocker.values:
        raise DomainError(_("Pick a reason."))
    note = (note or "").strip()[:300]
    if reason_code == Task.Blocker.OTHER and not note:
        raise DomainError(_("Write what's in the way."))
    task.blocker, task.blocker_note, task.blocked_at = reason_code, note, timezone.now()
    task.next_reminder_at = None
    task.save()
    _audit(TasksAction.BLOCKED, task, by, reason=reason_code)
    givers = [person for person in escalation_recipients(task) if person.pk != by.pk]
    if givers:
        reason = Task.Blocker(reason_code)
        inbox.notify(
            givers,
            "tasks.blocked",
            title=lambda person: _("%(name)s can't do a task") % {"name": by},
            body=lambda person: _blocker_body(task, reason, note),
            url=f"/c/{task.company_id}/tasks?task={task.pk}",
            app_screen=f"task:{task.pk}",
            target=task,
            actor=by,
            severity="warning",
        )
        transaction.on_commit(
            partial(jobs.notify_blocked.delay, task.pk, [person.pk for person in givers])
        )
    _refresh_copies(task)
    return task


@transaction.atomic
def resolve_blocker(
    task: Task,
    *,
    by: Membership,
    action: str,
    assignee_id: int | None = None,
    due_at: datetime | None = None,
) -> Task:
    """Answer a "can't do it": give it to someone else (`assignee_id`), set a new deadline
    (`due_at`) or cancel it. The giver may, and so may whoever holds tasks.assign or
    tasks.confirm for the task's branch. The person who reported it hears the answer."""
    task = _lock(task)
    if action not in BlockerAction.ALL:
        raise DomainError(_("Pick: someone else, a new time, or cancel."))
    if task.blocked_at is None or not task.is_open:
        raise DomainError(_("This task isn't waiting for a decision."))
    _ensure_may_decide(task, by)
    reporter = task.assignee
    if action == BlockerAction.REASSIGN:
        person = _colleague(task, by, assignee_id)
        task = _reassign(task, by=by, assignee=person)
    elif action == BlockerAction.NEW_DUE:
        if due_at is None:
            raise DomainError(_("Pick the new deadline."))
        old_due = task.due_at
        _apply_changes(task, {"due_at": due_at})
        _restart_reminders(task)
        _clear_blocker(task, by, outcome=_("New deadline set"))
        task.save()
        changes = {"due_at": [audit.plain(old_due), audit.plain(task.due_at)]}
        _audit(AuditLog.Action.TASK_CHANGED, task, by, changes=changes)
    else:
        task.status = Task.Status.CANCELLED
        task.next_reminder_at = None
        _clear_blocker(task, by, outcome=_("Task cancelled"))
        _clear_extension(task, by, outcome=_("Task cancelled"))
        task.save()
        _audit(AuditLog.Action.TASK_CANCELLED, task, by)
    _audit(TasksAction.UNBLOCKED, task, by, reason=action)
    transaction.on_commit(
        partial(jobs.notify_blocker_resolved.delay, task.pk, action, by.pk, reporter.pk)
    )
    _refresh_copies(task)
    return task


@transaction.atomic
def request_extension(task: Task, *, by: Membership, until: datetime, note: str = "") -> Task:
    """The assignee asks for a later deadline; whoever gave it approves or declines in one tap
    (bot and inbox, `decide_extension`). Reminders go on meanwhile: the deadline still holds."""
    task = _lock(task)
    _ensure_assignee(task, by)
    if not task.is_open or task.due_at is None:
        raise DomainError(_("Only open tasks with a deadline can get more time."))
    if task.kind == Task.Kind.PERSONAL:
        raise DomainError(_("This is your own task: just change its deadline."))
    now = timezone.now()
    if until <= max(task.due_at, now):
        raise DomainError(_("Pick a time later than the current deadline."))
    if until - task.due_at > MAX_EXTENSION:
        raise DomainError(_("Ask for at most 30 days more."))
    note = (note or "").strip()[:300]
    task.extension_until, task.extension_note, task.extension_asked_at = until, note, now
    task.save()
    asked = {"due_at": [audit.plain(task.due_at), audit.plain(until)]}
    _audit(TasksAction.EXTENSION_ASKED, task, by, changes=asked)
    # One open request at a time: an earlier one is closed in the inbox first.
    inbox.settle(task, outcome=_("Asked again"), by=by, kind="tasks.extension")
    givers = [person for person in escalation_recipients(task) if person.pk != by.pk]
    if givers:
        inbox.notify(
            givers,
            "tasks.extension",
            title=lambda person: _("%(name)s asks for more time") % {"name": by},
            body=lambda person: _extension_body(task, person, now),
            url=f"/c/{task.company_id}/tasks?task={task.pk}",
            app_screen=f"task:{task.pk}",
            target=task,
            actor=by,
            actions=[
                inbox.NotificationAction("approve", _("Give more time"), "primary"),
                inbox.NotificationAction("decline", _("Keep the deadline")),
            ],
        )
    _refresh_copies(task)
    return task


@transaction.atomic
def decide_extension(task: Task, *, by: Membership, approve: bool) -> Task:
    """Approve (the deadline moves to what was asked, reminders start over) or decline (it
    stays). The giver may, and so may whoever holds tasks.assign or tasks.confirm for the task's
    branch. The assignee hears the answer."""
    task = _lock(task)
    if task.extension_until is None or not task.is_open:
        raise DomainError(_("Nobody is waiting for more time on this task."))
    _ensure_may_decide(task, by)
    until, old_due = task.extension_until, task.due_at
    if approve:
        if until <= timezone.now():
            raise DomainError(_("The time asked for has already passed. Set a new deadline."))
        task.due_at = until
        _restart_reminders(task)
    outcome = _("More time given") if approve else _("Deadline kept")
    _clear_extension(task, by, outcome=outcome)
    if approve:
        _clear_blocker(task, by, outcome=_("New deadline set"))
    task.save()
    _audit(
        TasksAction.EXTENSION_DECIDED,
        task,
        by,
        reason="approved" if approve else "declined",
        changes={"due_at": [audit.plain(old_due), audit.plain(task.due_at)]} if approve else {},
    )
    transaction.on_commit(
        partial(jobs.notify_extension_decided.delay, task.pk, approve, by.pk, until.isoformat())
    )
    _refresh_copies(task)
    return task


def can_decide(task: Task, member: Membership) -> bool:
    """Who answers a "can't do it" or a "need more time": whoever gave the task, its escalation
    contact, or someone holding tasks.assign or tasks.confirm whose branch scope covers it."""
    if task.company_id != member.company_id or rules.is_assignee(task, member):
        return False
    if member.status != Membership.Status.APPROVED:
        return False
    if task.created_by_id == member.pk or task.escalate_to_id == member.pk:
        return True
    holds = member.has_perm(Perm.TASKS_ASSIGN) or member.has_perm(Perm.TASKS_CONFIRM)
    return holds and allows(branch_ids(member), task.branch_id)


def _ensure_may_decide(task: Task, by: Membership) -> None:
    if not can_decide(task, by):
        raise PermissionDenied(_("Only whoever gave the task, or a manager, can decide."))


def _colleague(task: Task, by: Membership, member_id: int | None) -> Membership:
    """The person a blocked task goes to: registered in the task's company, inside the deciding
    person's scope, not the one who couldn't do it."""
    if member_id is None:
        raise DomainError(_("Pick who gets it."))
    person = (
        Membership.objects.for_company(task.company_id)
        .select_related("user", "company", "role")
        .filter(pk=member_id)
        .first()
    )
    if person is None or not _is_registered(person):
        raise DomainError(_("Tasks can only go to registered members of your company."))
    if person.pk == task.assignee_id:
        raise DomainError(_("%(name)s already has this task.") % {"name": person})
    _ensure_in_scope(by, person)
    return person


def _clear_blocker(task: Task, by: Membership | None, *, outcome) -> None:
    """The "can't do it" is answered (any way at all): its fields go, and its open inbox entries
    show `outcome`. The caller saves the task."""
    if task.blocked_at is None:
        return
    task.blocker, task.blocker_note, task.blocked_at = "", "", None
    inbox.settle(task, outcome=outcome, by=by, kind="tasks.blocked")


def _clear_extension(task: Task, by: Membership | None, *, outcome) -> None:
    """The same for a "need more time" request."""
    if task.extension_until is None:
        return
    task.extension_until, task.extension_note, task.extension_asked_at = None, "", None
    inbox.settle(task, outcome=outcome, by=by, kind="tasks.extension")


def _blocker_body(task: Task, reason: Task.Blocker, note: str) -> str:
    lines = [f"«{task.title}»", _("Reason: %(reason)s") % {"reason": reason.label}]
    if note:
        lines.append(_("Note: %(note)s") % {"note": note})
    return "\n".join(lines)


def _extension_body(task: Task, person: Membership, now: datetime) -> str:
    """In the recipient's language and the company's time ("bugun, 23:30" → "ertaga, 00:30")."""
    tz = ZoneInfo(task.company.timezone)
    local_now = timezone.localtime(now, tz)
    lang = person.user.language

    def when(moment: datetime) -> str:
        return dates.short_due(timezone.localtime(moment, tz), local_now, lang)

    lines = [
        f"«{task.title}»",
        _("Deadline now: %(due)s") % {"due": when(task.due_at)},
        _("Asks for: %(until)s") % {"until": when(task.extension_until)},
    ]
    if task.extension_note:
        lines.append(_("Why: %(note)s") % {"note": task.extension_note})
    return "\n".join(lines)


def _mentioned(task: Task, by: Membership, ids) -> list[Membership]:
    """The people a comment mentions: each must be someone on the task (its assignee, giver,
    checker or escalation contact) or work where it happens (its branch; any branch for a
    company-wide task, and anyone whose scope covers it)."""
    wanted = list(dict.fromkeys(int(pk) for pk in ids or ()))
    if not wanted:
        return []
    if len(wanted) > MAX_MENTIONS:
        raise DomainError(_("Mention at most %(max)d people.") % {"max": MAX_MENTIONS})
    people = {
        person.pk: person
        for person in Membership.objects.for_company(task.company_id)
        .filter(pk__in=wanted, status=Membership.Status.APPROVED)
        .select_related("user", "role", "company")
        .prefetch_related("branches")
    }
    on_task = {task.assignee_id, task.created_by_id, task.confirmed_by_id, task.escalate_to_id}
    found = []
    for pk in wanted:
        person = people.get(pk)
        if person is None:
            raise DomainError(_("Some of the people mentioned don't work here."))
        works_there = (
            task.branch_id is None
            or person.home_branch_id == task.branch_id
            or any(branch.pk == task.branch_id for branch in person.branches.all())
            or allows(branch_ids(person), task.branch_id)
        )
        if pk not in on_task and not works_there:
            raise DomainError(_("%(name)s doesn't work on this task's branch.") % {"name": person})
        if pk != by.pk:
            found.append(person)
    return found


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


@transaction.atomic
def give_routine_today(
    template: TaskTemplate, *, by: Membership, due_at: datetime | None = None
) -> list[Task]:
    """Today's tasks of a routine made after today's deadline, given now. Such a routine starts
    the next day it is due (`generation.MADE_LATE`); this gives today's task anyway, to everyone
    daily generation would give it to (time off, days off, suspended, joined later…, and not to
    whoever has it already), due at `due_at`: later today, by default
    `generation.suggested_deadline`. Each person hears about it like any task given to them."""
    _ensure_may_plan(by)
    template = (
        TaskTemplate.objects.select_for_update(of=("self",))
        .select_related("company", "reminder_policy")
        .prefetch_related("assignees", "positions")
        .get(pk=template.pk)
    )
    _ensure_template_in_scope(template, by)
    now = timezone.now()
    company = template.company
    tz = ZoneInfo(company.timezone)
    today = timezone.localtime(now, tz).date()
    reason = generation.skip_reason(template, today, tz=tz, holiday=is_holiday(company, today))
    if reason != generation.MADE_LATE:
        raise DomainError(_today_refusal(reason, template))
    if due_at is None:
        due_at = generation.suggested_deadline(now, tz)
    elif due_at <= now or timezone.localtime(due_at, tz).date() != today:
        raise DomainError(_("Pick a time later today."))
    people = generation.give_now_people(
        template, today, due_at, related=("user", "position", "company")
    )
    if not people:
        raise DomainError(_("Nobody gets today's task: everyone it names is off or has it."))
    tasks = Task.objects.bulk_create(
        generation.build_tasks(template, today, due_at, people=people, created_by=by, now=now)
    )
    if template.checklist:
        generation.add_checklists([template], today)
    Activity.objects.bulk_create(
        Activity(
            company_id=task.company_id,
            recipient=task.assignee,
            actor=by,
            kind=Activity.Kind.ASSIGNED,
            task=task,
        )
        for task in tasks
        if task.assignee_id != by.pk
    )
    for task in tasks:
        _audit(AuditLog.Action.TASK_ASSIGNED, task, by, assignee=str(task.assignee))
        if task.assignee_id != by.pk:
            transaction.on_commit(partial(jobs.notify_task_assigned.delay, task.pk))
    # bulk_create sends no post_save, so open dashboards hear about the new tasks from here.
    transaction.on_commit(partial(pulse.bump, template.company_id, "tasks.tasks"))
    return tasks


def _today_refusal(reason: str | None, template: TaskTemplate) -> str:
    """Why today's task of `template` can't be given now (`reason` from `skip_reason`)."""
    match reason:
        case None:
            return _("This routine gives today's tasks by itself.")
        case generation.PAUSED:
            return _("This routine is paused.")
        case generation.ONBOARDING:
            return _("Onboarding tasks go out when someone is let in.")
        case generation.HOLIDAY:
            return _("Today is a company holiday: nobody gets routine tasks.")
        case generation.NOT_DUE:
            return _("Today isn't one of this routine's days.")
        case _:
            return _("This routine starts on %(day)s.") % {
                "day": template.starts_on.strftime("%d.%m.%Y")
            }


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


def _refresh_copies(task: Task) -> None:
    """After the commit, every copy of the task in people's chats is drawn again as it is now
    (research R1 C5): no stale buttons on a checker's request, a reassigned card or a late
    alert."""
    transaction.on_commit(partial(jobs.refresh_task_messages.delay, task.pk))


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
        raise DomainError(_("This task isn't waiting for a check."))


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


def _project_role(project, person: Membership) -> str | None:
    """`lead`, `member`, `viewer` or None: what `person` is on the project (apps.projects)."""
    from apps.projects.queries import role_of

    return role_of(project, person)


def _ensure_may_assign(by: Membership, assignee: Membership, project=None) -> None:
    """Whether `by` may give work to someone else (docs/PLAN-OWNER.md §13.3):

    - with tasks.assign, anyone registered in their branch scope, and on a project also anyone
      already on it, wherever they work (the project brought them together);
    - without it, a project's lead, to the people on their own project only (a lead runs their
      project without projects.manage).
    """
    on_project = project is not None and _project_role(project, assignee) is not None
    leads_it = on_project and _project_role(project, by) == "lead"
    if not (by.has_perm(Perm.TASKS_ASSIGN) or leads_it):
        raise PermissionDenied(_("You can't assign tasks to others."))
    if assignee.company_id != by.company_id or not _is_registered(assignee):
        raise DomainError(_("Tasks can only go to registered members of your company."))
    if not on_project:
        _ensure_in_scope(by, assignee)


def _check_project(by: Membership, project, project_list, milestone) -> None:
    """A task's board: a live project of `by`'s company, and a list and milestone of it."""
    if project is None:
        if project_list is not None or milestone is not None:
            raise DomainError(_("That list or milestone is on another board."))
        return
    if project.company_id != by.company_id:
        raise DomainError(_("That isn't part of your company."))
    if project.archived_at is not None:
        raise DomainError(_("This project is archived."))
    for part in (project_list, milestone):
        if part is not None and part.project_id != project.pk:
            raise DomainError(_("That list or milestone is on another board."))


def _ensure_registered(member: Membership) -> None:
    if not _is_registered(member):
        raise PermissionDenied(_("Finish registration first."))
