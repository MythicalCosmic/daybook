"""Running the scheduled agents (v0.2 AI contract §3).

The beat tick (every 5 minutes, ai queue) runs each enabled agent whose `next_run_at` has
come, in every company whose AI is on; "Run now" runs one at once. A run is claimed first (its
next time moved on under a row lock), so two workers never run the same agent together, and
each agent is idempotent itself (events with a dedupe key), so a repeated run does nothing
twice.

Every run is recorded (`AgentRun`, the agent page's log): made "running" when it is claimed,
finished with what it did, its error, and the calls, tokens and money of the Claude calls its
usage features made meanwhile; one whose next time can't be worked out is recorded as an
error. The newest `AgentRun.RUNS_KEPT` of each agent stay.
"""

import logging
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.ai import conf
from apps.ai.agents import registry
from apps.ai.models import AgentRun, AgentState, AIUsage

logger = logging.getLogger(__name__)

# An agent whose next time can't be worked out (a setting it can't read) is tried this much later.
RETRY_UNSCHEDULABLE = timedelta(hours=1)


def scheduled_keys() -> list[str]:
    return [agent.key for agent in registry.all_agents() if agent.scheduled]


def tick(now: datetime | None = None) -> int:
    """Run what is due; how many things the agents did."""
    now = now or timezone.now()
    due = (
        AgentState.objects.filter(enabled=True, key__in=scheduled_keys())
        .filter(Q(next_run_at__isnull=True) | Q(next_run_at__lte=now))
        .select_related("company")
    )
    done = 0
    for state in due:
        if state.company.is_active and conf.ai_on(state.company):
            try:
                done += run_state(state.pk, now)
            except Exception:  # one agent's trouble never stops the others
                logger.exception("Agent state %s could not run", state.pk)
    return done


def run_state(state_id: int, now: datetime | None = None, *, forced: bool = False) -> int:
    now = now or timezone.now()
    with transaction.atomic():
        state = (
            AgentState.objects.select_for_update(skip_locked=True)
            .select_related("company")
            .filter(pk=state_id)
            .first()
        )
        if state is None:
            return 0  # another worker holds it
        agent = registry.get(state.key)
        if agent is None or not agent.scheduled:
            return 0
        if not forced and (not state.enabled or (state.next_run_at and state.next_run_at > now)):
            return 0
        config = registry.config_of(agent, state)
        try:
            state.next_run_at = agent.next_run(config, now, state.company)
        except Exception as exc:  # a stored setting it can't read: recorded, tried again later
            logger.exception("Agent %s of company %s has no next time", agent.key, state.company_id)
            state.next_run_at = now + RETRY_UNSCHEDULABLE
            state.last_run_at, state.last_status = now, "error"
            state.last_error = _error(exc)
            fields = ["next_run_at", "last_run_at", "last_status", "last_error", "updated_at"]
            state.save(update_fields=fields)
            moment = timezone.now()
            AgentRun.objects.create(
                company=state.company,
                key=agent.key,
                started_at=moment,
                finished_at=moment,
                status=AgentRun.Status.ERROR,
                forced=forced,
                error=state.last_error,
            )
            prune(state.company_id, agent.key)
            return 0
        state.running_since = now
        state.save(update_fields=["next_run_at", "running_since", "updated_at"])
        record = AgentRun.objects.create(
            company=state.company, key=agent.key, started_at=timezone.now(), forced=forced
        )
    company = state.company
    try:
        with transaction.atomic():
            done = agent.run(company, state, now)
        status, error = AgentRun.Status.OK, ""
    except Exception as exc:
        logger.exception("Agent %s of company %s failed", agent.key, company.pk)
        done, status, error = 0, AgentRun.Status.ERROR, _error(exc)
    AgentState.objects.filter(pk=state.pk).update(
        last_run_at=now, last_status=status, last_error=error, running_since=None
    )
    _finish(record, agent, status=status, done=done, error=error)
    return done


def _error(exc: Exception) -> str:
    """An exception as the short text a failed run keeps."""
    return f"{type(exc).__name__}: {exc}"[:200]


def _finish(record: AgentRun, agent, *, status: str, done: int, error: str) -> None:
    """The run's end: what it did, and the Claude calls of its usage features made since it
    started, summed."""
    finished = timezone.now()
    used = AIUsage.objects.filter(
        company_id=record.company_id,
        feature__in=agent.usage_features,
        created_at__gte=record.started_at,
        created_at__lte=finished,
    ).aggregate(
        calls=Count("pk"),
        input_tokens=Sum("input_tokens", default=0),
        output_tokens=Sum("output_tokens", default=0),
        cost=Sum("cost_micro_usd", default=0),
    )
    AgentRun.objects.filter(pk=record.pk).update(
        finished_at=finished,
        status=status,
        done=done,
        error=error,
        calls=used["calls"],
        input_tokens=used["input_tokens"],
        output_tokens=used["output_tokens"],
        cost_micro_usd=used["cost"],
    )
    prune(record.company_id, record.key)


def prune(company_id: int, key: str) -> int:
    """Keep an agent's newest `AgentRun.RUNS_KEPT` runs; how many older ones went."""
    older = list(
        AgentRun.objects.filter(company_id=company_id, key=key)
        .order_by("-started_at", "-pk")
        .values_list("pk", flat=True)[AgentRun.RUNS_KEPT :]
    )
    if not older:
        return 0
    return AgentRun.objects.filter(pk__in=older).delete()[0]


def next_runs(agent, state: AgentState, company, now: datetime, count: int) -> list[datetime]:
    """When a scheduled agent runs next, `count` times: its stored next time (one already due
    reads as `now`: the next tick takes it), then its schedule stepped on. None at all when
    its next time can't be worked out (a setting it can't read)."""
    config = registry.config_of(agent, state)
    try:
        moment = max(state.next_run_at or agent.next_run(config, now, company), now)
        found = [moment]
        while len(found) < count:
            moment = agent.next_run(config, moment, company)
            found.append(moment)
    except Exception:
        logger.info("Agent %s of company %s has no next time", agent.key, company.pk)
        return []
    return found


def schedule_first_run(state: AgentState, now: datetime | None = None) -> None:
    """When an agent is switched on: its first run at its next time."""
    agent = registry.get(state.key)
    if agent is None or not agent.scheduled:
        return
    now = now or timezone.now()
    state.next_run_at = agent.next_run(registry.config_of(agent, state), now, state.company)
