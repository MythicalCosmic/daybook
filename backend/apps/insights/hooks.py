"""Registrations with the shared registries and signal receivers of insights.

Imported by `AppConfig.ready()`; register a function only once it exists.
"""

from django.utils.translation import gettext_lazy as _

from apps.audit import registry as audit_registry
from apps.console import registry
from apps.inbox.registry import register_action, register_kind
from apps.insights import access, decisions, notify, queries
from apps.insights.audit_actions import InsightAction

audit_registry.register(InsightAction)

# The sidebar badge of the insights page and the version key the cockpit refreshes on.
registry.register_pulse("insights.open", perm=access.BASE, count=queries.open_count)

# Urgent insights in the owner bot, with their buttons (one handler for Telegram and the bell).
register_kind(
    notify.KIND,
    label=_("Urgent insight"),
    audience="owner",
    default_telegram=True,
    severity="critical",
)
register_action(notify.KIND, notify.SEEN[0], notify.seen_action)
register_action(notify.KIND, notify.TASK[0], notify.task_action)

# What waits for the owner's decision ("Qaroringizni kutmoqda"): the "Needs you" queues that
# are decisions, by their kind (each keeps its own permission, switch, items and buttons).
# Hiring adds `decisions.register_source("<its queue kind>", group="hire", order=15)`.
decisions.register_source("members.join", group="people", order=10)
decisions.register_source("finance.claims", group="expense", order=20)
decisions.register_source("timeoff.request", group="time_off", order=30)
decisions.register_source("attendance.overtime", group="overtime", order=40)
decisions.register_source("payroll.advances", group="pay", order=50)
decisions.register_source("payroll.adjustments", group="pay", order=60)
decisions.register_source("inventory.writeoffs_to_approve", group="stock", order=70)
