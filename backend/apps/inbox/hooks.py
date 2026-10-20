"""Registrations with the shared registries and signal receivers of the inbox.

Imported by `AppConfig.ready()`; register a function only once it exists.
"""

from apps.console import registry
from apps.inbox import facts, queries

# The inbox badge: the member's unread in-app notifications.
registry.register_pulse("inbox.unread", perm=None, count=queries.unread_count)
# Portfolio cards: approvals waiting for the caller in each company.
registry.register_company_facts("inbox", perm=None, facts=facts.company_facts)
