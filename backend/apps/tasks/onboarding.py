"""Onboarding tasks (docs/PLAN-OWNER.md §1.3): when someone is approved, every onboarding template
that names them (directly, through their position, or everyone when it names nobody) gives them
one task, due a few days later. Once per approval: the (template, assignee, for_date) constraint
makes a second run on the same approval a no-op."""

from datetime import datetime, timedelta
from functools import partial
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.audit import services as audit
from apps.members.models import Membership
from apps.reminders.policies import policy_for
from apps.reminders.schedule import first_reminder_at
from apps.tasks import tasks as jobs
from apps.tasks.audit_actions import TasksAction
from apps.tasks.models import Activity, ChecklistItem, Task, TaskTemplate


def templates_for(membership: Membership) -> QuerySet[TaskTemplate]:
    """Active onboarding templates that apply to `membership`."""
    names_nobody = Q(assignees__isnull=True, positions__isnull=True)
    names_them = Q(assignees=membership)
    if membership.position_id is not None:
        names_them |= Q(positions=membership.position_id)
    branch = Q(branch__isnull=True)
    if membership.home_branch_id is not None:
        branch |= Q(branch_id=membership.home_branch_id)
    return (
        TaskTemplate.objects.for_company(membership.company_id)
        .filter(onboarding=True, is_active=True, personal=False)
        .filter(names_nobody | names_them)
        .filter(branch)
        .select_related("reminder_policy", "created_by")
        .distinct()
        .order_by("due_after_days", "due_time", "pk")
    )


@transaction.atomic
def assign_onboarding(membership: Membership, *, now: datetime | None = None) -> list[Task]:
    """Give `membership` their onboarding tasks; returns the tasks made by this call."""
    membership = (
        Membership.objects.select_for_update(of=("self",))
        .select_related("company", "user", "position")
        .get(pk=membership.pk)
    )
    if membership.status != Membership.Status.APPROVED:
        return []
    now = now or timezone.now()
    tz = ZoneInfo(membership.company.timezone)
    approved_on = timezone.localtime(membership.decided_at or now, tz).date()
    made = []
    for template in templates_for(membership):
        due_at = datetime.combine(
            approved_on + timedelta(days=template.due_after_days), template.due_time, tzinfo=tz
        )
        while due_at <= now:  # approved late in the day: due the next time that comes round
            due_at += timedelta(days=1)
        creator = template.created_by
        task = Task(
            company_id=membership.company_id,
            kind=Task.Kind.ASSIGNED,
            template=template,
            for_date=approved_on,
            title=template.title,
            description=template.description,
            assignee=membership,
            created_by=creator
            if creator and creator.status == Membership.Status.APPROVED
            else None,
            due_at=due_at,
            proof=template.proof,
            needs_confirmation=template.needs_confirmation,
            accept_with_proof=template.accept_with_proof,
            reminder_policy=template.reminder_policy,
            escalate_to=template.escalate_to,
            branch_id=membership.home_branch_id,
        )
        task.next_reminder_at = first_reminder_at(due_at, policy_for(task), now)
        try:
            with transaction.atomic():
                task.save()
        except IntegrityError:
            continue  # this approval already got it
        ChecklistItem.objects.bulk_create(
            ChecklistItem(task=task, text=text, order=index)
            for index, text in enumerate(template.checklist)
        )
        Activity.objects.create(
            company_id=task.company_id,
            recipient=membership,
            actor=task.created_by,
            kind=Activity.Kind.ASSIGNED,
            task=task,
        )
        made.append(task)
    if made:
        audit.record(
            TasksAction.ONBOARDING_ASSIGNED,
            company_id=membership.company_id,
            actor=None,
            target=membership,
            tasks=[task.title for task in made],
        )
        ids = [task.pk for task in made]
        transaction.on_commit(partial(jobs.notify_onboarding.delay, membership.pk, ids))
    return made
