"""Tasks and routines a page can be linked to ("How to do this").

The tasks app owns both, and both are read through its contract: tasks with
`tasks.queries.visible_tasks` (the person's visibility and branch scope), routines with
`tasks.queries.routines` / `routine` (the company's shared routines).
"""

from __future__ import annotations

from dataclasses import dataclass

from django.utils import timezone

from apps.members.models import Membership


@dataclass(frozen=True)
class Target:
    type: str  # "task" | "routine"
    id: int
    title: str
    subtitle: str


def title(
    company_id: int, target_type: str, target_id: int, *, by: Membership | None
) -> str | None:
    """The title of the task (one `by` may see) or routine, or None when there is none."""
    if target_type == "task":
        from apps.tasks.queries import visible_tasks

        if by is None:
            return None
        return visible_tasks(by).filter(pk=target_id).values_list("title", flat=True).first()
    if target_type == "routine":
        from apps.tasks.queries import routine

        found = routine(company_id, target_id)
        return found.title if found is not None else None
    return None


def _task_subtitle(task) -> str:
    """Whose task it is and the day it is due: tasks often share a title."""
    parts = [task.assignee.full_name] if task.assignee_id else []
    if task.due_at:
        parts.append(timezone.localtime(task.due_at).strftime("%d.%m"))
    return " · ".join(part for part in parts if part) or f"#{task.pk}"


def search(member: Membership, q: str, *, limit: int = 8) -> list[Target]:
    """Routines and tasks whose title holds `q` (routines first: they are linked the most).

    Tasks a routine made are left out: linking the routine covers every one of them.
    """
    from apps.tasks.queries import routines, visible_tasks

    q = (q or "").strip()
    tasks = (
        visible_tasks(member)
        .exclude(kind="personal")
        .filter(template__isnull=True)
        .select_related("assignee")
    )
    if q:
        tasks = tasks.filter(title__icontains=q)
    found = [
        Target("routine", row.pk, row.title, row.due_time.strftime("%H:%M"))
        for row in routines(member.company_id, q=q, active=True)[:limit]
    ]
    rest = max(0, limit - len(found))
    found += [
        Target("task", row.pk, row.title, _task_subtitle(row))
        for row in tasks.order_by("-created_at")[:rest]
    ]
    return found


def visible_links(member: Membership, links) -> list:
    """The links `member` may see: routines (company-wide) always, tasks only when `member`
    may see the task, so a link never shows the title of someone else's task."""
    links = list(links)
    task_ids = {link.target_id for link in links if link.target_type == "task"}
    if not task_ids:
        return links
    from apps.tasks.queries import visible_tasks

    seen = set(visible_tasks(member).filter(pk__in=task_ids).values_list("pk", flat=True))
    return [link for link in links if link.target_type != "task" or link.target_id in seen]
