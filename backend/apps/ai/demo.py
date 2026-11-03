"""Demo data of the AI features (`make demo`): Demo Dorixona has AI on, as its owner's consent
leaves it, with the default agents on; three voice notes (two made into tasks, one waiting) and
the agents' work of the last two days, made through the real services and backdated into
working hours. For the agents' own pages: their runs of the last two days and today, and the
Claude calls of the last 30 workdays (AI_FAKE makes none, so they are written as recorded)."""

from collections import Counter
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from apps.ai import drafts, events, pricing, services
from apps.ai.agents import deadline_watcher, hr_assistant, morning_plan, photo_checker, voice_tasks
from apps.ai.models import AgentEvent, AgentRun, AgentState, AIDraft, AIUsage
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
# The agent pages: Claude calls this many days back; runs this many days back (and today).
CALL_DAYS = 30
RUN_DAYS = 2
# The deadline watcher's half hours, 08:00-20:30; the one run that failed (days ago, h, m).
WATCH_FROM, WATCH_UNTIL = time(8, 0), time(20, 30)
WATCH_FAILED = (1, 13, 0)


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
    agent_pages(company, now)


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


def agent_pages(company, now) -> None:
    """What the agents' own pages read. Each workday of the last CALL_DAYS, one to three voice
    notes read by Claude (the drafts model) and a summary by the fast model for each morning
    plan and HR note sent; the scheduled agents that are on ran on their schedule over the last
    RUN_DAYS days and today, each run with what it did (the demo's events) and its calls."""
    zone = ZoneInfo(company.timezone)
    today = timezone.localtime(now, zone).date()
    on = set(AgentState.objects.filter(company=company, enabled=True).values_list("key", flat=True))
    said = list(
        AgentEvent.objects.filter(
            company=company,
            created_at__gte=datetime.combine(today - timedelta(days=RUN_DAYS), time.min, zone),
        ).values_list("agent", "created_at")
    )
    per_day = Counter((agent, timezone.localtime(at, zone).date()) for agent, at in said)
    escalated = [at for agent, at in said if agent == deadline_watcher.KEY]
    calls: list[tuple[AIUsage, datetime]] = []
    runs: list[AgentRun] = []
    for days_ago in range(CALL_DAYS - 1, -1, -1):
        day = today - timedelta(days=days_ago)
        if day.weekday() not in (company.workdays or []):
            continue
        for index in range(1 + days_ago % 3):
            moment = datetime.combine(day, time(10 + 3 * index, 5 + 7 * index), zone)
            calls.append(
                _call(
                    company,
                    voice_tasks.AGENT.usage_features[0],
                    settings.AI_MODEL_DRAFTS,
                    moment,
                    (2300 + 90 * index, 420 + 30 * (days_ago % 4), 5400),
                )
            )
        for key, start in ((morning_plan.KEY, time(8, 30)), (hr_assistant.KEY, time(9, 0))):
            if key not in on:
                continue
            began = datetime.combine(day, start, zone)
            sent = per_day[(key, day)] if days_ago <= RUN_DAYS else 1 + days_ago % 2
            made = [
                _call(
                    company,
                    key,
                    settings.AI_MODEL_FAST,
                    began + timedelta(seconds=2 + 2 * index),
                    (640 + 25 * index, 85 + 10 * index, 1700),
                )
                for index in range(sent)
            ]
            calls += made
            if days_ago <= RUN_DAYS:
                runs.append(_run(company, key, began, made, done=sent, seconds=3 + 2 * sent))
        if deadline_watcher.KEY in on and days_ago <= RUN_DAYS:
            runs += _watcher_runs(company, day, days_ago, zone, escalated)
    calls = [(row, moment) for row, moment in calls if moment < now]
    AIUsage.objects.bulk_create([row for row, _moment in calls])
    for row, moment in calls:  # made "now": backdated one by one
        AIUsage.objects.filter(pk=row.pk).update(created_at=moment)
    AgentRun.objects.bulk_create([run for run in runs if run.finished_at < now])
    for key in on:
        last = AgentRun.objects.filter(company=company, key=key).order_by("-started_at").first()
        if last is not None:
            AgentState.objects.filter(company=company, key=key).update(
                last_run_at=last.started_at, last_status=last.status, last_error=last.error
            )


def _watcher_runs(company, day: date, days_ago: int, zone, escalated: list) -> list[AgentRun]:
    """The deadline watcher's half hours of `day`, each with the late work it passed on."""
    runs = []
    moment = datetime.combine(day, WATCH_FROM, zone)
    while moment.time() <= WATCH_UNTIL:
        told = sum(1 for at in escalated if moment <= at < moment + timedelta(minutes=30))
        if (days_ago, moment.hour, moment.minute) == WATCH_FAILED:
            error = "OperationalError: server closed the connection unexpectedly"
            runs.append(_run(company, deadline_watcher.KEY, moment, [], done=0, error=error))
        else:
            runs.append(_run(company, deadline_watcher.KEY, moment, [], done=told))
        moment += timedelta(minutes=30)
    return runs


def _call(company, feature: str, model: str, moment: datetime, numbers: tuple):
    """One recorded Claude call at `moment`: (input tokens, output tokens, latency in ms)."""
    input_tokens, output_tokens, latency_ms = numbers
    cost = pricing.cost_micro_usd(model, input_tokens=input_tokens, output_tokens=output_tokens)
    row = AIUsage(
        company=company,
        feature=feature,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_micro_usd=cost,
        latency_ms=latency_ms,
        stop_reason="end_turn",
    )
    return row, moment


def _run(
    company, key: str, started: datetime, made: list, *, done: int, seconds: int = 1, error=""
):
    rows = [row for row, _moment in made]
    return AgentRun(
        company=company,
        key=key,
        started_at=started,
        finished_at=started + timedelta(seconds=seconds),
        status=AgentRun.Status.ERROR if error else AgentRun.Status.OK,
        done=done,
        error=error,
        calls=len(rows),
        input_tokens=sum(row.input_tokens for row in rows),
        output_tokens=sum(row.output_tokens for row in rows),
        cost_micro_usd=sum(row.cost_micro_usd for row in rows),
    )
