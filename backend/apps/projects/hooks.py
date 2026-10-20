"""Registrations with the shared registries and signal receivers of projects.

Imported by `AppConfig.ready()`; register a function only once it exists.
"""

from functools import partial

from django.db.models import Q
from django.db.models.signals import post_save
from django.utils.translation import gettext_lazy as _

from apps.audit import registry as audit_registry
from apps.companies.signals import company_created
from apps.console import registry
from apps.core.files import register_file_check
from apps.exports.registry import Column, register_exporter
from apps.inbox.registry import register_action, register_kind
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.projects import defaults, jobs, providers, queries, receivers
from apps.projects.audit_actions import ProjectsAction
from apps.projects.models import Health
from apps.tasks.models import Task
from apps.tasks.visibility import register_task_visibility_filter

audit_registry.register(ProjectsAction)
audit_registry.register_target("project", Perm.DASHBOARD_ACCESS, check=providers.history_check)

# Version keys: the board, the index and the roadmap refresh on the first; the time grid on
# the second.
registry.register_pulse("projects.projects", perm=None, count=None)
registry.register_pulse("projects.time", perm=None, count=None)

registry.register_search("projects.project", perm=None, search=providers.search)
registry.register_stream("projects.updates", perm=None, fetch=providers.stream)
registry.register_calendar_source(
    "projects.milestones",
    label=_("Project milestones"),
    perm=None,
    events=providers.milestones_calendar,
)

register_file_check("projects.file", providers.file_check)

register_exporter(
    "projects.time",
    perm=Perm.PROJECTS_TIME_VIEW,
    label=_("Time entries"),
    columns=[
        Column("day", _("Day"), "date"),
        Column("person", _("Person")),
        Column("project", _("Project")),
        Column("task", _("Task")),
        Column("minutes", _("Minutes"), "number"),
        Column("hours", _("Hours"), "number"),
        Column("note", _("Note")),
        Column("billable", _("Billable"), "bool"),
        Column("source", _("Source")),
    ],
    rows=providers.time_rows,
)

register_kind(
    "projects.added",
    label=_("You were added to a project"),
    audience="employee",
    default_telegram=True,
)
register_kind(
    "projects.update_nudge",
    label=_("Weekly project update reminder"),
    audience="employee",
    default_telegram=True,
)
register_kind(
    "projects.off_track",
    label=_("A project went off track"),
    audience="owner",
    default_telegram=True,
    severity="warning",
)
register_kind(
    "projects.milestone_missed",
    label=_("A project milestone was missed"),
    audience="owner",
    default_telegram=True,
    severity="warning",
)
for health in Health.values:
    register_action(
        "projects.update_nudge", health, partial(jobs.post_nudged_update, health=health)
    )


def hide_private_project_tasks(tasks, member: Membership):
    """Tasks of members-only projects are hidden from people outside them (§13.3); a person
    keeps their own tasks and the ones they handed out."""
    if member.has_perm(Perm.PROJECTS_VIEW_ALL):
        return tasks  # visible_tasks already applied the branch scope
    visible = queries.visible_projects(member, archived=True).values("pk")
    return tasks.filter(
        Q(project__isnull=True) | Q(project__in=visible) | Q(assignee=member) | Q(created_by=member)
    )


register_task_visibility_filter("projects.members", hide_private_project_tasks)

post_save.connect(receivers.task_saved, sender=Task, dispatch_uid="projects.task_saved")


def make_defaults(sender, company, by=None, **kwargs) -> None:
    defaults.ensure(company)


company_created.connect(make_defaults, dispatch_uid="projects.make_defaults")
