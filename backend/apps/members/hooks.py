"""Registrations of memberships with the shared registries. Imported by AppConfig.ready()."""

from apps.audit import registry as audit_registry
from apps.members.audit_actions import MemberAction
from apps.members.queries import suspended_ids
from apps.tasks import offdays

audit_registry.register(MemberAction)

# Suspended people get no routine tasks while the suspension lasts.
offdays.register(suspended_ids)
