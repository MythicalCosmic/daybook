"""Registrations of time off with the shared registries. Imported by AppConfig.ready()."""

from django.utils.translation import gettext_lazy as _

from apps.audit import registry as audit_registry
from apps.console import registry
from apps.console.perms import AnyOf
from apps.core.files import register_file_check
from apps.exports.registry import register_exporter
from apps.inbox.registry import register_action, register_kind
from apps.members.permissions import Perm
from apps.timeoff import providers
from apps.timeoff.audit_actions import TimeOffAuditAction

audit_registry.register(TimeOffAuditAction)
audit_registry.register_target("timeoff", Perm.TIME_OFF_APPROVE, check=providers.history_check)
audit_registry.register_target("holiday", Perm.TIME_OFF_APPROVE)

register_file_check("timeoff.attachment", providers.may_open_attachment)

# Requests: in "Needs you", and as a Telegram copy with buttons for the approvers.
register_kind(
    "timeoff.request",
    label=_("Time off request"),
    audience="owner",
    default_telegram=True,
    queue_kind="timeoff.request",
)
register_action("timeoff.request", "approve", providers.approve_from_inbox)
register_action("timeoff.request", "reject", providers.reject_from_inbox)
registry.register_queue(
    "timeoff.request",
    perm=Perm.TIME_OFF_APPROVE,
    label=_("Time off requests"),
    count=providers.queue_count,
    items=providers.queue_items,
)

# What the person hears (the bot and the mini app's inbox).
register_kind(
    "timeoff.decided", label=_("Time off decided"), audience="employee", default_telegram=True
)
register_kind(
    "timeoff.recorded",
    label=_("Time off recorded for you"),
    audience="employee",
    default_telegram=True,
)
register_kind(
    "timeoff.revoked",
    label=_("Time off revoked"),
    audience="employee",
    default_telegram=True,
    severity="warning",
)

registry.register_pulse("timeoff.pending", perm=Perm.TIME_OFF_APPROVE, count=providers.queue_count)
registry.register_pulse("timeoff.time_off", perm=Perm.TIME_OFF_APPROVE, count=None)
registry.register_pulse("timeoff.holidays", perm=None, count=None)

registry.register_calendar_source(
    "timeoff.time_off",
    label=_("Time off"),
    perm=AnyOf(Perm.TIME_OFF_APPROVE, Perm.TIME_OFF_MANAGE),
    events=providers.calendar_time_off,
)
registry.register_calendar_source(
    "timeoff.holidays", label=_("Holidays"), perm=None, events=providers.calendar_holidays
)

registry.register_offboard_step(
    "timeoff",
    perm=Perm.MEMBERS_MANAGE,
    order=60,
    label=_("Time off"),
    preview=providers.offboard_step,
)

registry.register_person_fields(
    "timeoff", perm=AnyOf(Perm.MEMBERS_VIEW, Perm.TIME_OFF_APPROVE), fetch=providers.person_fields
)

register_exporter(
    "timeoff.time_off",
    perm=Perm.TIME_OFF_APPROVE,
    label=_("Time off"),
    columns=providers.EXPORT_COLUMNS,
    rows=providers.export_rows,
)
