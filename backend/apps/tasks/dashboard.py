"""Read models of the owner console's task pages (docs/PLAN-OWNER.md §6.2): the board, the
calendar, the KPI numbers, the photo wall, a task's merged timeline, routine statistics and the
Routines page's routine work (a day of it, its history, what waits for confirmation).
Everything starts from `queries.visible_tasks`, so personal tasks and branch scope (§2.6, §3.2)
apply everywhere. Personal tasks never count in KPIs."""

from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Count, F, Prefetch, Q, QuerySet
from django.utils import timezone

from apps.audit import registry as audit_registry
from apps.audit.queries import events
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.scope import branch_ids as scope_of
from apps.reminders.models import ReminderLog
from apps.tasks import generation, queries, rules
from apps.tasks.models import Task, TaskTemplate
from apps.timeoff.queries import is_holiday

BOARD_LIMIT = 60
CALENDAR_LIMIT = 600
# Finished from the assignee's point of view: waiting for a check counts as done on time.
FINISHED = (Task.Status.DONE, Task.Status.REVIEW)
SHARED = (Task.Kind.DAILY, Task.Kind.ASSIGNED)


def with_rows(tasks: QuerySet[Task]) -> QuerySet[Task]:
    """What `TaskRowSerializer` reads, loaded up front (safe to apply twice)."""
    return tasks.prefetch_related("checklist")


# Board -------------------------------------------------------------------------------------


def board(tasks: QuerySet[Task], now: datetime, company) -> list[dict]:
    """Five columns of cards (To do, In progress, Waiting, Sent back, Done) from an already
    filtered queryset; each capped at `BOARD_LIMIT`, with its full count. Done shows the last
    7 days, newest first; the others by deadline."""
    done_since = now - timedelta(days=7)
    columns = []
    for column in rules.Column:
        cards = tasks.filter(status=column.value)
        if column == rules.Column.DONE:
            cards = cards.filter(completed_at__gte=done_since).order_by("-completed_at", "-pk")
        else:
            cards = cards.order_by(F("due_at").asc(nulls_last=True), "pk")
        columns.append(
            {
                "id": column.value,
                "count": cards.count(),
                "items": list(with_rows(cards)[:BOARD_LIMIT]),
            }
        )
    return columns


# Calendar ----------------------------------------------------------------------------------


def calendar(tasks: QuerySet[Task], company, start: date, end: date, now: datetime) -> dict:
    """Due tasks per company-local day from `start` to `end` (both inclusive): counts per day
    and the tasks themselves (capped)."""
    first, _unused = queries.day_bounds(company, start)
    _unused, last = queries.day_bounds(company, end)
    due = tasks.filter(due_at__gte=first, due_at__lt=last).exclude(status=Task.Status.CANCELLED)
    rows = list(due.values_list("due_at", "status"))
    days: dict[date, dict] = {}
    tz = ZoneInfo(company.timezone)
    for due_at, status in rows:
        day = timezone.localtime(due_at, tz).date()
        entry = days.setdefault(day, {"total": 0, "done": 0, "review": 0, "open": 0, "late": 0})
        entry["total"] += 1
        if status == Task.Status.DONE:
            entry["done"] += 1
        elif status == Task.Status.REVIEW:
            entry["review"] += 1
        else:
            entry["open"] += 1
            if due_at < now:
                entry["late"] += 1
    items = list(with_rows(due.order_by("due_at", "pk"))[:CALENDAR_LIMIT])
    return {
        "days": [{"date": day, **days[day]} for day in sorted(days)],
        "items": items,
        "truncated": len(rows) > CALENDAR_LIMIT,
    }


# KPI numbers -------------------------------------------------------------------------------


