"""Registrations with the shared registries and signal receivers of the company calendar.

Imported by `AppConfig.ready()`; register a function only once it exists.
"""

from django.utils.translation import gettext_lazy as _

from apps.agenda import actions, providers, queries, services
from apps.agenda.audit_actions import AgendaAction
from apps.audit import registry as audit_registry
from apps.console import registry
from apps.inbox.registry import register_action, register_kind

audit_registry.register(AgendaAction)

# Bumped on every change, so open calendars refresh.
registry.register_pulse(services.PULSE_KEY, perm=None, count=None)
# The company's own events on the calendar (everyone sees the ones meant for them).
registry.register_calendar_source(
    "agenda.events", label=_("Company events"), perm=None, events=queries.calendar_items
)
registry.register_search("agenda.event", perm=None, search=providers.search)
registry.register_brief_section("agenda.today", perm=None, order=70, build=providers.today_section)

# Invitations (answered with the buttons), changes and cancellations, reminders.
register_kind(
    services.KIND_INVITE,
    label=_("Invitations to company events"),
    audience="employee",
    default_telegram=True,
)
register_action(services.KIND_INVITE, "going", actions.going)
register_action(services.KIND_INVITE, "decline", actions.decline)
register_kind(
    services.KIND_CHANGED,
    label=_("Company events moved or cancelled"),
    audience="employee",
    default_telegram=True,
)
register_kind(
    services.KIND_REMINDER,
    label=_("Reminders before company events"),
    audience="employee",
    default_telegram=True,
)
