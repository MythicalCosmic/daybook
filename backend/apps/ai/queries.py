"""Read functions of the AI features, for other apps, the dashboard and the AI tools.

A function returning branch-bound data takes the required keyword
`branch_ids: list[int] | None` (callers pass `apps.members.scope.branch_ids(member)`).

    agent_rows(company)                          the agents as the dashboard lists them
    agent_row(company, key)                      one of them (None: not listed here)
    agent_detail(company, key, can_configure=…)  one agent's page: runs, calls, tokens, next
    activity(company, branch_ids=…, agent=…)     what they did, newest first, in pages
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.ai import agents, conf, events
from apps.ai.agents import runner
from apps.ai.models import AgentEvent, AgentRun, AIDraft, AIUsage
from apps.members.models import Membership
from apps.members.queries import photo_url
from apps.tasks.models import Task

ACTIVITY_LIMIT = 100
# An agent's page: its newest runs and Claude calls, its days of token use, its next runs and
# what it expects next (at most UPCOMING_MAX in all).
RUNS_SHOWN = 30
CALLS_SHOWN = 30
USAGE_DAYS = 30
NEXT_RUNS_SHOWN = 3
UPCOMING_MAX = 6
# A run still "running" this long after it started died with its worker.
STUCK_AFTER = timedelta(hours=1)
# An agent reads as running while its run is queued or going, this long at most.
RUNNING_FOR = timedelta(minutes=10)


def agent_rows(company) -> list[dict]:
    counts = _event_counts(company)
    return [
        _agent_row(company, agent, agents.state_of(company, agent.key), counts, timezone.now())
        for agent in agents.all_agents()
        if agent.works_in(company)
    ]


def agent_row(company, key: str) -> dict | None:
    if (found := _listed(company, key)) is None:
        return None
    agent, state = found
    return _agent_row(company, agent, state, _event_counts(company, key), timezone.now())


def _listed(company, key: str):
    """The agent `key` and the company's state of it, when it is listed for the company."""
    agent = agents.get(key)
    if agent is None or not agent.works_in(company):
        return None
    return agent, agents.state_of(company, key)


def _event_counts(company, key: str | None = None) -> dict[str, tuple[int, int]]:
    """agent -> (its events today, in the last 7 days), in the company's calendar."""
    zone = ZoneInfo(company.timezone)
    today = datetime.combine(timezone.localtime(timezone.now(), zone).date(), time.min, zone)
    rows = AgentEvent.objects.filter(company=company, created_at__gte=today - timedelta(days=6))
    if key is not None:
        rows = rows.filter(agent=key)
    counted = (
        rows.values_list("agent")
        .annotate(today=Count("pk", filter=Q(created_at__gte=today)), week=Count("pk"))
        .values_list("agent", "today", "week")
    )
    return {agent: (today_count, week) for agent, today_count, week in counted}


def _agent_row(company, agent, state, counts: dict, now: datetime) -> dict:
    from apps.ai.services import agent_unavailable

    config = agents.config_of(agent, state)
    reason = agent_unavailable(company, agent)
    today_count, week = counts.get(agent.key, (0, 0))
    return {
        "key": agent.key,
        "name": str(agent.name),
        "description": str(agent.description),
        "icon": agent.icon,
        "enabled": state.enabled,
        "needs_claude": agent.needs_claude,
        "available": reason in ("", "needs_speech"),
        "unavailable_reason": reason,
        "schedule": agent.schedule(config),
        "running": state.running_since is not None and now - state.running_since < RUNNING_FOR,
        "last_run_at": state.last_run_at,
        "next_run_at": state.next_run_at if state.enabled and agent.scheduled else None,
        "stats": {"today": today_count, "week": week},
        "config": config,
        "fields": [_field(item) for item in agent.fields],
    }


def agent_detail(company, key: str, *, can_configure: bool, now: datetime | None = None):
    """One agent's page: its row as the list shows it, plus its newest runs, its newest Claude
    calls, its token use (this month, and each of the last USAGE_DAYS days), what comes next
    and its scene. Money and error texts only for `can_configure` (ai.configure). None for an
    unknown key or an agent not listed for the company."""
    if (found := _listed(company, key)) is None:
        return None
    agent, state = found
    now = now or timezone.now()
    row = _agent_row(company, agent, state, _event_counts(company, key), now)
    if row["running"]:
        scene = "working"
    elif row["enabled"] and row["available"]:
        scene = "idle"
    else:
        scene = "asleep"
    return row | {
        "runs": _runs(company, agent, now, can_configure),
        "calls": _calls(company, agent, can_configure),
        "usage": _usage(company, agent, now, can_configure),
        # An agent that is off or can't work here expects nothing.
        "upcoming": [] if scene == "asleep" else _upcoming(company, agent, state, now),
        "scene": scene,
    }