def summary(
    member: Membership,
    now: datetime,
    *,
    branch_ids: list[int] | None,
    assignee_id=None,
    routines: str = "",
) -> dict:
    """The Tasks KPI strip and Overview widgets: today's done/total, late now, waiting for a
    check, 7-day on-time % against the 7 days before, and a 14-day series. `routines`
    ("without"/"only", `queries.split`) keeps to one-off work or to routine work."""
    company = member.company
    shared = queries.split(queries.visible_tasks(member).filter(kind__in=SHARED), routines)
    if branch_ids is not None:
        shared = shared.filter(branch_id__in=branch_ids)
    if assignee_id is not None:
        shared = shared.filter(assignee_id=assignee_id)
    today = queries.company_today(company, now)
    start, end = queries.day_bounds(company, today)
    todays = shared.filter(due_at__gte=start, due_at__lt=end).exclude(status=Task.Status.CANCELLED)
    counts = todays.aggregate(
        total=Count("pk"),
        done=Count("pk", filter=Q(status__in=FINISHED)),
    )
    late_now = shared.filter(status__in=Task.OPEN_STATUSES, due_at__lt=now).count()
    review = shared.filter(status=Task.Status.REVIEW).count()
    open_count = shared.filter(status__in=Task.OPEN_STATUSES).count()
    series = daily_series(shared, company, today - timedelta(days=13), today, now)
    week = _window(series[-7:])
    before = _window(series[:7])
    return {
        "today": today,
        "done_today": counts["done"],
        "total_today": counts["total"],
        "late_now": late_now,
        "review": review,
        "open": open_count,
        "on_time_percent": week["on_time_percent"],
        "on_time_previous": before["on_time_percent"],
        "done_7d": week["done"],
        "done_prev_7d": before["done"],
        "series": series,
    }


def daily_series(
    tasks: QuerySet[Task], company, first: date, last: date, now: datetime
) -> list[dict]:
    """Per day: tasks due that day whose deadline passed, on time, late, missed, on-time %."""
    tz = ZoneInfo(company.timezone)
    start, _unused = queries.day_bounds(company, first)
    _unused, end = queries.day_bounds(company, last)
    rows = (
        tasks.filter(due_at__gte=start, due_at__lt=min(end, now))
        .exclude(status=Task.Status.CANCELLED)
        .values_list("due_at", "status", "completed_at")
    )
    days: dict[date, dict] = defaultdict(lambda: {"on_time": 0, "late": 0, "missed": 0})
    for due_at, status, completed_at in rows:
        entry = days[timezone.localtime(due_at, tz).date()]
        if status in FINISHED and completed_at is not None:
            entry["on_time" if completed_at <= due_at else "late"] += 1
        else:
            entry["missed"] += 1
    out = []
    day = first
    while day <= last:
        entry = days.get(day, {"on_time": 0, "late": 0, "missed": 0})
        total = entry["on_time"] + entry["late"] + entry["missed"]
        out.append(
            {
                "date": day,
                **entry,
                "total": total,
                "done": entry["on_time"] + entry["late"],
                "on_time_percent": round(100 * entry["on_time"] / total, 1) if total else None,
            }
        )
        day += timedelta(days=1)
    return out


def _window(days: list[dict]) -> dict:
    on_time = sum(day["on_time"] for day in days)
    total = sum(day["total"] for day in days)
    return {
        "on_time_percent": round(100 * on_time / total, 1) if total else None,
        "done": sum(day["done"] for day in days),
    }


# Photo wall --------------------------------------------------------------------------------


def proofs(
    member: Membership, day: date, *, branch_ids: list[int] | None, routine_id=None
) -> list[Task]:
    """Tasks finished on `day` with a proof photo, newest first."""
    start, end = queries.day_bounds(member.company, day)
    tasks = (
        queries.visible_tasks(member)
        .exclude(proof_photo="")
        .filter(completed_at__gte=start, completed_at__lt=end)
    )
    if branch_ids is not None:
        tasks = tasks.filter(branch_id__in=branch_ids)
    if routine_id is not None:
        tasks = tasks.filter(template_id=routine_id)
    return list(with_rows(tasks.order_by("-completed_at", "-pk"))[:300])


