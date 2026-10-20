from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.utils import timezone

from apps.companies.models import Company
from apps.members.models import Membership
from apps.reminders.policies import policy_for
from apps.reminders.schedule import first_reminder_at
from apps.tasks import offdays
from apps.tasks.models import ChecklistItem, Task, TaskTemplate
from apps.timeoff.queries import is_holiday, members_off


def generate_daily_tasks(company: Company, day: date) -> None:
    """Create the day's tasks from the company's active templates. Safe to run repeatedly."""
    if is_holiday(company, day):
        return  # nobody works on a company holiday
    # Approved time off, plus whoever other apps say is off (suspended, not on a shift…).
    off = members_off(company, day) | offdays.people_off(company, day)
    tz = ZoneInfo(company.timezone)
    now = timezone.now()
    templates = (
        TaskTemplate.objects.for_company(company)
        .filter(is_active=True, onboarding=False)  # onboarding ones go out on approval
        .select_related("reminder_policy")
        .prefetch_related("assignees", "positions")
    )
    new_tasks = []
    with_checklist = []
    for template in templates:
        if not template.is_due_on(day) or (template.starts_on and day < template.starts_on):
            continue
        due_at = datetime.combine(day, template.due_time, tzinfo=tz)
        if due_at <= template.created_at:
            continue  # the template appeared after today's deadline
        if template.checklist:
            with_checklist.append(template)
        first_reminder = first_reminder_at(due_at, policy_for(template), now)
        for member in people_for(template):
            if member.onboarded_at >= due_at:
                continue  # they registered after the deadline
            if member.pk in off:
                continue  # time off, or another app's day off
            new_tasks.append(
                Task(
                    company=company,
                    kind=Task.Kind.PERSONAL if template.personal else Task.Kind.DAILY,
                    template=template,
                    for_date=day,
                    title=template.title,
                    description=template.description,
                    assignee=member,
                    created_by=template.created_by,
                    due_at=due_at,
                    proof=template.proof,
                    needs_confirmation=template.needs_confirmation,
                    reminder_policy=template.reminder_policy,
                    escalate_to=template.escalate_to,
                    next_reminder_at=first_reminder,
                    branch_id=member.home_branch_id,
                )
            )
    # The unique (template, assignee, for_date) constraint makes reruns no-ops.
    Task.objects.bulk_create(new_tasks, ignore_conflicts=True)
    _add_checklists(with_checklist, day)


def preview(template: TaskTemplate, day: date) -> dict:
    """Who would get the routine's task on `day`, by the same rules as `generate_daily_tasks`:
    `{"due": bool, "holiday": bool, "people": [{"member", "gets", "reason"}]}`. `reason` says
    why someone named doesn't get it: off (time off or another app's day off), branch (works
    elsewhere), not_registered."""
    company = template.company
    due = template.is_due_on(day) and not (template.starts_on and day < template.starts_on)
    holiday = is_holiday(company, day)
    off = members_off(company, day) | offdays.people_off(company, day)
    getting = people_for(template)
    named = set(template.assignees.select_related("user", "position", "home_branch"))
    position_ids = list(template.positions.values_list("pk", flat=True))
    if position_ids:
        named |= set(
            Membership.objects.filter(
                company_id=template.company_id,
                position_id__in=position_ids,
                status=Membership.Status.APPROVED,
            ).select_related("user", "position", "home_branch")
        )
    rows = []
    for member in sorted(named, key=lambda m: str(m).lower()):
        if member not in getting:
            reason = "not_registered" if member.onboarded_at is None else "branch"
        elif member.pk in off:
            reason = "off"
        else:
            reason = None
        rows.append(
            {"member": member, "gets": due and not holiday and reason is None, "reason": reason}
        )
    return {"due": due, "holiday": holiday, "people": rows}


def _add_checklists(templates: list[TaskTemplate], day: date) -> None:
    """The routine's steps on each of the day's tasks that doesn't have them yet."""
    if not templates:
        return
    by_template = {template.pk: template for template in templates}
    bare = Task.objects.filter(
        template_id__in=by_template, for_date=day, checklist__isnull=True
    ).values_list("pk", "template_id")
    ChecklistItem.objects.bulk_create(
        ChecklistItem(task_id=task_id, text=text, order=index)
        for task_id, template_id in bare
        for index, text in enumerate(by_template[template_id].checklist)
    )


def people_for(template: TaskTemplate) -> set[Membership]:
    """Registered members the template names directly or through their position, limited to
    its branch's people when it has one."""
    people = set(template.assignees.all())
    position_ids = [position.pk for position in template.positions.all()]
    if position_ids:
        people |= set(
            Membership.objects.filter(company_id=template.company_id, position_id__in=position_ids)
        )
    return {
        member
        for member in people
        if member.status == Membership.Status.APPROVED
        and member.onboarded_at is not None
        and (template.branch_id is None or member.home_branch_id == template.branch_id)
    }
