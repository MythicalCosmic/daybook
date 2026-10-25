"""Registrations of tasks with the shared registries, and its signal receivers
(docs/PLAN-OWNER.md §11.3, Package B). Imported by `AppConfig.ready()`."""

from django.db.models.signals import post_delete, post_save
from django.utils.translation import gettext_lazy as _

from apps.audit import registry as audit_registry
from apps.console import pulse, registry
from apps.exports.registry import Column, register_exporter
from apps.inbox.registry import register_action, register_kind
from apps.members.permissions import Perm
from apps.members.scope import branch_ids
from apps.members.signals import member_approved
from apps.tasks import feeds, inbox_actions, queries
from apps.tasks import tasks as jobs
from apps.tasks.audit_actions import TasksAction
from apps.tasks.models import Task, TaskTemplate

audit_registry.register(TasksAction)

# "Can't do it" (research R2 T57): an entry in the giver's inbox; the bot message with its
# buttons goes out on its own (apps.tasks.notifications.send_blocked), so no Telegram copy here.
register_kind(
    "tasks.blocked",
    label=_("Someone can't do a task"),
    audience="owner",
    default_telegram=False,
    severity="warning",
)
# "Need more time" (T17): approve or decline in one tap, in either bot or the dashboard.
register_kind(
    "tasks.extension",
    label=_("Someone asks for more time"),
    audience="owner",
    default_telegram=True,
)
register_action("tasks.extension", "approve", inbox_actions.approve_extension)
register_action("tasks.extension", "decline", inbox_actions.decline_extension)
# Finished work nobody reviewed in time was accepted (PLAN-OWNER §15.3): whoever should have
# checked it hears, in the inbox and through the employee bot, where review requests come.
register_kind(
    "tasks.auto_accepted",
    label=_("Work accepted automatically without a review"),
    audience="employee",
    default_telegram=True,
)


def _task_in_scope(member, task_id: int) -> bool:
    return queries.visible_tasks(member).filter(pk=task_id).exists()


def _template_in_scope(member, template_id: int) -> bool:
    templates = TaskTemplate.objects.for_company(member.company_id).filter(
        pk=template_id, personal=False
    )
    scope = branch_ids(member)
    if scope is not None:
        templates = templates.filter(branch_id__in=scope)
    return templates.exists()


# The History tab of a task (and of a routine) for people who may see it without audit.view.
audit_registry.register_target("task", Perm.TASKS_VIEW_ALL, check=_task_in_scope)
audit_registry.register_target("tasktemplate", Perm.TASKS_TEMPLATES, check=_template_in_scope)

registry.register_search("tasks.task", perm=Perm.TASKS_VIEW_ALL, search=feeds.search)
registry.register_queue(
    "tasks.review",
    perm=None,  # whoever has work to check: tasks.confirm holders and those who gave it
    label=_("Tasks to check"),
    count=feeds.review_count,
    items=feeds.review_items,
)
# Badges: one-off work to check (Tasks), routine work to confirm (Routines → To confirm).
registry.register_pulse("tasks.review", perm=None, count=queries.review_count)
registry.register_pulse(
    "tasks.routine_review", perm=Perm.TASKS_CONFIRM, count=queries.routine_review_count
)
registry.register_pulse("tasks.late_now", perm=Perm.TASKS_VIEW_ALL, count=queries.late_now_count)
# Version keys: any task (or routine) changed, so open dashboards refetch.
registry.register_pulse("tasks.tasks", perm=None, count=None)
registry.register_pulse("tasks.routines", perm=Perm.TASKS_TEMPLATES, count=None)
registry.register_stream("tasks.done", perm=Perm.TASKS_VIEW_ALL, fetch=feeds.stream)
registry.register_branch_facts("tasks", perm=Perm.TASKS_VIEW_ALL, facts=feeds.branch_facts)
registry.register_brief_section("tasks", perm=Perm.TASKS_VIEW_ALL, order=20, build=feeds.brief)
registry.register_company_facts("tasks", perm=Perm.TASKS_VIEW_ALL, facts=feeds.company_facts)
registry.register_calendar_source(
    "tasks.due", label=_("Tasks due"), perm=Perm.TASKS_VIEW_ALL, events=feeds.calendar_events
)
registry.register_copy_part(
    "tasks.routines", label=_("Routines"), perm=Perm.TASKS_TEMPLATES, copy=feeds.copy_routines
)
registry.register_copy_part(
    "tasks.onboarding",
    label=_("Onboarding tasks"),
    perm=Perm.TASKS_TEMPLATES,
    copy=feeds.copy_onboarding,
)

register_exporter(
    "tasks.list",
    perm=Perm.TASKS_VIEW_ALL,
    label=_("Tasks"),
    columns=[
        Column("id", _("No."), "number"),
        Column("title", _("Task")),
        Column("status", _("Status")),
        Column("kind", _("Kind")),
        Column("priority", _("Priority")),
        Column("assignee", _("Assignee")),
        Column("position", _("Position")),
        Column("branch", _("Branch")),
        Column("routine", _("Routine")),
        Column("due_at", _("Due"), "datetime"),
        Column("completed_at", _("Finished"), "datetime"),
        Column("created_by", _("Given by")),
        Column("checklist", _("Checklist")),
        Column("has_proof", _("Proof"), "bool"),
        Column("reward", _("Reward"), "money"),
    ],
    rows=feeds.export_rows,
)


# New people get their onboarding tasks (§10.1 `tasks.tasks.assign_onboarding`).
def _on_member_approved(sender, membership, **kwargs):
    jobs.assign_onboarding.delay(membership.pk)  # the signal is sent after commit already


member_approved.connect(_on_member_approved, dispatch_uid="tasks.assign_onboarding")


# Pulse: every saved or removed task or routine moves its version key, so open dashboards
# refetch. At once rather than on commit: the services queue their own messages on commit and
# their tests count those callbacks; a bump a few milliseconds early only costs a dashboard that
# polls in that instant one extra refetch, and the next change moves the key again. The reminder
# engine's own bookkeeping (next reminder, count, message id) changes nothing a dashboard lists,
# so it doesn't make every open dashboard refetch every task each minute.
REMINDER_BOOKKEEPING = frozenset(
    {
        "next_reminder_at",
        "reminders_sent",
        "escalated_at",
        "last_reminder_message_id",
        "snoozed_until",
        "snooze_count",
        "updated_at",
    }
)


def _bump(key: str, company_id: int) -> None:
    pulse.bump(company_id, key)


def _task_saved(sender, instance, update_fields=None, **kwargs):
    if update_fields and set(update_fields) <= REMINDER_BOOKKEEPING:
        return
    _bump("tasks.tasks", instance.company_id)


def _template_saved(sender, instance, **kwargs):
    if not instance.personal:
        _bump("tasks.routines", instance.company_id)


post_save.connect(_task_saved, sender=Task, dispatch_uid="tasks.pulse.task_saved")
post_delete.connect(_task_saved, sender=Task, dispatch_uid="tasks.pulse.task_deleted")
post_save.connect(_template_saved, sender=TaskTemplate, dispatch_uid="tasks.pulse.template_saved")
post_delete.connect(
    _template_saved, sender=TaskTemplate, dispatch_uid="tasks.pulse.template_deleted"
)
