"""What projects hands the shared registries (registered in `hooks.py`): command palette
search, the Overview activity stream, company calendar dates, private file checks, the time
export and the audit History target. Each applies the caller's project visibility (which
already carries the branch scope, §2.6)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.console import contracts
from apps.console.registry import CalendarItem, SearchHit, StreamItem
from apps.members.models import Membership
from apps.projects import queries
from apps.projects.models import Milestone, Project, ProjectFile, ProjectUpdate


def _url(project: Project, tail: str = "") -> str:
    return f"/c/{project.company_id}/projects/{project.pk}{tail}"


def search(member: Membership, q: str, limit: int) -> list[SearchHit]:
    q = (q or "").strip()
    if not q:
        return []
    projects = (
        queries.visible_projects(member)
        .filter(Q(name__icontains=q) | Q(key__iexact=q) | Q(key__istartswith=q))
        .select_related("lead")
        .order_by("name")[:limit]
    )
    return [
        SearchHit(
            type="projects.project",
            id=project.pk,
            title=f"{project.key} · {project.name}",
            subtitle=" · ".join(
                part for part in (project.get_status_display(), str(project.lead or "")) if part
            ),
            url=_url(project),
        )
        for project in projects
    ]


def _person(member: Membership | None) -> contracts.Person | None:
    if member is None:
        return None
    return {"id": member.pk, "name": str(member)}


def stream(member: Membership, since: datetime | None, limit: int) -> list[StreamItem]:
    """Project updates and finished milestones, newest first."""
    visible = queries.visible_projects(member, archived=True).values("pk")
    updates = ProjectUpdate.objects.filter(project__in=visible).select_related(
        "project", "author__user"
    )
    milestones = Milestone.objects.filter(
        project__in=visible, status=Milestone.Status.DONE, completed_at__isnull=False
    ).select_related("project")
    if since is not None:
        updates = updates.filter(created_at__gt=since)
        milestones = milestones.filter(completed_at__gt=since)
    items = [
        StreamItem(
            at=update.created_at,
            kind="projects.update",
            actor=_person(update.author),
            title=_("%(key)s update: %(health)s")
            % {"key": update.project.key, "health": update.get_health_display()},
            url=_url(update.project, "/updates"),
        )
        for update in updates.order_by("-created_at")[:limit]
    ]
    items += [
        StreamItem(
            at=milestone.completed_at,
            kind="projects.milestone",
            actor=None,
            title=_("%(key)s reached a milestone: %(name)s")
            % {"key": milestone.project.key, "name": milestone.name},
            url=_url(milestone.project, "/milestones"),
        )
        for milestone in milestones.order_by("-completed_at")[:limit]
    ]
    items.sort(key=lambda item: item.at, reverse=True)
    return items[:limit]


def milestones_calendar(company, start: date, end: date, member: Membership) -> list[CalendarItem]:
    if member.company_id != company.pk:
        return []
    visible = queries.visible_projects(member).values("pk")
    rows = (
        Milestone.objects.filter(project__in=visible, due_on__range=(start, end))
        .select_related("project")
        .order_by("due_on", "pk")
    )
    return [
        CalendarItem(
            id=f"milestone-{milestone.pk}",
            kind="projects.milestone",
            title=f"{milestone.project.key} · {milestone.name}",
            start=milestone.due_on,
            end=None,
            all_day=True,
            color=milestone.project.color,
            url=_url(milestone.project, "/milestones"),
        )
        for milestone in rows
    ]


def file_check(user, company_id: int, object_id) -> bool:
    """A project file opens for approved members who may still see its project."""
    member = (
        Membership.objects.select_related("role", "company")
        .filter(user=user, company_id=company_id, status=Membership.Status.APPROVED)
        .first()
    )
    if member is None:
        return False
    row = ProjectFile.objects.filter(pk=object_id, project__company_id=company_id).first()
    return row is not None and queries.can_view(row.project, member)


def history_check(member: Membership, object_id: int) -> bool:
    project = Project.objects.filter(pk=object_id, company_id=member.company_id).first()
    return project is not None and queries.can_view(project, member)


def time_rows(member: Membership, params: dict):
    """The time export: the entries the person may see in a period (default this week)."""
    tz = ZoneInfo(member.company.timezone)
    today = timezone.localtime(timezone.now(), tz).date()
    start, end = queries.week_bounds(today)
    try:
        if params.get("from"):
            start = date.fromisoformat(str(params["from"]))
        if params.get("to"):
            end = date.fromisoformat(str(params["to"]))
    except ValueError:
        pass
    project = None
    if params.get("project"):
        project = (
            queries.visible_projects(member, archived=True).filter(pk=params["project"]).first()
        )
        if project is None:
            return
    people = [int(p) for p in str(params.get("person") or "").split(",") if p.strip().isdigit()]
    for entry in queries.time_entries(
        member, start=start, end=end, project=project, person_ids=people or None
    ).order_by("day", "pk"):
        yield {
            "day": entry.day,
            "person": str(entry.membership),
            "project": entry.project.key if entry.project else "",
            "task": entry.task.title if entry.task else "",
            "minutes": entry.minutes,
            "hours": round(entry.minutes / 60, 2),
            "note": entry.note,
            "billable": entry.billable,
            "source": entry.get_source_display(),
        }
