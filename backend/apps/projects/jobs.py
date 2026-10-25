"""The work behind the projects' Celery jobs (plain functions, so tests call them directly).

- `watch_health`: a project turning off track, and a milestone whose date passed while still
  open, are told once to the project's lead and the people who see every project
  (`projects.view_all`, in their branch scope), through the owner bot when they started it.
- `nudge_leads`: once a week, on the company's nudge day after 10:00 local time, leads of live
  projects without an update in the last week are asked how it's going (one tap posts it).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings as django_settings
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.companies.models import Company
from apps.inbox import services as inbox
from apps.inbox.services import NotificationAction
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import members_with_perm
from apps.members.scope import allows, branch_ids
from apps.projects import conf, queries
from apps.projects.models import Health, Milestone, Project, ProjectUpdate

NUDGE_HOUR = 10
log = logging.getLogger(__name__)


def watchers(project: Project) -> list[Membership]:
    """Who hears about a project in trouble: its lead and the `projects.view_all` holders
    whose branch scope covers it."""
    people = {}
    if project.lead is not None and project.lead.status == Membership.Status.APPROVED:
        people[project.lead.pk] = project.lead
    for member in (
        members_with_perm(project.company, Perm.PROJECTS_VIEW_ALL)
        .select_related("user", "role", "company")
        .prefetch_related("branches")
    ):
        if member.has_perm(Perm.DASHBOARD_ACCESS) and allows(branch_ids(member), project.branch_id):
            people[member.pk] = member
    return list(people.values())


def _live_projects():
    return Project.objects.filter(
        company__is_active=True,
        archived_at__isnull=True,
        status__in=Project.LIVE_STATUSES,
    ).select_related("company", "lead__user", "lead__role", "lead__company")


def watch_health(now: datetime | None = None) -> int:
    """Tell watchers about projects that went off track and milestones that were missed.
    Returns how many alerts went out."""
    now = now or timezone.now()
    sent = 0
    by_company: dict[int, list[Project]] = {}
    for project in _live_projects():
        by_company.setdefault(project.company_id, []).append(project)
    for company_id, projects in by_company.items():
        try:
            sent += _watch_company(projects, now)
        except Exception:  # one company's bad data must not stop the others' alerts
            log.exception("projects.watch_health failed for company %s", company_id)
    sent += _alert_missed_milestones(now)
    return sent


def _watch_company(projects: list[Project], now: datetime) -> int:
    sent = 0
    facts = queries.summaries(projects, now=now)
    for project in projects:
        state = facts[project.pk]["health"] or ""
        if state == project.health:
            continue
        with transaction.atomic():
            Project.objects.filter(pk=project.pk).update(health=state)
            if state == Health.OFF_TRACK:
                sent += _alert_off_track(project, facts[project.pk], now)
    return sent


def _alert_off_track(project: Project, facts: dict, now: datetime) -> int:
    reasons = []
    if facts["overdue_milestones"]:
        reasons.append(_("a milestone is overdue"))
    if facts["budget_base"] is not None and facts["spent"] > facts["budget_base"]:
        reasons.append(_("spending is over the budget"))
    if project.due_on is not None and project.due_on < queries.local_today(project.company, now):
        reasons.append(_("the due date has passed"))
    why = ", ".join(str(r) for r in reasons)
    created = inbox.notify(
        watchers(project),
        "projects.off_track",
        title=lambda person: _("%(key)s is off track") % {"key": project.key},
        body=lambda person: (
            _("%(name)s: %(why)s.") % {"name": project.name, "why": why} if why else project.name
        ),
        url=f"/c/{project.company_id}/projects/{project.pk}",
        target=project,
        dedupe_key=f"projects.off_track:{project.pk}:{queries.local_today(project.company, now)}",
    )
    return len(created)


def _alert_missed_milestones(now: datetime) -> int:
    sent = 0
    milestones = (
        Milestone.objects.filter(
            status=Milestone.Status.OPEN,
            due_on__isnull=False,
            missed_notified_at__isnull=True,
            project__archived_at__isnull=True,
            project__status__in=Project.LIVE_STATUSES,
            project__company__is_active=True,
        )
        .select_related("project__company", "project__lead__user", "project__lead__role")
        .order_by("pk")
    )
    for milestone in milestones:
        project = milestone.project
        if milestone.due_on >= queries.local_today(project.company, now):
            continue
        with transaction.atomic():
            updated = Milestone.objects.filter(
                pk=milestone.pk, missed_notified_at__isnull=True
            ).update(missed_notified_at=now)
            if not updated:
                continue
            created = inbox.notify(
                watchers(project),
                "projects.milestone_missed",
                title=lambda person, m=milestone, p=project: (
                    _("Missed milestone: %(name)s") % {"name": m.name}
                ),
                body=lambda person, m=milestone, p=project: (
                    _("%(key)s · %(project)s was due %(day)s.")
                    % {"key": p.key, "project": p.name, "day": m.due_on.strftime("%d.%m")}
                ),
                url=f"/c/{project.company_id}/projects/{project.pk}/milestones",
                target=project,
                dedupe_key=f"projects.milestone_missed:{milestone.pk}",
            )
            sent += len(created)
    return sent


def nudge_leads(now: datetime | None = None) -> int:
    """Ask leads of live projects for their weekly update. Returns how many were asked."""
    now = now or timezone.now()
    asked = 0
    for company in Company.objects.filter(is_active=True):
        settings = conf.get_settings(company)
        local = timezone.localtime(now, ZoneInfo(company.timezone))
        if not settings.weekly_nudge or local.weekday() != settings.nudge_weekday:
            continue
        if local.hour < NUDGE_HOUR:
            continue
        today = local.date()
        week_ago = now - timedelta(days=6)
        projects = (
            _live_projects()
            .filter(company=company, lead__isnull=False, status=Project.Status.ACTIVE)
            .exclude(update_nudged_on=today)
        )
        for project in projects:
            if ProjectUpdate.objects.filter(project=project, created_at__gte=week_ago).exists():
                Project.objects.filter(pk=project.pk).update(update_nudged_on=today)
                continue
            with transaction.atomic():
                updated = (
                    Project.objects.filter(pk=project.pk)
                    .exclude(update_nudged_on=today)
                    .update(update_nudged_on=today)
                )
                if not updated:
                    continue
                created = inbox.notify(
                    [project.lead],
                    "projects.update_nudge",
                    title=lambda person, p=project: _("How is %(key)s going?") % {"key": p.key},
                    body=lambda person, p=project: _nudge_body(p),
                    url=f"/c/{project.company_id}/projects/{project.pk}/updates",
                    app_screen=f"projects.updates:{project.pk}",
                    target=project,
                    actions=[
                        NotificationAction("on_track", _("On track"), "primary"),
                        NotificationAction("at_risk", _("At risk")),
                        NotificationAction("off_track", _("Off track"), "danger"),
                    ],
                    dedupe_key=f"projects.update_nudge:{project.pk}:{today}",
                )
                asked += 1 if created else 0
    return asked


def _nudge_body(project: Project) -> str:
    text = _("%(name)s: post this week's update. Tap a status, or write a fuller one.") % {
        "name": project.name
    }
    username = getattr(django_settings, "EMPLOYEE_BOT_USERNAME", "") or ""
    if username:
        text += f"\nhttps://t.me/{username}?start=upd_{project.pk}"
    return text


def post_nudged_update(notification, by: Membership, reason: str, *, health: str) -> str:
    """Inbox action handler: one tap on the weekly nudge posts the update."""
    from apps.projects import services

    project = queries.get_visible(by, notification.target_id)
    update = services.post_update(project, by=by, health=health, text=reason or "")
    return _("Posted: %(health)s") % {"health": update.get_health_display()}
