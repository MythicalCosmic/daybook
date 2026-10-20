"""Registrations with the shared registries and signal receivers of the inbox.

Imported by `AppConfig.ready()`; register a function only once it exists.
"""

from django.utils.translation import gettext_lazy as _

from apps.console import registry
from apps.inbox import actions, facts, queries
from apps.inbox.registry import register_action, register_kind

# The inbox badge: the member's unread in-app notifications.
registry.register_pulse("inbox.unread", perm=None, count=queries.unread_count)
# Portfolio cards: approvals waiting for the caller in each company.
registry.register_company_facts("inbox", perm=None, facts=facts.company_facts)

# Messages from the product itself (welcome, tips); "Got it" settles them.
register_kind(
    "inbox.system", label=_("Messages from 911"), audience="owner", default_telegram=False
)
register_action("inbox.system", "got_it", actions.got_it)
