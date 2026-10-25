"""Routine tasks: who gets a routine's task on a day, and making them.

One set of rules decides it everywhere: the generator (every 10 minutes), the "who gets it"
preview, a routine's next run, the Routines page's Today and "Give today's task now".

- The day: the routine is running (not paused, not an onboarding template), the day is no company
  holiday, it is one of the routine's weekdays and not before its start date, and the routine
  existed before that day's deadline. A routine made at 12:00 with a 09:00 deadline starts the
  next day it is due (`MADE_LATE`): its first task would be late before anyone saw it.
- The person: named directly or through their position, working here (not left, not suspended),
  registered, at the routine's branch when it has one, registered before the deadline, and not
  off that day (approved time off, or another app's day off: no shift, …).
"""

from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

from apps.companies.models import Company
from apps.console import pulse
from apps.members.models import Membership
from apps.reminders.policies import policy_for
from apps.reminders.schedule import first_reminder_at
from apps.tasks import offdays
from apps.tasks.models import ChecklistItem, Task, TaskTemplate
from apps.timeoff.queries import holidays_between, is_holiday, members_off

# Why a routine makes no tasks on a day, in the order they are checked.
PAUSED = "paused"
ONBOARDING = "onboarding"  # onboarding templates go out when someone is let in
HOLIDAY = "holiday"
NOT_DUE = "not_due"  # not one of its weekdays
NOT_STARTED = "not_started"  # before its start date
MADE_LATE = "made_late"  # made after that day's deadline

# Why someone a routine names doesn't get its task on a day, in the order they are checked.
LEFT = "left"  # doesn't work here any more (left, rejected, blocked)
SUSPENDED = "suspended"
NOT_REGISTERED = "not_registered"
BRANCH = "branch"  # works at another branch than the routine's
JOINED_LATER = "joined_later"  # registered after that day's deadline
TIME_OFF = "time_off"  # approved time off
DAY_OFF = "off"  # another app's day off (offdays providers: no shift that day, …)

# A routine's next run is looked for this many days past its first possible day.
HORIZON_DAYS = 31
# "Give today's task now": due this long from now, on a quarter hour, and never after 23:59.
GIVE_NOW_DELAY = timedelta(hours=2)
# Less time than this left today, and today's task isn't offered any more.
GIVE_NOW_MIN = timedelta(minutes=15)

PERSON_RELATIONS = ("user", "position", "home_branch")


def deadline(template: TaskTemplate, day: date, tz: ZoneInfo) -> datetime:
    """When the routine's task of `day` is due."""
    return datetime.combine(day, template.due_time, tzinfo=tz)


def skip_reason(template: TaskTemplate, day: date, *, tz: ZoneInfo, holiday: bool) -> str | None:
    """Why the routine makes no tasks on `day` (one of the day reasons above), or None when it
    makes them. `holiday`: whether `day` is a company holiday."""
    if not template.is_active:
        return PAUSED
    if template.onboarding:
        return ONBOARDING
    if holiday:
        return HOLIDAY
    if not template.is_due_on(day):
        return NOT_DUE
    if template.starts_on and day < template.starts_on:
        return NOT_STARTED
    if deadline(template, day, tz) <= template.created_at:
        return MADE_LATE
    return None


def days_off(company: Company, day: date) -> tuple[set[int], set[int]]:
    """Membership ids off on `day`: (approved time off, every other app's day off)."""
    return members_off(company, day), offdays.people_off(company, day)


def candidates(template: TaskTemplate, *, related: tuple[str, ...] = ()) -> list[Membership]:
    """Everyone the routine names: the people it picks, whatever their status now (so the
    preview can say who left), and whoever holds one of its positions (working or suspended).
    `related` is select_related for both, for callers that show the people."""
    assignees = template.assignees.select_related(*related) if related else template.assignees.all()
    people = {member.pk: member for member in assignees}
    position_ids = [position.pk for position in template.positions.all()]
    if position_ids:
        holders = Membership.objects.filter(
            company_id=template.company_id,
            position_id__in=position_ids,
            status__in=(Membership.Status.APPROVED, Membership.Status.SUSPENDED),
        )
        if related:
            holders = holders.select_related(*related)
        for member in holders:
            people.setdefault(member.pk, member)
    return list(people.values())


