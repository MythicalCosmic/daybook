"""Registrations with the shared registries of business goals.

Imported by `AppConfig.ready()`; register a function only once it exists.
"""

from django.utils.translation import gettext_lazy as _

from apps.audit import registry as audit_registry
from apps.console import registry
from apps.goals import queries
from apps.goals.audit_actions import GoalsAction
from apps.goals.services import NOTIFY_KIND
from apps.inbox.registry import register_kind
from apps.members.permissions import Perm

audit_registry.register(GoalsAction)
audit_registry.register_target(
    "goal",
    Perm.REPORTS_VIEW,
    check=lambda member, target_id: queries.visible(member).filter(pk=target_id).exists(),
)

# Tells the dashboard that goals changed (no badge).
registry.register_pulse("goals", perm=Perm.REPORTS_VIEW, count=None)

register_kind(
    NOTIFY_KIND,
    label=_("Business goals at risk"),
    audience="owner",
    default_telegram=True,
    severity="warning",
)