# Timeline ----------------------------------------------------------------------------------


def timeline(task: Task, viewer: Membership) -> list[dict]:
    """Comments, reminders and audited changes of one task, oldest first:
    `{at, kind, title, actor, text, meta}` (kind: created, comment, heads_up, reminder,
    escalation, blocked, audit)."""
    entries: list[dict] = [
        {
            "at": task.created_at,
            "kind": "created",
            "actor": task.created_by,
            "action": "created",
            "text": "",
            "meta": {},
        }
    ]
    for comment in task.comments.select_related("author__user", "author__position"):
        entries.append(
            {
                "at": comment.created_at,
                "kind": "comment",
                "actor": comment.author,
                "action": "comment",
                "text": comment.text,
                "meta": {},
            }
        )
    for log in task.reminder_log.select_related("recipient__user", "recipient__position"):
        entries.append(
            {
                "at": log.sent_at,
                "kind": log.kind,
                "actor": log.recipient,
                "action": log.kind,
                "text": log.error,
                "meta": {"step": log.step, "delivered": log.delivered},
            }
        )
    if task.completed_at:
        entries.append(
            {
                "at": task.completed_at,
                "kind": "completed",
                "actor": task.assignee,
                "action": "completed",
                "text": task.proof_text,
                "meta": {},
            }
        )
    actors = {}
    for row in events(viewer, target_type="task", target_id=task.pk):
        user_id = row.actor_id
        if user_id is not None and user_id not in actors:
            actors[user_id] = (
                Membership.objects.select_related("user", "position")
                .filter(company_id=task.company_id, user_id=user_id)
                .first()
            )
        entries.append(
            {
                "at": row.created_at,
                "kind": "audit",
                "actor": actors.get(user_id),
                "action": row.action,
                "text": audit_registry.label(row.action),
                "meta": {
                    key: value
                    for key, value in (row.details or {}).items()
                    if key in ("changes", "reason", "assignee")
                },
            }
        )
    entries.sort(key=lambda entry: entry["at"])
    return entries


# Routines ----------------------------------------------------------------------------------


def routine_stats(
    templates: list[TaskTemplate], company, now: datetime, *, days: int = 30
) -> dict[int, dict]:
    """Per routine: tasks made in the last `days` days whose deadline passed, how many finished
    on time, the completion % and a 14-day sparkline of daily completion."""
    if not templates:
        return {}
    tz = ZoneInfo(company.timezone)
    today = queries.company_today(company, now)
    start, _unused = queries.day_bounds(company, today - timedelta(days=days - 1))
    rows = (
        Task.objects.filter(
            template_id__in=[t.pk for t in templates], due_at__gte=start, due_at__lt=now
        )
        .exclude(status=Task.Status.CANCELLED)
        .values_list("template_id", "due_at", "status", "completed_at")
    )
    per: dict[int, dict] = {
        t.pk: {"made": 0, "on_time": 0, "done": 0, "days": defaultdict(lambda: [0, 0])}
        for t in templates
    }
    for template_id, due_at, status, completed_at in rows:
        entry = per[template_id]
        entry["made"] += 1
        finished = status in FINISHED and completed_at is not None
        if finished:
            entry["done"] += 1
            if completed_at <= due_at:
                entry["on_time"] += 1
        day = timezone.localtime(due_at, tz).date()
        entry["days"][day][0] += 1
        entry["days"][day][1] += int(finished)
    out = {}
    for template_id, entry in per.items():
        spark = []
        for offset in range(13, -1, -1):
            made, done = entry["days"].get(today - timedelta(days=offset), (0, 0))
            spark.append(round(100 * done / made) if made else None)
        out[template_id] = {
            "made_30d": entry["made"],
            "done_30d": entry["done"],
            "on_time_30d": entry["on_time"],
            "completion_30d": round(100 * entry["done"] / entry["made"], 1)
            if entry["made"]
            else None,
            "spark": spark,
        }
    return out