def person_reason(
    member: Membership,
    template: TaskTemplate,
    *,
    due_at: datetime,
    time_off: set[int],
    day_off: set[int],
) -> str | None:
    """Why `member`, whom the routine names, doesn't get its task due at `due_at` (one of the
    person reasons above), or None when they get it."""
    if member.status == Membership.Status.SUSPENDED:
        return SUSPENDED
    if member.status == Membership.Status.PENDING:
        return NOT_REGISTERED
    if member.status != Membership.Status.APPROVED:
        return LEFT
    if member.onboarded_at is None:
        return NOT_REGISTERED
    if template.branch_id is not None and member.home_branch_id != template.branch_id:
        return BRANCH
    if member.onboarded_at >= due_at:
        return JOINED_LATER
    if member.pk in time_off:
        return TIME_OFF
    if member.pk in day_off:
        return DAY_OFF
    return None


def generate_daily_tasks(company: Company, day: date) -> None:
    """Create the day's tasks from the company's running routines. Safe to run repeatedly."""
    if is_holiday(company, day):
        return  # nobody works on a company holiday
    time_off, day_off = days_off(company, day)
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
        if skip_reason(template, day, tz=tz, holiday=False) is not None:
            continue
        due_at = deadline(template, day, tz)
        if template.checklist:
            with_checklist.append(template)
        new_tasks += build_tasks(
            template,
            day,
            due_at,
            people=getting(template, due_at, time_off=time_off, day_off=day_off),
            created_by=template.created_by,
            now=now,
        )
    # The unique (template, assignee, for_date) constraint makes reruns no-ops.
    Task.objects.bulk_create(new_tasks, ignore_conflicts=True)
    add_checklists(with_checklist, day)
    if new_tasks:
        # bulk_create sends no post_save: open dashboards hear about the day's routine work
        # from here (audit X-13).
        pulse.bump(company.pk, "tasks.tasks")


def getting(
    template: TaskTemplate,
    due_at: datetime,
    *,
    time_off: set[int],
    day_off: set[int],
    related: tuple[str, ...] = (),
) -> list[Membership]:
    """The people who get the routine's task due at `due_at` (the day's own rules aside)."""
    return [
        member
        for member in candidates(template, related=related)
        if person_reason(member, template, due_at=due_at, time_off=time_off, day_off=day_off)
        is None
    ]


def build_tasks(
    template: TaskTemplate,
    day: date,
    due_at: datetime,
    *,
    people: Iterable[Membership],
    created_by: Membership | None,
    now: datetime,
) -> list[Task]:
    """The routine's (unsaved) tasks of `day` for `people`, due at `due_at`."""
    first_reminder = first_reminder_at(due_at, policy_for(template), now)
    return [
        Task(
            company_id=template.company_id,
            kind=Task.Kind.PERSONAL if template.personal else Task.Kind.DAILY,
            template=template,
            for_date=day,
            title=template.title,
            description=template.description,
            assignee=member,
            created_by=created_by,
            due_at=due_at,
            proof=template.proof,
            needs_confirmation=template.needs_confirmation,
            accept_with_proof=template.accept_with_proof,
            reminder_policy=template.reminder_policy,
            escalate_to=template.escalate_to,
            next_reminder_at=first_reminder,
            branch_id=member.home_branch_id,
        )
        for member in people
    ]


def preview(template: TaskTemplate, day: date, now: datetime | None = None) -> dict:
    """Who gets the routine's task on `day`, by the same rules as `generate_daily_tasks`:
    `{"due", "holiday", "reason", "due_at", "next_run", "people": [{"member", "gets",
    "reason"}]}`. The top `reason` is why the routine makes no tasks that day (None when it
    makes them), and `next_run` when its next tasks are due then ("made after today's 09:00:
    starts tomorrow"); each person's `reason` is why they don't get it. `due` keeps its old
    meaning: one of its days, on or after its start."""
    now = now or timezone.now()
    company = template.company
    tz = ZoneInfo(company.timezone)
    holiday = is_holiday(company, day)
    reason = skip_reason(template, day, tz=tz, holiday=holiday)
    due_at = deadline(template, day, tz)
    time_off, day_off = days_off(company, day)
    rows = []
    named = sorted(candidates(template, related=PERSON_RELATIONS), key=lambda m: str(m).lower())
    for member in named:
        why = person_reason(member, template, due_at=due_at, time_off=time_off, day_off=day_off)
        rows.append({"member": member, "gets": reason is None and why is None, "reason": why})
    return {
        "due": template.is_due_on(day) and not (template.starts_on and day < template.starts_on),
        "holiday": holiday,
        "reason": reason,
        "due_at": due_at,
        "next_run": next_run(template, now) if reason is not None else None,
        "people": rows,
    }


