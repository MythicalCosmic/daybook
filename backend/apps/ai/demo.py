"""Demo data of the AI features (`make demo`): Demo Dorixona has AI on, as its owner's consent
leaves it, with the default agents on; three voice notes (two made into tasks, one waiting) and
the agents' work of the last two days, made through the real services and backdated into
working hours."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Q
from django.utils import timezone

from apps.ai import drafts, events, services
from apps.ai.agents import deadline_watcher, morning_plan, photo_checker
from apps.ai.models import AgentEvent, AIDraft
from apps.tasks.models import Task, TaskComment

# (who speaks, source, what was said, made into tasks, (days ago, hour, minute) or None = just now)
NOTES = (
    (
        "manager",
        AIDraft.Source.BOT,
        "Alisher, ertaga soat 10 gacha muzlatgich haroratini tekshirib, rasmini yubor. "
        "Madina, bugun kechqurun kassani sanab qo‘y.",
        True,
        (1, 9, 14),
    ),
    (
        "manager",
        AIDraft.Source.MINIAPP,
        "Jasur, bugun soat 15 gacha Yunusobod filialiga buyurtmani yetkazib ber.",
        True,
        (1, 14, 40),
    ),
    (
        "owner",
        AIDraft.Source.DASHBOARD,
        "Nigora, ertaga ertalab yaroqlilik muddatini tekshir, rasm bilan. "
        "Madina, javonlarni tartibga keltir.",
        False,
        None,
    ),
)
# When the deadline watcher spoke up and the photo was read: (days ago, hour, minute).
ESCALATIONS = ((2, 16, 5), (1, 11, 0), (1, 15, 30))
PHOTO_AT = (1, 10, 12)
FRIDGE_WORDS = ("muzlatgich", "harorat", "холодильник", "fridge")


def seed(company, people, now) -> None:
    """Add demo rows to `company`. `people` maps owner, manager, worker, madina, jasur
    and nigora to their memberships."""
    services.enable_ai(company, by=people["owner"])
    clock = _Clock(company, now)
    for who, source, text, apply, when in NOTES:
        draft = services.start_draft(people[who], text=text, source=source)
        drafts.process(draft.pk)
        draft.refresh_from_db()
        if apply and draft.status == AIDraft.Status.READY:
            drafts.apply_draft(draft, people[who], refresh=False)
        _backdate_draft(draft, clock.at(*when) if when else now - timedelta(minutes=40))


def finish(company, people, now) -> None:
    """Once every demo has written its work: what the agents said about it."""
    clock = _Clock(company, now)
    _late_work(company, now, clock)
    _morning_plans(company, now, clock)
    _photo_note(company, clock)


class _Clock:
    """Moments of the last days in the company's time; "today" only once it has happened."""

    def __init__(self, company, now):
        self.zone = ZoneInfo(company.timezone)
        self.now = now
        self.today = timezone.localtime(now, self.zone).date()

    def at(self, days_ago: int, hour: int, minute: int) -> datetime:
        day = self.today - timedelta(days=days_ago)
        moment = datetime.combine(day, time(hour, minute), tzinfo=self.zone)
        return moment if moment < self.now else moment - timedelta(days=1)


def _backdate_draft(draft: AIDraft, when: datetime) -> None:
    AIDraft.objects.filter(pk=draft.pk).update(
        created_at=when,
        started_at=when,
        finished_at=when + timedelta(seconds=6),
        applied_at=when + timedelta(minutes=1) if draft.applied_ids else None,
    )
    for event in AgentEvent.objects.filter(subject_type="draft", subject_id=draft.pk):
        later = timedelta(minutes=1) if event.kind.endswith("applied") else timedelta(seconds=6)
        AgentEvent.objects.filter(pk=event.pk).update(created_at=when + later)


def _late_work(company, now, clock: _Clock) -> None:
    """What the deadline watcher said about the demo's late work, marked as escalated so the
    reminders and the real watcher leave those tasks alone."""
    late = (
        Task.objects.for_company(company)
        .filter(
            kind=Task.Kind.ASSIGNED,
            status__in=Task.OPEN_STATUSES,
            due_at__lt=now,
            escalated_at__isnull=True,
            blocked_at__isnull=True,
        )
        .exclude(created_by__isnull=True)
        .select_related("assignee__user", "created_by__user")
        .order_by("due_at")
    )
    for task, when in zip(late[: len(ESCALATIONS)], ESCALATIONS, strict=False):
        Task.objects.filter(pk=task.pk).update(escalated_at=clock.at(*when))
        events.log(
            company,
            deadline_watcher.KEY,
            "escalated",
            params={
                "task": task.title,
                "assignee": str(task.assignee),
                "to": str(task.created_by),
                "hours": max(1, int((now - task.due_at).total_seconds() // 3600)),
            },
            subject=("task", task.pk),
            branch_id=task.branch_id,
            dedupe_key=f"late:{task.pk}",
        )
    escalations = AgentEvent.objects.filter(company=company, agent=deadline_watcher.KEY)
    for event, when in zip(escalations.order_by("pk"), ESCALATIONS, strict=False):
        AgentEvent.objects.filter(pk=event.pk).update(created_at=clock.at(*when))


def _morning_plans(company, now, clock: _Clock) -> None:
    """The last two mornings' plans, for the heads and managers with something to hear."""
    for days_ago in (2, 1):
        sent_at = clock.at(days_ago, 8, 30)
        for person in morning_plan.recipients(company, "both"):
            facts = morning_plan.team_day(person, now)
            if not (facts["due_today"] or facts["late"] or facts["to_check"]):
                continue
            logged = events.log(
                company,
                morning_plan.KEY,
                "plan_sent",
                params={
                    "to": str(person),
                    "due_today": facts["due_today"],
                    "late": len(facts["late"]),
                    "to_check": facts["to_check"],
                },
                subject=("member", person.pk),
                branch_id=person.home_branch_id,
                dedupe_key=f"plan:{person.pk}:{sent_at.date().isoformat()}",
            )
            if logged is not None:
                AgentEvent.objects.filter(pk=logged.pk).update(created_at=sent_at)


def _photo_note(company, clock: _Clock) -> None:
    """A fridge check finished with its photo, read by the photo checker."""
    fridge = Q()
    for word in FRIDGE_WORDS:
        fridge |= Q(title__icontains=word)
    tasks = Task.objects.for_company(company).filter(fridge)
    task = (
        tasks.filter(status__in=(Task.Status.DONE, Task.Status.REVIEW))
        .exclude(proof_photo="")
        .order_by("-completed_at")
        .first()
        or tasks.filter(status__in=(Task.Status.DONE, Task.Status.REVIEW)).first()
        or tasks.first()
    )
    if task is None:
        return
    note = "Muzlatgich 5 °C ko‘rsatmoqda, 2–8 °C oralig‘ida."
    logged = events.log(
        company,
        photo_checker.KEY,
        "looks_right",
        params={"task": task.title, "note": note, "assignee": str(task.assignee)},
        subject=("task", task.pk),
        branch_id=task.branch_id,
        dedupe_key=f"photo:{task.pk}:demo",
    )
    if logged is not None:
        AgentEvent.objects.filter(pk=logged.pk).update(created_at=clock.at(*PHOTO_AT))
        TaskComment.objects.create(task=task, author=None, text=f"AI: {note}")
