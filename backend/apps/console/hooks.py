"""Registrations with the shared registries and signal receivers of the owner console.

Imported by `AppConfig.ready()`; register a function only once it exists.
"""

from apps.audit import registry as audit_registry
from apps.console import registry
from apps.console.audit_actions import ConsoleAction

# The "Needs you" badge: every queue item the member may act on, across modules.
registry.register_pulse("console.queue", perm=None, count=registry.queue_total)
# Bumped whenever a shared saved view changes, so colleagues' lists refresh.
registry.register_pulse("console.saved_views", perm=None, count=None)

audit_registry.register(ConsoleAction)
