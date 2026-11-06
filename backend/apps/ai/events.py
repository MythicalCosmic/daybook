"""What the agents did: AgentEvent rows, worded when they are read (v0.2 AI contract §2, §5).

    events.log(company, "deadline_watcher", "escalated", params={...}, subject=("task", 12),
               branch_id=task.branch_id, dedupe_key=f"late:{task.pk}")

`dedupe_key` makes a repeated run harmless: the second event with the same key is not written
(and `log` returns None), which is also how agents know they already did something. The text
comes from the agent's `EventTemplate` for `kind`, in the reader's language.
"""

import logging

from django.db import IntegrityError, transaction
from django.utils import translation

from apps.ai.agents import registry
from apps.ai.models import AgentEvent

logger = logging.getLogger(__name__)


def log(
    company,
    agent: str,
    kind: str,
    *,
    params: dict | None = None,
    actor=None,
    subject: tuple[str, int] | None = None,
    branch_id: int | None = None,
    dedupe_key: str = "",
    level: str | None = None,
) -> AgentEvent | None:
    """Record one event; None when `dedupe_key` was already used in the company."""
    template = registry.event_template(agent, kind)
    if template is None:
        raise ValueError(f"Agent {agent!r} has no event {kind!r}.")
    subject_type, subject_id = subject or ("", None)
    event = AgentEvent(
        company=company,
        agent=agent,
        kind=kind,
        level=level or template.level,
        params=params or {},
        actor=actor,
        subject_type=subject_type,
        subject_id=subject_id,
        branch_id=branch_id,
        dedupe_key=dedupe_key[:96],
    )
    if not dedupe_key:
        event.save()
        return event
    try:
        with transaction.atomic():
            event.save()
    except IntegrityError:
        return None
    return event


def already(company, dedupe_key: str) -> bool:
    return AgentEvent.objects.filter(company=company, dedupe_key=dedupe_key).exists()


def render(event: AgentEvent, language: str | None = None) -> str:
    """The event's sentence in `language` (the active language when None)."""
    template = registry.event_template(event.agent, event.kind)
    if template is None:
        return event.kind
    params = {"count": 0, **(event.params or {})}
    with translation.override(language or translation.get_language()):
        try:
            return str(template.text % params)
        except KeyError, TypeError, ValueError:
            logger.warning("Event %s of %s has params its text can't use", event.pk, event.agent)
            return str(template.text)
