from datetime import date, datetime
from zoneinfo import ZoneInfo

from apps.companies.models import Company
from apps.members.models import Membership
from apps.tasks.models import Task, TaskTemplate


def generate_daily_tasks(company: Company, day: date) -> None:
    """Create the day's tasks from the company's active templates. Safe to run repeatedly."""
    tz = ZoneInfo(company.timezone)
    templates = (
        TaskTemplate.objects.for_company(company)
        .filter(is_active=True)
        .prefetch_related("assignees", "positions")
    )
    new_tasks = []
    for template in templates:
        if not template.is_due_on(day):
            continue
        due_at = datetime.combine(day, template.due_time, tzinfo=tz)
        if due_at <= template.created_at:
            continue  # the template appeared after today's deadline
        for member in _people_for(template):
            if member.onboarded_at >= due_at:
                continue  # they registered after the deadline
            new_tasks.append(
                Task(
                    company=company,
                    kind=Task.Kind.DAILY,
                    template=template,
                    for_date=day,
                    title=template.title,
                    description=template.description,
                    assignee=member,
                    created_by=template.created_by,
                    due_at=due_at,
                    proof=template.proof,
                    needs_confirmation=template.needs_confirmation,
                )
            )
    # The unique (template, assignee, for_date) constraint makes reruns no-ops.
    Task.objects.bulk_create(new_tasks, ignore_conflicts=True)


def _people_for(template: TaskTemplate) -> set[Membership]:
    """Registered members the template names directly or through their position."""
    people = set(template.assignees.all())
    position_ids = [position.pk for position in template.positions.all()]
    if position_ids:
        people |= set(
            Membership.objects.filter(company_id=template.company_id, position_id__in=position_ids)
        )
    return {
        member
        for member in people
        if member.status == Membership.Status.APPROVED and member.onboarded_at is not None
    }
