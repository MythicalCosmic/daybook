from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import members_with_perm
from apps.reminders.models import ReminderPolicy
from apps.tasks.models import Task, TaskTemplate


def default_policy(company_id: int) -> ReminderPolicy:
    policy, _ = ReminderPolicy.objects.get_or_create(
        company_id=company_id, is_default=True, defaults={"name": "Default"}
    )
    return policy


def policy_for(task: Task | TaskTemplate) -> ReminderPolicy:
    """The task's own policy, else its template's, else the company default."""
    if task.reminder_policy_id:
        return task.reminder_policy
    template = getattr(task, "template", None)
    if template is not None and template.reminder_policy_id:
        return template.reminder_policy
    return default_policy(task.company_id)


def escalation_recipients(task: Task) -> list[Membership]:
    """Who hears that a task is late: the named contact, else whoever assigned it, else
    everyone allowed to confirm tasks."""
    approved = Membership.Status.APPROVED
    if task.escalate_to_id and task.escalate_to.status == approved:
        return [task.escalate_to]
    creator = task.created_by
    if (
        task.kind == Task.Kind.ASSIGNED
        and creator is not None
        and creator.pk != task.assignee_id
        and creator.status == approved
    ):
        return [creator]
    return list(
        members_with_perm(task.company, Perm.TASKS_CONFIRM)
        .exclude(pk=task.assignee_id)
        .select_related("user")
    )
