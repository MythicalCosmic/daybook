"""Who may do what with a task. Pure checks: no queries beyond already-loaded relations."""

from enum import StrEnum

from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.tasks.models import Task


class Action(StrEnum):
    START = "start"
    COMPLETE = "complete"
    CONFIRM = "confirm"
    RETURN = "return"
    EDIT = "edit"
    CANCEL = "cancel"


def is_assignee(task: Task, member: Membership) -> bool:
    return task.assignee_id == member.pk


def can_review(task: Task, member: Membership) -> bool:
    """Confirm or return finished work: whoever assigned it, or anyone allowed to confirm."""
    if task.company_id != member.company_id or is_assignee(task, member):
        return False
    if task.kind == Task.Kind.ASSIGNED and task.created_by_id == member.pk:
        return True
    return member.has_perm(Perm.TASKS_CONFIRM)


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
        if task.status in (Task.Status.TODO, Task.Status.RETURNED):
            actions.append(Action.START)
        if task.is_open:
            actions.append(Action.COMPLETE)
    if task.status == Task.Status.REVIEW and can_review(task, member):
        actions += [Action.CONFIRM, Action.RETURN]
    if task.is_open and can_manage(task, member):
        actions += [Action.EDIT, Action.CANCEL]
    return actions