def routine_compliance(template: TaskTemplate, start: date, end: date, now: datetime) -> dict:
    """One routine over a range: per day and per person, made / on time / late / missed. Work
    still open past its deadline is late while its day lasts and missed once the day is over."""
    company = template.company
    tz = ZoneInfo(company.timezone)
    first, _unused = queries.day_bounds(company, start)
    _unused, last = queries.day_bounds(company, end)
    rows = (
        Task.objects.filter(template=template, due_at__gte=first, due_at__lt=min(last, now))
        .exclude(status=Task.Status.CANCELLED)
        .select_related("assignee__user", "assignee__position")
    )
    days: dict[date, dict] = defaultdict(lambda: {"made": 0, "on_time": 0, "late": 0, "missed": 0})
    people: dict[int, dict] = {}
    over = _day_over(company, now)
    for task in rows:
        local_day = timezone.localtime(task.due_at, tz).date()
        outcome = _outcome(task, day_over=over(local_day))
        day = days[local_day]
        day["made"] += 1
        day[outcome] += 1
        row = people.setdefault(
            task.assignee_id,
            {"member": task.assignee, "made": 0, "on_time": 0, "late": 0, "missed": 0},
        )
        row["made"] += 1
        row[outcome] += 1
    series = []
    day = start
    while day <= end:
        entry = days.get(day, {"made": 0, "on_time": 0, "late": 0, "missed": 0})
        series.append(
            {"date": day, **entry, "on_time_percent": _percent(entry["on_time"], entry["made"])}
        )
        day += timedelta(days=1)
    totals = {
        key: sum(entry[key] for entry in series) for key in ("made", "on_time", "late", "missed")
    }
    totals["on_time_percent"] = _percent(totals["on_time"], totals["made"])
    rows_out = sorted(
        (
            {**row, "on_time_percent": _percent(row["on_time"], row["made"])}
            for row in people.values()
        ),
        key=lambda row: (
            row["on_time_percent"] is None,
            -(row["on_time_percent"] or 0),
            str(row["member"]),
        ),
    )
    return {"totals": totals, "series": series, "people": rows_out}


def _outcome(task: Task, *, day_over: bool = True) -> str:
    """on_time or late when finished; not finished past its deadline: late while its day lasts,
    missed once it is over."""
    if task.status in FINISHED and task.completed_at is not None:
        return "on_time" if task.completed_at <= task.due_at else "late"
    return "missed" if day_over else "late"


def _day_over(company, now: datetime):
    """`over(day)`: whether the company's `day` has ended by `now` (each end worked out once)."""
    ends: dict[date, datetime] = {}

    def over(day: date | None) -> bool:
        if day is None:
            return True
        if day not in ends:
            ends[day] = queries.day_bounds(company, day)[1]
        return now >= ends[day]

    return over


