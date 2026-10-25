"""Registrations with the shared registries and signal receivers of the knowledge base.

Imported by `AppConfig.ready()`; register a function only once it exists.
"""

from django.utils.translation import gettext_lazy as _

from apps.audit import registry as audit_registry
from apps.companies.signals import company_created
from apps.console import registry
from apps.core.files import register_file_check
from apps.inbox.registry import register_action, register_kind
from apps.knowledge import actions, defaults, providers, services
from apps.knowledge.audit_actions import KnowledgeAction
from apps.members.permissions import Perm

audit_registry.register(KnowledgeAction)

# Bumped on every change, so open dashboards refresh the tree and the page.
registry.register_pulse(services.PULSE_KEY, perm=None, count=None)
# Command palette: pages the person may open (drafts too for managers).
registry.register_search("knowledge.page", perm=None, search=providers.search)
# Overview activity: "Dilnoza published the page …".
registry.register_stream("knowledge.published", perm=None, fetch=providers.stream)
# Copy setup from another company: spaces and their published pages.
registry.register_copy_part(
    "knowledge.spaces",
    label=_("Knowledge base: spaces and published pages"),
    perm=Perm.KNOWLEDGE_MANAGE,
    copy=providers.copy_spaces,
)

# "New page to read: …" and the reminder; "Read" sends the page into the chat.
register_kind(
    services.KIND_PUBLISHED,
    label=_("New pages in the knowledge base"),
    audience="employee",
    default_telegram=True,
)
register_action(services.KIND_PUBLISHED, "read", actions.read_in_chat)
register_kind(
    services.KIND_REMINDER,
    label=_("Reminders to read knowledge base pages"),
    audience="employee",
    default_telegram=True,
)
register_action(services.KIND_REMINDER, "read", actions.read_in_chat)

# Pictures in pages: managers, and readers of the page they are on.
register_file_check("knowledge.image", providers.image_check)


def make_defaults(sender, company, by=None, **kwargs) -> None:
    """A new company starts with one space to write in."""
    defaults.ensure(company)


company_created.connect(make_defaults, dispatch_uid="knowledge.make_defaults")