def _usd(micro_usd: int) -> str:
    """Micro-dollars as dollars, exactly (6 decimals)."""
    return f"{Decimal(micro_usd) / 1_000_000:.6f}"


def _runs(company, agent, now: datetime, can_configure: bool) -> list[dict]:
    rows = AgentRun.objects.filter(company=company, key=agent.key).order_by("-started_at", "-pk")
    found = []
    for run in rows[:RUNS_SHOWN]:
        status, error, finished = run.status, run.error, run.finished_at
        if status == AgentRun.Status.RUNNING and now - run.started_at > STUCK_AFTER:
            status, error = AgentRun.Status.ERROR, _("Did not finish")
        found.append(
            {
                "id": run.pk,
                "started_at": run.started_at,
                "finished_at": finished,
                "duration_ms": None
                if finished is None
                else (finished - run.started_at) // timedelta(milliseconds=1),
                "status": status,
                "forced": run.forced,
                "done": run.done,
                "error": (error or None) if can_configure else None,
                "calls": run.calls,
                "input_tokens": run.input_tokens,
                "output_tokens": run.output_tokens,
                "cost_usd": _usd(run.cost_micro_usd) if can_configure else None,
            }
        )
    return found


def _calls(company, agent, can_configure: bool) -> list[dict]:
    rows = (
        AIUsage.objects.filter(company=company, feature__in=agent.usage_features)
        .order_by("-created_at", "-pk")
        .values(
            "created_at",
            "model",
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "latency_ms",
            "stop_reason",
            "cost_micro_usd",
        )[:CALLS_SHOWN]
    )
    return [
        {
            "at": row["created_at"],
            "model": row["model"],
            "input_tokens": row["input_tokens"],
            "output_tokens": row["output_tokens"],
            "cache_read_tokens": row["cache_read_tokens"],
            "latency_ms": row["latency_ms"],
            "stop_reason": row["stop_reason"],
            "cost_usd": _usd(row["cost_micro_usd"]) if can_configure else None,
        }
        for row in rows
    ]


USAGE_SUMS = ("calls", "input_tokens", "output_tokens", "cache_read_tokens", "cost", "all_cost")


def _usage(company, agent, now: datetime, can_configure: bool) -> dict:
    """The agent's Claude calls summed: this month, and each of the last USAGE_DAYS days (zero
    days too, oldest first), in the company's calendar; and the company's month beside it,
    from the same rows (its share never reads over 100%)."""
    zone = ZoneInfo(company.timezone)
    today = timezone.localtime(now, zone).date()
    first = today - timedelta(days=USAGE_DAYS - 1)
    month = today.replace(day=1)
    mine = Q(feature__in=agent.usage_features)
    per_day: dict[date, dict] = {
        row["day"]: row
        for row in AIUsage.objects.filter(
            company=company, created_at__gte=datetime.combine(min(first, month), time.min, zone)
        )
        .annotate(day=TruncDate("created_at", tzinfo=zone))
        .values("day")
        .annotate(
            calls=Count("pk", filter=mine),
            input_tokens=Sum("input_tokens", filter=mine, default=0),
            output_tokens=Sum("output_tokens", filter=mine, default=0),
            cache_read_tokens=Sum("cache_read_tokens", filter=mine, default=0),
            cost=Sum("cost_micro_usd", filter=mine, default=0),
            all_cost=Sum("cost_micro_usd", default=0),
        )
    }

    def summed(days) -> dict:
        rows = [per_day[day] for day in days if day in per_day]
        return {name: sum(row[name] for row in rows) for name in USAGE_SUMS}

    this_month = summed(day for day in per_day if month <= day <= today)
    days = []
    for offset in range(USAGE_DAYS):
        day = first + timedelta(days=offset)
        numbers = summed([day])
        days.append(
            {
                "date": day,
                "calls": numbers["calls"],
                "input_tokens": numbers["input_tokens"],
                "output_tokens": numbers["output_tokens"],
                "cost_usd": _usd(numbers["cost"]) if can_configure else None,
            }
        )
    company_month = None
    if can_configure:
        company_month = {
            "month_cost_usd": _usd(this_month["all_cost"]),
            "monthly_budget_usd": f"{conf.get_settings(company).monthly_budget_usd:.2f}",
        }
    return {
        "month": {
            "calls": this_month["calls"],
            "input_tokens": this_month["input_tokens"],
            "output_tokens": this_month["output_tokens"],
            "cache_read_tokens": this_month["cache_read_tokens"],
            "cost_usd": _usd(this_month["cost"]) if can_configure else None,
        },
        "days": days,
        "company": company_month,
    }


