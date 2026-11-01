"""Read functions of the AI features, for other apps, the dashboard and the AI tools.

A function returning branch-bound data takes the required keyword
`branch_ids: list[int] | None` (callers pass `apps.members.scope.branch_ids(member)`).

    agent_rows(company)                          the agents as the dashboard lists them
    activity(company, branch_ids=…, agent=…)     what they did, newest first, in pages
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Count, Q
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.ai import agents, events
from apps.ai.models import AgentEvent, AIDraft
from apps.members.models import Membership
from apps.members.queries import photo_url
from apps.tasks.models import Task

ACTIVITY_LIMIT = 100


def agent_rows(company) -> list[dict]:
    from apps.ai.services import agent_unavailable

    zone = ZoneInfo(company.timezone)
    today = datetime.combine(timezone.localtime(timezone.now(), zone).date(), time.min, zone)
    counts = dict(
        AgentEvent.objects.filter(company=company, created_at__gte=today - timedelta(days=6))
        .values_list("agent")
        .annotate(week=Count("pk"))
        .values_list("agent", "week")
    )
    today_counts = dict(
        AgentEvent.objects.filter(company=company, created_at__gte=today)
        .values_list("agent")
        .annotate(today=Count("pk"))
        .values_list("agent", "today")
    )
    rows = []
    for agent in agents.all_agents():
        state = agents.state_of(company, agent.key)
        config = agents.config_of(agent, state)
        reason = agent_unavailable(company, agent)
        rows.append(
            {
                "key": agent.key,
                "name": str(agent.name),
                "description": str(agent.description),
                "icon": agent.icon,
                "enabled": state.enabled,
                "needs_claude": agent.needs_claude,
                "available": reason in ("", "needs_speech"),
                "unavailable_reason": reason,
                "schedule": agent.schedule(config),
                "running": state.running_since is not None
                and timezone.now() - state.running_since < timedelta(minutes=10),
                "last_run_at": state.last_run_at,
                "next_run_at": state.next_run_at if state.enabled and agent.scheduled else None,
                "stats": {
                    "today": today_counts.get(agent.key, 0),
                    "week": counts.get(agent.key, 0),
                },
                "config": config,
                "fields": [_field(item) for item in agent.fields],
            }
        )
    return rows


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
    """{"results": [...], "next_before": id | None}, newest first; an event about something in
    a branch the reader doesn't see is left out (company-wide ones stay)."""
    rows = AgentEvent.objects.filter(company=company).select_related("actor__user")
    if branch_ids is not None:
        rows = rows.filter(Q(branch_id__in=branch_ids) | Q(branch_id__isnull=True))
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
