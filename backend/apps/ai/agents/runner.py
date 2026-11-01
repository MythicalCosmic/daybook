"""Running the scheduled agents (v0.2 AI contract §3).

The beat tick (every 5 minutes, ai queue) runs each enabled agent whose `next_run_at` has
come, in every company whose AI is on; "Run now" runs one at once. A run is claimed first (its
next time moved on under a row lock), so two workers never run the same agent together, and
each agent is idempotent itself (events with a dedupe key), so a repeated run does nothing
twice.
"""

import logging
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.ai import conf
from apps.ai.agents import registry
from apps.ai.models import AgentState

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
            state.last_error = f"{type(exc).__name__}: {exc}"[:200]
            fields = ["next_run_at", "last_run_at", "last_status", "last_error", "updated_at"]
            state.save(update_fields=fields)
            return 0
        state.running_since = now
        state.save(update_fields=["next_run_at", "running_since", "updated_at"])
    company = state.company
    try:
        with transaction.atomic():
            done = agent.run(company, state, now)
        status, error = "ok", ""
    except Exception as exc:
        logger.exception("Agent %s of company %s failed", agent.key, company.pk)
        done, status, error = 0, "error", f"{type(exc).__name__}: {exc}"[:200]
    AgentState.objects.filter(pk=state.pk).update(
        last_run_at=now, last_status=status, last_error=error, running_since=None
    )
    return done


def schedule_first_run(state: AgentState, now: datetime | None = None) -> None:
    """When an agent is switched on: its first run at its next time."""
    agent = registry.get(state.key)
    if agent is None or not agent.scheduled:
        return
    now = now or timezone.now()
    state.next_run_at = agent.next_run(registry.config_of(agent, state), now, state.company)
