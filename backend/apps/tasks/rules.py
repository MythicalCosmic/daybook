"""Who may do what with a task. Pure checks: no queries beyond already-loaded relations, except
for a department head (their team, kept on the member, and whether they may see the task)."""

from datetime import datetime, timedelta
from enum import StrEnum

from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.tasks.models import Proof, Task
from apps.tasks.visibility import head_sees


class Action(StrEnum):
    START = "start"
    COMPLETE = "complete"
    CONFIRM = "confirm"
    RETURN = "return"
    EDIT = "edit"
    CANCEL = "cancel"


# Done can be undone this long (research R2 T38): the service enforces it, the bot's card shows
# its Undo button meanwhile.
UNDO_WINDOW = timedelta(seconds=60)


def is_assignee(task: Task, member: Membership) -> bool:
    return task.assignee_id == member.pk


def can_undo(task: Task, member: Membership, now: datetime) -> bool:
    """Whether the assignee may still take back their Done: within `UNDO_WINDOW`, before anyone
    confirmed it."""
    return (
        is_assignee(task, member)
        and task.status in (Task.Status.DONE, Task.Status.REVIEW)
        and task.completed_at is not None
        and task.confirmed_at is None
        and now - task.completed_at <= UNDO_WINDOW
    )


def accepted_automatically(task: Task) -> bool:
    """Finished work someone else gave that nobody checked: accepted the moment it was done
    (no check asked for, or the company's rule took its proof), or after the company's wait
    for a review (`confirmed_at` set, nobody's name on it). One's own tasks are just done."""
    return (
        task.status == Task.Status.DONE
        and task.confirmed_by_id is None
        and task.kind != Task.Kind.PERSONAL
        and task.created_by_id != task.assignee_id
    )


def can_review(task: Task, member: Membership) -> bool:
    """Confirm or return finished work: whoever assigned it, the assignee's heads, or anyone
    allowed to confirm."""
    if task.company_id != member.company_id or is_assignee(task, member):
        return False
    if task.kind == Task.Kind.ASSIGNED and task.created_by_id == member.pk:
        return True
    if member.has_perm(Perm.TASKS_CONFIRM):
        return True
    return head_sees(task, member)


def can_manage(task: Task, member: Membership) -> bool:
    """Edit or cancel."""
    if task.company_id != member.company_id:
        return False
    if task.kind == Task.Kind.PERSONAL:
        return is_assignee(task, member)
    if task.created_by_id == member.pk:
        return True
    return member.has_perm(
        Perm.TASKS_TEMPLATES if task.kind == Task.Kind.DAILY else Perm.TASKS_ASSIGN
    )


def allowed_actions(task: Task, member: Membership) -> list[Action]:
    actions = []
    if is_assignee(task, member):
        # Start is for work someone was given (audit M-16): routines, one's own tasks and work
        # sent back go straight to Done, the same in the bot and the app.
        if task.kind == Task.Kind.ASSIGNED and task.status == Task.Status.TODO:
            actions.append(Action.START)
        if task.is_open:
            actions.append(Action.COMPLETE)
    if task.status == Task.Status.REVIEW and can_review(task, member):
        actions += [Action.CONFIRM, Action.RETURN]
    if task.is_open and can_manage(task, member):
        actions += [Action.EDIT, Action.CANCEL]
    return actions


# The owner console's extra actions (docs/PLAN-OWNER.md §4.5). Kept apart from `Action`, which
# the mini app's schema lists.
class OwnerAction(StrEnum):
    REASSIGN = "reassign"
    NUDGE = "nudge"
    COMMENT = "comment"


def can_reassign(task: Task, member: Membership) -> bool:
    """Give the work to someone else: whoever may manage it, never someone's personal task."""
    return task.kind != Task.Kind.PERSONAL and task.is_open and can_manage(task, member)


def can_nudge(task: Task, member: Membership) -> bool:
    """Send the assignee a reminder now: shared, open work of someone else, by whoever gave it,
    the assignee's heads, or anyone who hands out, checks or plans work."""
    if task.company_id != member.company_id or is_assignee(task, member):
        return False
    if task.kind == Task.Kind.PERSONAL or not task.is_open:
        return False
    if task.created_by_id == member.pk:
        return True
    if any(
        member.has_perm(perm)
        for perm in (Perm.TASKS_ASSIGN, Perm.TASKS_CONFIRM, Perm.TASKS_TEMPLATES)
    ):
        return True
    return head_sees(task, member)


def owner_actions(task: Task, member: Membership) -> list[str]:
    """What the member may do with the task in the dashboard, as plain strings."""
    actions = [str(action) for action in allowed_actions(task, member)]
    if can_reassign(task, member):
        actions.append(OwnerAction.REASSIGN)
    if can_nudge(task, member):
        actions.append(OwnerAction.NUDGE)
    if task.company_id == member.company_id:
        actions.append(OwnerAction.COMMENT)
    return actions


# Board columns (docs/PLAN-OWNER.md §1.3: To do, In progress, Waiting, Sent back, Done).
class Column(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    RETURNED = "returned"
    DONE = "done"


def board_moves(task: Task, member: Membership) -> list[str]:
    """Columns the member may drag the card to, each meaning one allowed transition: start it,
    finish it (only work that needs no proof), confirm it or send it back."""
    actions = allowed_actions(task, member)
    moves = []
    if Action.START in actions:
        moves.append(Column.IN_PROGRESS)
    if Action.COMPLETE in actions and task.proof == Proof.NONE:
        moves.append(Column.REVIEW if task.needs_confirmation else Column.DONE)
    if Action.CONFIRM in actions:
        moves.append(Column.DONE)
    if Action.RETURN in actions:
        moves.append(Column.RETURNED)
    return [str(move) for move in dict.fromkeys(moves)]