def _percent(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def reminder_counts(task_ids: list[int]) -> dict[int, int]:
    return dict(
        ReminderLog.objects.filter(task_id__in=task_ids, kind=ReminderLog.Kind.REMINDER)
        .values("task_id")
        .annotate(n=Count("pk"))
        .values_list("task_id", "n")
    )


# Routine work: the Routines page's Today, History and To confirm ----------------------------

# How one person's run of a routine stands. Late: open past its deadline while the day lasts;
# missed: still open once the day is over.
RUN_ORDER = ("late", "missed", "review", "returned", "open", "done", "cancelled")
# People a routine names but leaves out on a day, listed as skipped: these are the day's doing.
# (Someone who left, works at another branch or never registered isn't "skipped".)
SKIPPED_SHOWN = (
    generation.TIME_OFF,
    generation.DAY_OFF,
    generation.SUSPENDED,
    generation.JOINED_LATER,
)
CONFIRM_LIMIT = 300
PERSON_RELATIONS = ("user", "position")


def run_state(task: Task, now: datetime, day_end: datetime) -> str:
    """done, review (waiting for confirmation), cancelled, late, missed, returned or open."""
    if task.status == Task.Status.DONE:
        return "done"
    if task.status == Task.Status.REVIEW:
        return "review"
    if task.status == Task.Status.CANCELLED:
        return "cancelled"
    if task.due_at is not None and task.due_at < now:
        return "missed" if now >= day_end else "late"
    return "returned" if task.status == Task.Status.RETURNED else "open"


def _run_relations(tasks: QuerySet[Task]) -> QuerySet[Task]:
    return tasks.select_related("assignee__user", "assignee__position", "branch").prefetch_related(
        "checklist"
    )


def _shared_routines(member: Membership, branch_ids: list[int] | None) -> list[TaskTemplate]:
    """The company's routines `member` may see on the Routines page: branch-less ones and those
    of their branches (and of `branch_ids` when the page filters by branch)."""
    routines = (
        TaskTemplate.objects.for_company(member.company_id)
        .filter(personal=False, onboarding=False)
        .select_related("branch")
        .prefetch_related(
            Prefetch("assignees", queryset=Membership.objects.select_related(*PERSON_RELATIONS)),
            "positions",
        )
        .order_by("due_time", "title", "pk")
    )
    scope = scope_of(member)
    return [
        routine
        for routine in routines
        if (routine.branch_id is None or scope is None or routine.branch_id in scope)
        and (routine.branch_id is None or not branch_ids or routine.branch_id in branch_ids)
    ]


def _holders(company_id: int, routines: list[TaskTemplate]) -> dict[int, list[Membership]]:
    """{position id: its working or suspended holders}, one query for every routine's positions."""
    position_ids = {position.pk for routine in routines for position in routine.positions.all()}
    holders: dict[int, list[Membership]] = defaultdict(list)
    if position_ids:
        for member in Membership.objects.filter(
            company_id=company_id,
            position_id__in=position_ids,
            status__in=(Membership.Status.APPROVED, Membership.Status.SUSPENDED),
        ).select_related(*PERSON_RELATIONS):
            holders[member.position_id].append(member)
    return holders


def _named(routine: TaskTemplate, holders: dict[int, list[Membership]]) -> list[Membership]:
    """`generation.candidates` from what `_shared_routines` and `_holders` loaded."""
    people = {member.pk: member for member in routine.assignees.all()}
    for position in routine.positions.all():
        for member in holders.get(position.pk, ()):
            people.setdefault(member.pk, member)
    return list(people.values())


def routine_day(
    member: Membership,
    day: date,
    now: datetime,
    *,
    branch_ids: list[int] | None = None,
    position_ids: list[int] | None = None,
) -> dict:
    """Every routine due on `day`, or with work that day, with each person's run and who it
    skipped (time off, day off, suspended, joined later): the Routines page's Today, and one day
    of its History. Runs come from `visible_tasks` (branch scope). `branch_ids` narrows runs to
    work at those branches and skipped people to their home branch; `position_ids` to people
    holding those positions. Routines that make nothing that day and had no work are counted in
    `idle`, not listed."""
    company = member.company
    tz = ZoneInfo(company.timezone)
    routines = _shared_routines(member, branch_ids)
    runs = queries.visible_tasks(member).filter(
        queries.ROUTINE_WORK, for_date=day, template_id__in=[routine.pk for routine in routines]
    )
    if branch_ids:
        runs = runs.filter(branch_id__in=branch_ids)
    if position_ids:
        runs = runs.filter(assignee__position_id__in=position_ids)
    by_routine: dict[int, list[Task]] = defaultdict(list)
    for task in _run_relations(runs).order_by("pk"):
        by_routine[task.template_id].append(task)

    holiday = is_holiday(company, day)
    time_off, day_off = generation.days_off(company, day)
    holders = _holders(company.pk, routines)
    scope = scope_of(member)
    day_end = queries.day_bounds(company, day)[1]
    may_give = member.has_perm(Perm.TASKS_TEMPLATES)
    today = queries.company_today(company, now)

    def shown(person: Membership) -> bool:
        return (
            (scope is None or person.home_branch_id in scope)
            and (not branch_ids or person.home_branch_id in branch_ids)
            and (not position_ids or person.position_id in position_ids)
        )

    listed, idle = [], 0
    for routine in routines:
        reason = generation.skip_reason(routine, day, tz=tz, holiday=holiday)
        tasks = by_routine.get(routine.pk, [])
        skipped = []
        if reason is None:
            due_at = generation.deadline(routine, day, tz)
            have = {task.assignee_id for task in tasks}
            for person in _named(routine, holders):
                why = generation.person_reason(
                    person, routine, due_at=due_at, time_off=time_off, day_off=day_off
                )
                if why in SKIPPED_SHOWN and person.pk not in have and shown(person):
                    skipped.append({"member": person, "reason": why})
        if not tasks and not skipped and reason not in (generation.HOLIDAY, generation.MADE_LATE):
            idle += 1
            continue
        states = [run_state(task, now, day_end) for task in tasks]
        counts = {state: states.count(state) for state in RUN_ORDER}
        counts["skipped"] = len(skipped)
        total = len(tasks) - counts["cancelled"]
        finished = counts["done"] + counts["review"]
        give = None
        # Offered to whoever may plan this routine (services.give_routine_today's own checks):
        # routines rights, and the routine's branch in their scope.
        plans_it = may_give and (scope is None or routine.branch_id in scope)
        if reason == generation.MADE_LATE and day == today and plans_it:
            give = generation.today_status(routine, now)["give"]
        order = {state: index for index, state in enumerate(RUN_ORDER)}
        rows = sorted(
            zip(tasks, states, strict=True),
            key=lambda pair: (order[pair[1]], str(pair[0].assignee).lower()),
        )
        listed.append(
            {
                "routine": routine,
                "due_at": generation.deadline(routine, day, tz),
                "reason": reason,
                "next_run": generation.next_run(routine, now, tz=tz)
                if reason in (generation.HOLIDAY, generation.MADE_LATE)
                else None,
                "give": give,
                "progress": {
                    "finished": finished,
                    "total": total,
                    "percent": share(finished, total),
                },
                "counts": counts,
                "runs": [{"task": task, "state": state} for task, state in rows],
                "skipped": sorted(skipped, key=lambda row: str(row["member"]).lower()),
            }
        )
    totals = {state: sum(row["counts"][state] for row in listed) for state in RUN_ORDER}
    totals["skipped"] = sum(row["counts"]["skipped"] for row in listed)
    totals["total"] = sum(row["progress"]["total"] for row in listed)
    totals["finished"] = totals["done"] + totals["review"]
    totals["routines"] = len(listed)
    return {"day": day, "holiday": holiday, "routines": listed, "totals": totals, "idle": idle}


def share(part: int, whole: int) -> int | None:
    """A whole percent of `whole` that reads 100 only when all of it is done and 0 only when
    none of it is (537 of 539 is 99, not a rounded-up 100); None when there is nothing."""
    if not whole:
        return None
    value = round(100 * part / whole)
    if part < whole:
        value = min(value, 99)
    if part > 0:
        value = max(value, 1)
    return value


def _cell() -> dict:
    return {"made": 0, "finished": 0, "on_time": 0, "late": 0, "missed": 0, "open": 0}


def _rated(cell: dict) -> dict:
    """A cell with its rates over the work whose time has come (not what's still ahead)."""
    due = cell["made"] - cell["open"]
    return cell | {
        "percent": share(cell["finished"], due),
        "on_time_percent": share(cell["on_time"], due),
    }


def routine_history(
    member: Membership,
    start: date,
    end: date,
    now: datetime,
    *,
    branch_ids: list[int] | None = None,
    position_ids: list[int] | None = None,
) -> dict:
    """Routine work from `start` to `end`: per routine per day (the completion heatmap), per
    day, and per person. A run counts as finished when done or waiting for confirmation, on
    time when finished by its deadline, late when finished after it or still open past it while
    its day lasts, missed when its day ended without it (the Today page's words), open while its
    time is still ahead; rates are over the work whose time has come."""
    over = _day_over(member.company, now)
    runs = (
        queries.visible_tasks(member)
        .filter(queries.ROUTINE_WORK, for_date__range=(start, end))
        .exclude(status=Task.Status.CANCELLED)
    )
    if branch_ids:
        runs = runs.filter(branch_id__in=branch_ids)
    if position_ids:
        runs = runs.filter(assignee__position_id__in=position_ids)
    cells: dict[tuple[int, date], dict] = defaultdict(_cell)
    days: dict[date, dict] = defaultdict(_cell)
    people: dict[int, dict] = defaultdict(_cell)
    rows = runs.values_list(
        "template_id", "for_date", "status", "completed_at", "due_at", "assignee_id"
    )
    for template_id, day, status, completed_at, due_at, assignee_id in rows:
        if status in FINISHED and completed_at is not None:
            on_time = due_at is None or completed_at <= due_at
            outcome = ("finished", "on_time" if on_time else "late")
        elif due_at is not None and due_at < now:
            outcome = ("missed",) if over(day) else ("late",)
        else:
            outcome = ("open",)
        for entry in (cells[(template_id, day)], days[day], people[assignee_id]):
            entry["made"] += 1
            for key in outcome:
                entry[key] += 1
    template_ids = {template_id for template_id, _day in cells}
    routines = TaskTemplate.objects.filter(pk__in=template_ids).select_related("branch")
    span = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    members = Membership.objects.filter(pk__in=list(people)).select_related(*PERSON_RELATIONS)
    totals = _cell()
    for entry in days.values():
        for key in totals:
            totals[key] += entry[key]
    return {
        "days": span,
        "routines": [
            {
                "routine": routine,
                "cells": [
                    _rated(cells[(routine.pk, day)]) if (routine.pk, day) in cells else None
                    for day in span
                ],
                "totals": _rated(
                    {
                        key: sum(
                            cells[(routine.pk, day)][key]
                            for day in span
                            if (routine.pk, day) in cells
                        )
                        for key in _cell()
                    }
                ),
            }
            for routine in sorted(routines, key=lambda r: (r.due_time, r.title.lower(), r.pk))
        ],
        "series": [{"date": day, **_rated(days[day] if day in days else _cell())} for day in span],
        "people": sorted(
            ({"member": person, **_rated(people[person.pk])} for person in members),
            key=lambda row: (
                row["percent"] is None,
                row["percent"] or 0,
                str(row["member"]).lower(),
            ),
        ),
        "totals": _rated(totals),
    }


def routine_confirm_queue(member: Membership) -> list[dict]:
    """Routine work waiting for `member`'s confirmation, by routine and day, oldest day first:
    `[{"routine", "day", "items": [Task]}]` (at most `CONFIRM_LIMIT` runs)."""
    waiting = (
        queries.awaiting_review_by(member)
        .filter(queries.ROUTINE_WORK)
        .select_related("template__branch")
        .order_by("for_date", "template__due_time", "template__title", "completed_at", "pk")
    )
    groups: dict[tuple[int, date], dict] = {}
    for task in _run_relations(waiting)[:CONFIRM_LIMIT]:
        key = (task.template_id, task.for_date)
        groups.setdefault(key, {"routine": task.template, "day": task.for_date, "items": []})
        groups[key]["items"].append(task)
    return list(groups.values())
