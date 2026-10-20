"""Tasks and routines a page can be linked to ("How to do this").

The tasks app owns both. Tasks are read through its contract (`tasks.queries.visible_tasks`,
which applies the person's visibility and branch scope); routines have no query function yet,
so their titles are read here, read-only and company-scoped. Package B may replace that with a
`tasks.queries` function at integration.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.members.models import Membership


@dataclass(frozen=True)
class Target:
    type: str  # "task" | "routine"
    id: int
    title: str
    subtitle: str


def _routines(company_id: int):
    from apps.tasks.models import TaskTemplate

    return TaskTemplate.objects.filter(company_id=company_id, personal=False)


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
        return _routines(company_id).filter(pk=target_id).values_list("title", flat=True).first()
    return None


def search(member: Membership, q: str, *, limit: int = 8) -> list[Target]:
    """Routines and tasks whose title holds `q` (routines first: they are linked the most)."""
    from apps.tasks.queries import visible_tasks

    q = (q or "").strip()
    routines = _routines(member.company_id).filter(is_active=True)
    tasks = visible_tasks(member).exclude(kind="personal")
    if q:
        routines = routines.filter(title__icontains=q)
        tasks = tasks.filter(title__icontains=q)
    found = [
        Target("routine", row.pk, row.title, row.due_time.strftime("%H:%M"))
        for row in routines.order_by("title")[:limit]
    ]
    rest = max(0, limit - len(found))
    found += [
        Target("task", row.pk, row.title, f"#{row.pk}")
        for row in tasks.order_by("-created_at")[:rest]
    ]
    return found
