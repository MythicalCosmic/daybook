from apps.members.departments import manager_of
from apps.members.models import Membership
from apps.reminders.models import ReminderPolicy
from apps.tasks.models import Task, TaskTemplate
from apps.tasks.queries import closest_confirmers


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
    """Who hears that a task is late: the named contact, else whoever assigned it and the
    assignee's own head (apps.members.departments), else everyone allowed to confirm tasks who
    may see it."""
    approved = Membership.Status.APPROVED
    if task.escalate_to_id and task.escalate_to.status == approved:
        return [task.escalate_to]
    recipients = []
    creator = task.created_by
    if (
        task.kind == Task.Kind.ASSIGNED
        and creator is not None
        and creator.pk != task.assignee_id
        and creator.status == approved
    ):
        recipients.append(creator)
    # Someone's personal tasks stay theirs: their head hears only about work given out.
    head = manager_of(task.assignee) if task.kind != Task.Kind.PERSONAL else None
    if head is not None and head not in recipients:
        recipients.append(head)
    if recipients:
        return recipients
    # Only confirmers whose branch scope covers the task (docs/PLAN-OWNER.md §2.6), the
    # branch's own heads first and the owners last (audit X-11).
    return closest_confirmers(task)
