"""How each person's shared work went over a period: what managers judge the team by."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q

from apps.companies.models import Company
from apps.members.models import Membership
from apps.reminders.models import ReminderLog
from apps.tasks.models import Task

# Personal tasks are nobody else's business.
SHARED_KINDS = (Task.Kind.DAILY, Task.Kind.ASSIGNED)
# Finished from the assignee's point of view: waiting for a check counts.
FINISHED = (Task.Status.DONE, Task.Status.REVIEW)


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
    def on_time_percent(self) -> int | None:
        return round(100 * self.on_time / self.total) if self.total else None

    @property
    def avg_delay_minutes(self) -> int | None:
        return round(self.avg_delay.total_seconds() / 60) if self.avg_delay else None


@dataclass
class TeamReport:
    start: date
    end: date  # the day after the last
    rows: list[tuple[Membership, Score]]
    totals: Score


def team(company: Company, start: date, end: date, now: datetime) -> TeamReport:
    """Scores for everyone registered, best first. Only deadlines already passed count."""
    tz = ZoneInfo(company.timezone)
    since = datetime.combine(start, time.min, tzinfo=tz)
    until = min(datetime.combine(end, time.min, tzinfo=tz), now)
    shared = Task.objects.for_company(company).filter(kind__in=SHARED_KINDS)
    finished_late = Q(status__in=FINISHED, completed_at__gt=F("due_at"))
    delay = ExpressionWrapper(F("completed_at") - F("due_at"), output_field=DurationField())
    grouped = (
        shared.filter(due_at__gte=since, due_at__lt=until)
        .exclude(status=Task.Status.CANCELLED)
        .values("assignee")
        .annotate(
            on_time=Count("pk", filter=Q(status__in=FINISHED, completed_at__lte=F("due_at"))),
            late=Count("pk", filter=finished_late),
            missed=Count("pk", filter=Q(status__in=Task.OPEN_STATUSES)),
            avg_delay=Avg(delay, filter=finished_late),
        )
    )
    work = {row.pop("assignee"): row for row in grouped}
    late_now = _counts(shared.filter(status__in=Task.OPEN_STATUSES, due_at__lt=now), "assignee")
    reminders = _counts(
        ReminderLog.objects.filter(
            task__company=company,
            kind=ReminderLog.Kind.REMINDER,
            delivered=True,
            sent_at__gte=since,
            sent_at__lt=until,
        ),
        "recipient",
    )
    people = (
        Membership.objects.for_company(company)
        .filter(status=Membership.Status.APPROVED, onboarded_at__isnull=False)
        .select_related("user", "position")
    )
    rows = [
        (
            person,
            Score(
                **work.get(person.pk, {}),
                late_now=late_now.get(person.pk, 0),
                reminders=reminders.get(person.pk, 0),
            ),
        )
        for person in people
    ]
    rows.sort(key=_rank)
    return TeamReport(start, end, rows, _sum(score for _, score in rows))


def _counts(queryset, field: str) -> dict[int, int]:
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