def next_run(
    template: TaskTemplate,
    now: datetime,
    *,
    tz: ZoneInfo | None = None,
    holidays: set[date] | None = None,
) -> datetime | None:
    """When the routine's next tasks are due: the first deadline after `now` on a day it makes
    tasks. None for paused and onboarding routines, or when no such day comes within
    `HORIZON_DAYS` of its first possible day. `holidays` (the company's, from today on) saves
    a query when many routines are asked about."""
    if not template.is_active or template.onboarding:
        return None
    if tz is None:
        tz = ZoneInfo(template.company.timezone)
    today = timezone.localtime(now, tz).date()
    first = max(today, template.starts_on or today)
    if holidays is None:
        holidays = _holidays(template.company, first, first + timedelta(days=HORIZON_DAYS))
    for offset in range(HORIZON_DAYS + 1):
        day = first + timedelta(days=offset)
        if skip_reason(template, day, tz=tz, holiday=day in holidays) is None:
            due_at = deadline(template, day, tz)
            if due_at > now:
                return due_at
    return None


def next_runs(
    templates: list[TaskTemplate], company: Company, now: datetime
) -> dict[int, datetime | None]:
    """`next_run` of each routine, with one query for the company's holidays."""
    tz = ZoneInfo(company.timezone)
    today = timezone.localtime(now, tz).date()
    last = max([today, *(t.starts_on for t in templates if t.starts_on)])
    holidays = _holidays(company, today, last + timedelta(days=HORIZON_DAYS))
    return {t.pk: next_run(t, now, tz=tz, holidays=holidays) for t in templates}


def _holidays(company: Company, first: date, last: date) -> set[date]:
    return set(holidays_between(company, first, last).values_list("date", flat=True))


# "Give today's task now" -------------------------------------------------------------------


def suggested_deadline(now: datetime, tz: ZoneInfo) -> datetime:
    """When today's task given now is due: `GIVE_NOW_DELAY` from now, rounded up to the quarter
    hour, but still today (23:59 at the latest)."""
    later = timezone.localtime(now, tz) + GIVE_NOW_DELAY
    rounded = later.replace(minute=0, second=0, microsecond=0)
    quarters = -(-(later - rounded).total_seconds() // (15 * 60))  # ceiling
    rounded += timedelta(minutes=15 * int(quarters))
    end_of_today = datetime.combine(timezone.localtime(now, tz).date(), time(23, 59), tzinfo=tz)
    return min(rounded, end_of_today)


def give_now_people(
    template: TaskTemplate, day: date, due_at: datetime, *, related: tuple[str, ...] = ()
) -> list[Membership]:
    """Who gets the routine's task of `day` if it is given now, due at `due_at`: the generator's
    person rules (time off, days off, suspended, joined later…), less whoever has it already."""
    time_off, day_off = days_off(template.company, day)
    have = set(
        Task.objects.filter(template=template, for_date=day).values_list("assignee_id", flat=True)
    )
    people = getting(template, due_at, time_off=time_off, day_off=day_off, related=related)
    return [member for member in people if member.pk not in have]


def today_status(template: TaskTemplate, now: datetime) -> dict:
    """Today, for a routine's page: `{"date", "reason", "give", "given"}`. `reason` is why it
    makes no tasks today (None when it does). When it was made after today's deadline, `given`
    counts today's tasks given by hand all the same, and `give` is `{"people", "due_at"}` for
    "Give today's task now" while someone would still get one."""
    company = template.company
    tz = ZoneInfo(company.timezone)
    today = timezone.localtime(now, tz).date()
    reason = skip_reason(template, today, tz=tz, holiday=is_holiday(company, today))
    give = None
    given = 0
    if reason == MADE_LATE:
        given = (
            Task.objects.filter(template=template, for_date=today)
            .exclude(status=Task.Status.CANCELLED)
            .count()
        )
        due_at = suggested_deadline(now, tz)
        if due_at - now >= GIVE_NOW_MIN:
            people = give_now_people(template, today, due_at)
            if people:
                give = {"people": len(people), "due_at": due_at}
    return {"date": today, "reason": reason, "give": give, "given": given}


def add_checklists(templates: list[TaskTemplate], day: date) -> None:
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
