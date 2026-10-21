"""How shared work went over a period: what managers judge the team by.

Only deadlines already passed count; personal tasks never count (they are nobody else's
business); a task waiting for a check counts as finished. Every function takes the required
keyword `branch_ids` (docs/PLAN-OWNER.md §2.6): None for every branch, otherwise only tasks
of those branches (by `Task.branch`) and, for people lists, people working in them.

`team(company, start, end, now)` takes `end` as the day after the last (the bot's weekly
report and the mini app's team results); the owner console's `team_grouped`, `trend` and
`routine_compliance` take the last day itself, like `apps.reports.periods.Range`.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.companies.models import Company
from apps.members.models import Membership
from apps.members.scope import restrict
from apps.reminders.models import ReminderLog
from apps.tasks.models import Task, TaskTemplate

# Personal tasks are nobody else's business.
SHARED_KINDS = (Task.Kind.DAILY, Task.Kind.ASSIGNED)
# Finished from the assignee's point of view: waiting for a check counts.
FINISHED = (Task.Status.DONE, Task.Status.REVIEW)
GROUPS = ("member", "position", "routine", "day", "branch")
TREND_GROUPS = ("day", "week", "month")
METRICS = ("on_time_percent", "done", "on_time", "late", "missed", "total")


@dataclass
class Score:
    on_time: int = 0
    late: int = 0
    missed: int = 0  # still open after the deadline
    late_now: int = 0  # open and overdue right now, whenever it was due
    reminders: int = 0
    avg_delay: timedelta | None = None  # of the work finished late

    @property
    def total(self) -> int:
        return self.on_time + self.late + self.missed

    @property
    def done(self) -> int:
        return self.on_time + self.late

    @property
    def on_time_percent(self) -> int | None:
        return round(100 * self.on_time / self.total) if self.total else None

    @property
    def on_time_exact(self) -> float | None:
        """The on-time share with one decimal, for charts and comparisons."""
        return round(100 * self.on_time / self.total, 1) if self.total else None

    @property
    def avg_delay_minutes(self) -> int | None:
        return round(self.avg_delay.total_seconds() / 60) if self.avg_delay else None

    def as_dict(self) -> dict:
        return {
            "total": self.total,
            "done": self.done,
            "on_time": self.on_time,
            "late": self.late,
            "missed": self.missed,
            "on_time_percent": self.on_time_exact,
            "late_now": self.late_now,
            "reminders": self.reminders,
            "avg_delay_minutes": self.avg_delay_minutes,
        }


@dataclass
class TeamReport:
    start: date
    end: date  # the day after the last
    rows: list[tuple[Membership, Score]]
    totals: Score


@dataclass
class Row:
    """One group of `team_grouped`: a person, a position, a routine, a branch or a day."""

    key: str
    label: str
    score: Score
    member: Membership | None = None
    extra: dict = field(default_factory=dict)


def _window(
    company: Company, start: date, end_exclusive: date, now: datetime
) -> tuple[datetime, datetime]:
    tz = ZoneInfo(company.timezone)
    since = datetime.combine(start, time.min, tzinfo=tz)
    until = min(datetime.combine(end_exclusive, time.min, tzinfo=tz), now)
    return since, until


def _shared(company: Company, branch_ids: list[int] | None):
    tasks = Task.objects.for_company(company).filter(kind__in=SHARED_KINDS)
    if branch_ids is not None:
        tasks = tasks.filter(branch_id__in=branch_ids)
    return tasks


def _people(company: Company, branch_ids: list[int] | None):
    people = Membership.objects.for_company(company).filter(
        status=Membership.Status.APPROVED, onboarded_at__isnull=False
    )
    return restrict(people, branch_ids, field="branches").select_related("user", "position")


_FINISHED_LATE = Q(status__in=FINISHED, completed_at__gt=F("due_at"))
_DELAY = ExpressionWrapper(F("completed_at") - F("due_at"), output_field=DurationField())
_SCORES = {
    "on_time": Count("pk", filter=Q(status__in=FINISHED, completed_at__lte=F("due_at"))),
    "late": Count("pk", filter=_FINISHED_LATE),
    "missed": Count("pk", filter=Q(status__in=Task.OPEN_STATUSES)),
    "avg_delay": Avg(_DELAY, filter=_FINISHED_LATE),
}


def team(
    company: Company,
    start: date,
    end: date,
    now: datetime,
    *,
    branch_ids: list[int] | None,
) -> TeamReport:
    """Scores for everyone registered (in `branch_ids`' people; None for the whole company),
    best first, from `start` to the day before `end`. Callers serving a person pass their
    scope (`members.scope.branch_ids`)."""
    since, until = _window(company, start, end, now)
    shared = _shared(company, branch_ids)
    grouped = (
        shared.filter(due_at__gte=since, due_at__lt=until)
        .exclude(status=Task.Status.CANCELLED)
        .values("assignee")
        .annotate(**_SCORES)
    )
    work = {row.pop("assignee"): row for row in grouped}
    late_now = _counts(shared.filter(status__in=Task.OPEN_STATUSES, due_at__lt=now), "assignee")
    reminders = _counts(_reminders(company, since, until, branch_ids), "recipient")
    rows = [
        (
            person,
            Score(
                **work.get(person.pk, {}),
                late_now=late_now.get(person.pk, 0),
                reminders=reminders.get(person.pk, 0),
            ),
        )
        for person in _people(company, branch_ids)
    ]
    rows.sort(key=_rank)
    return TeamReport(start, end, rows, _sum(score for _, score in rows))


def team_grouped(
    company: Company,
    start: date,
    end: date,
    now: datetime,
    group_by: str,
    *,
    branch_ids: list[int] | None,
) -> list[Row]:
    """Scores from `start` to `end` (both inclusive) grouped by member, position, routine,
    branch or day. Members: everyone registered in scope, best first (like `team`); the other
    groups list only what had work, best on-time rate first (days in order)."""
    if group_by not in GROUPS:
        raise ValueError(f"group_by must be one of {GROUPS}")
    if group_by == "member":
        report = team(company, start, end + timedelta(days=1), now, branch_ids=branch_ids)
        return [
            Row(str(person.pk), str(person), score, member=person, extra=_member_extra(person))
            for person, score in report.rows
        ]
    since, until = _window(company, start, end + timedelta(days=1), now)
    shared = _shared(company, branch_ids)
    window = shared.filter(due_at__gte=since, due_at__lt=until).exclude(
        status=Task.Status.CANCELLED
    )
    if group_by == "day":
        return _by_day(company, window, start, end, since, until, branch_ids)
    path, label_of = {
        "position": ("assignee__position", _position_labels),
        "routine": ("template", _routine_labels),
        "branch": ("branch", _branch_labels),
    }[group_by]
    grouped = list(window.values(path).annotate(**_SCORES))
    late_now = _counts(shared.filter(status__in=Task.OPEN_STATUSES, due_at__lt=now), path)
    reminders = _counts(_reminders(company, since, until, branch_ids), f"task__{path}")
    labels = label_of(company, [row[path] for row in grouped])
    rows = []
    for row in grouped:
        key = row.pop(path)
        rows.append(
            Row(
                "none" if key is None else str(key),
                labels.get(key, ""),
                Score(**row, late_now=late_now.get(key, 0), reminders=reminders.get(key, 0)),
            )
        )
    rows.sort(key=lambda r: (r.score.total == 0, -(r.score.on_time_exact or 0), r.label.lower()))
    return rows


def trend(
    company: Company,
    metric: str,
    start: date,
    end: date,
    group_by: str,
    *,
    branch_ids: list[int] | None,
) -> list[dict]:
    """The team's numbers per day, week (from Monday) or month from `start` to `end` (both
    inclusive): `[{"date", "total", "done", "on_time", "late", "missed", "on_time_percent"}]`,
    `metric` among them. Periods with nothing due have zeros and a None percent."""
    if metric not in METRICS:
        raise ValueError(f"metric must be one of {METRICS}")
    if group_by not in TREND_GROUPS:
        raise ValueError(f"group_by must be one of {TREND_GROUPS}")
    now = timezone.now()
    since, until = _window(company, start, end + timedelta(days=1), now)
    tz = ZoneInfo(company.timezone)
    rows = (
        _shared(company, branch_ids)
        .filter(due_at__gte=since, due_at__lt=until)
        .exclude(status=Task.Status.CANCELLED)
        .values_list("due_at", "status", "completed_at")
    )
    buckets: dict[date, Score] = defaultdict(Score)
    for due_at, status, completed_at in rows:
        score = buckets[_period(timezone.localtime(due_at, tz).date(), group_by)]
        if status in FINISHED and completed_at is not None:
            if completed_at <= due_at:
                score.on_time += 1
            else:
                score.late += 1
        else:
            score.missed += 1
    out = []
    period = _period(start, group_by)
    while period <= end:
        score = buckets.get(period, Score())
        out.append(
            {
                "date": period,
                "total": score.total,
                "done": score.done,
                "on_time": score.on_time,
                "late": score.late,
                "missed": score.missed,
                "on_time_percent": score.on_time_exact,
            }
        )
        period = _next_period(period, group_by)
    return out


def routine_compliance(
    company: Company, start: date, end: date, *, branch_ids: list[int] | None
) -> list[dict]:
    """Every routine with what it made from `start` to `end` (both inclusive): made, on time,
    late, missed, the on-time and completion %, and how many people did it. Active routines
    that made nothing are listed too: a routine nobody does is worth seeing."""
    now = timezone.now()
    since, until = _window(company, start, end + timedelta(days=1), now)
    templates = TaskTemplate.objects.for_company(company).filter(personal=False, onboarding=False)
    if branch_ids is not None:
        templates = templates.filter(branch_id__in=branch_ids)
    templates = {t.pk: t for t in templates.select_related("branch")}
    grouped = (
        _shared(company, branch_ids)
        .filter(template_id__in=templates, due_at__gte=since, due_at__lt=until)
        .exclude(status=Task.Status.CANCELLED)
        .values("template")
        .annotate(**_SCORES, people=Count("assignee", distinct=True))
    )
    found = {row.pop("template"): row for row in grouped}
    out = []
    for pk, template in templates.items():
        row = found.get(pk)
        if row is None and not template.is_active:
            continue
        people = row.pop("people") if row else 0
        score = Score(**(row or {}))
        out.append(
            {
                "id": pk,
                "title": template.title,
                "is_active": template.is_active,
                "branch": template.branch.name if template.branch_id else None,
                "made": score.total,
                "on_time": score.on_time,
                "late": score.late,
                "missed": score.missed,
                "on_time_percent": score.on_time_exact,
                "completion_percent": round(100 * score.done / score.total, 1)
                if score.total
                else None,
                "people": people,
            }
        )
    out.sort(
        key=lambda r: (
            r["made"] == 0,
            r["on_time_percent"] if r["on_time_percent"] is not None else 101,
            r["title"].lower(),
        )
    )
    return out


def sum_rows(rows: list[Row]) -> Score:
    return _sum(row.score for row in rows)


# Helpers -----------------------------------------------------------------------------------


def _reminders(company: Company, since: datetime, until: datetime, branch_ids):
    logs = ReminderLog.objects.filter(
        task__company=company,
        task__kind__in=SHARED_KINDS,
        kind=ReminderLog.Kind.REMINDER,
        delivered=True,
        sent_at__gte=since,
        sent_at__lt=until,
    )
    if branch_ids is not None:
        logs = logs.filter(task__branch_id__in=branch_ids)
    return logs


def _by_day(company, window, start, end, since, until, branch_ids) -> list[Row]:
    tz = ZoneInfo(company.timezone)
    grouped = window.annotate(day=TruncDate("due_at", tzinfo=tz)).values("day").annotate(**_SCORES)
    work = {row.pop("day"): row for row in grouped}
    reminders = dict(
        _reminders(company, since, until, branch_ids)
        .annotate(day=TruncDate("sent_at", tzinfo=tz))
        .values("day")
        .annotate(n=Count("pk"))
        .values_list("day", "n")
    )
    rows = []
    day = start
    while day <= end:
        rows.append(
            Row(
                day.isoformat(),
                day.isoformat(),
                Score(**work.get(day, {}), reminders=reminders.get(day, 0)),
            )
        )
        day += timedelta(days=1)
    return rows


def _member_extra(person: Membership) -> dict:
    return {"position": person.position.name if person.position_id else None}


def _position_labels(company, keys) -> dict:
    from apps.members.models import Position

    names = dict(
        Position.objects.for_company(company)
        .filter(pk__in=[k for k in keys if k])
        .values_list("pk", "name")
    )
    return names | {None: ""}


def _routine_labels(company, keys) -> dict:
    names = dict(
        TaskTemplate.objects.for_company(company)
        .filter(pk__in=[k for k in keys if k])
        .values_list("pk", "title")
    )
    return names | {None: ""}


def _branch_labels(company, keys) -> dict:
    names = dict(company.branches.filter(pk__in=[k for k in keys if k]).values_list("pk", "name"))
    return names | {None: ""}


def _period(day: date, group_by: str) -> date:
    if group_by == "week":
        return day - timedelta(days=day.weekday())
    if group_by == "month":
        return day.replace(day=1)
    return day


def _next_period(day: date, group_by: str) -> date:
    if group_by == "week":
        return day + timedelta(days=7)
    if group_by == "month":
        return (day + timedelta(days=32)).replace(day=1)
    return day + timedelta(days=1)


def _counts(queryset, field: str) -> dict:
    return dict(queryset.values(field).annotate(n=Count("pk")).values_list(field, "n"))


def _rank(row: tuple[Membership, Score]):
    person, score = row
    # People with work come first, best on-time rate first; then whoever is late right now.
    return (score.total == 0, -(score.on_time_percent or 0), score.late_now, str(person))


def _sum(scores) -> Score:
    total = Score()
    delay = timedelta()
    for score in scores:
        total.on_time += score.on_time
        total.late += score.late
        total.missed += score.missed
        total.late_now += score.late_now
        total.reminders += score.reminders
        if score.avg_delay:
            delay += score.avg_delay * score.late
    total.avg_delay = delay / total.late if total.late else None
    return total