def _upcoming(company, agent, state, now: datetime) -> list[dict]:
    """Its next scheduled runs and what it expects (its `upcoming` hook): soonest first, the
    ones without a time last."""
    runs = runner.next_runs(agent, state, company, now, NEXT_RUNS_SHOWN) if agent.scheduled else []
    found = [{"at": moment, "kind": "run", "label": _("Scheduled run")} for moment in runs]
    if agent.upcoming is not None:
        found += [
            {"at": at, "kind": "item", "label": str(label)}
            for at, label in agent.upcoming(company, state, now)
        ]
    found.sort(key=lambda item: (item["at"] is None, item["at"] or now))
    return found[:UPCOMING_MAX]


def _field(item: agents.Field) -> dict:
    out = {"key": item.key, "type": item.type, "label": str(item.label), "help": str(item.help)}
    if item.min is not None:
        out["min"] = item.min
    if item.max is not None:
        out["max"] = item.max
    if item.unit is not None:
        out["unit"] = str(item.unit)
    if item.options:
        out["options"] = [{"value": value, "label": str(label)} for value, label in item.options]
    return out


def activity(
    company,
    *,
    branch_ids: list[int] | None,
    agent: str | None = None,
    limit: int = 30,
    before: int | None = None,
) -> dict:
    """{"results": [...], "next_before": id | None}, newest first. For someone who sees only
    some branches, an event about something (a task, a person, a voice note) is shown only when
    it happens in one of them: like every row without a branch (apps.members.scope), one about
    company-wide work or a person without a branch is for those who see every branch. Events
    about nothing in particular stay."""
    rows = AgentEvent.objects.filter(company=company).select_related("actor__user")
    if branch_ids is not None:
        rows = rows.filter(Q(branch_id__in=branch_ids) | Q(subject_type=""))
    if agent:
        rows = rows.filter(agent=agent)
    if before:
        rows = rows.filter(pk__lt=before)
    limit = max(1, min(limit, ACTIVITY_LIMIT))
    page = list(rows.order_by("-pk")[: limit + 1])
    more = len(page) > limit
    page = page[:limit]
    labels = _subject_labels(company, page)
    results = []
    for event in page:
        spec = agents.get(event.agent)
        subject = None
        if event.subject_type and event.subject_id:
            subject = {
                "type": event.subject_type,
                "id": event.subject_id,
                "label": labels.get((event.subject_type, event.subject_id), ""),
            }
        results.append(
            {
                "id": event.pk,
                "agent": event.agent,
                "agent_name": str(spec.name) if spec else event.agent,
                "icon": spec.icon if spec else "sparkles",
                "kind": event.kind,
                "level": event.level,
                "text": events.render(event),
                "created_at": event.created_at,
                "actor": _person(event.actor) if event.actor_id else None,
                "subject": subject,
            }
        )
    return {"results": results, "next_before": page[-1].pk if more and page else None}


def _person(member: Membership) -> dict:
    return {"id": member.pk, "name": str(member), "photo": photo_url(member)}


def _subject_labels(company, page: list[AgentEvent]) -> dict[tuple[str, int], str]:
    wanted: dict[str, set[int]] = {}
    for event in page:
        if event.subject_type and event.subject_id:
            wanted.setdefault(event.subject_type, set()).add(event.subject_id)
    labels = {}
    if ids := wanted.get("task"):
        for pk, title in Task.objects.filter(company=company, pk__in=ids).values_list(
            "pk", "title"
        ):
            labels[("task", pk)] = title
    if ids := wanted.get("member"):
        for person in Membership.objects.filter(company=company, pk__in=ids).select_related("user"):
            labels[("member", person.pk)] = str(person)
    if ids := wanted.get("draft"):
        for draft in AIDraft.objects.filter(company=company, pk__in=ids).select_related(
            "created_by__user"
        ):
            labels[("draft", draft.pk)] = _("Voice note · %(name)s") % {
                "name": str(draft.created_by)
            }
    return labels
