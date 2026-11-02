"""Registrations with the shared registries and signal receivers of HR records.

Imported by `AppConfig.ready()`; register a function only once it exists.
"""

from django.utils.translation import gettext_lazy as _

from apps.audit import registry as audit_registry
from apps.audit.redaction import SECRET
from apps.console import registry
from apps.core.files import register_file_check
from apps.hr import notify, providers, queries, services
from apps.hr.audit_actions import HRAction
from apps.hr.models import EmployeeDocument, EmployeeProfile
from apps.inbox.registry import register_action, register_kind
from apps.members.permissions import Perm
from apps.members.signals import member_approved, member_left

FEATURE = "hr"
VIEW, MANAGE = Perm.HR_VIEW, Perm.HR_MANAGE

audit_registry.register(HRAction)
audit_registry.register_sensitive(
    EmployeeProfile, {"pinfl": SECRET, "passport": SECRET, "payout_card": SECRET, "notes": SECRET}
)
audit_registry.register_sensitive(EmployeeDocument, {"number": SECRET})
audit_registry.register_target("hrsettings", MANAGE)
audit_registry.register_target("requireddocument", VIEW)

# Document and contract files: the person's own (also while suspended), or HR's in scope.
register_file_check("hr.document", providers.may_open_document, allow_suspended=True)
register_file_check("hr.contract", providers.may_open_contract, allow_suspended=True)

# The sidebar badge (expiring and expired), and version keys the pages refetch on.
registry.register_pulse("hr.expiring", perm=VIEW, count=queries.expiring_count, feature=FEATURE)
registry.register_pulse("hr.people", perm=VIEW, count=None, feature=FEATURE)
registry.register_pulse("hr.documents", perm=VIEW, count=None, feature=FEATURE)
registry.register_pulse("hr.required", perm=VIEW, count=None, feature=FEATURE)
registry.register_pulse("hr.settings", perm=VIEW, count=None, feature=FEATURE)
registry.register_pulse("hr.contracts", perm=VIEW, count=None, feature=FEATURE)
registry.register_pulse("hr.templates", perm=MANAGE, count=None, feature=FEATURE)

# What HR hears (the owner bot for owners and top managers): what runs out, once per step.
register_kind(
    notify.DOCUMENT_EXPIRING,
    label=_("Documents that expire"),
    audience="owner",
    default_telegram=True,
)
register_kind(
    notify.CONTRACT_ENDING,
    label=_("Contracts that end"),
    audience="owner",
    default_telegram=True,
)
register_kind(
    notify.PROBATION_ENDING,
    label=_("Probations that end"),
    audience="owner",
    default_telegram=True,
)
register_action(notify.PROBATION_ENDING, "keep", providers.keep_from_inbox)
register_action(notify.PROBATION_ENDING, "extend", providers.extend_from_inbox)

# What the person hears: their contract, their documents running out, their day.
register_kind(
    notify.CONTRACT_READY,
    label=_("Your contract"),
    audience="employee",
    default_telegram=True,
)
register_kind(
    notify.MY_DOCUMENT,
    label=_("Your documents that expire"),
    audience="employee",
    default_telegram=True,
)
register_kind(
    notify.CELEBRATION,
    label=_("Birthday and work anniversary greetings"),
    audience="employee",
    default_telegram=True,
)

# Briefings and /today; the company calendar.
registry.register_brief_section(
    "hr", perm=VIEW, order=60, build=providers.brief_section, feature=FEATURE
)
registry.register_calendar_source(
    "hr.celebrations",
    label=_("Birthdays and work anniversaries"),
    perm=VIEW,
    events=providers.calendar_celebrations,
    feature=FEATURE,
)
registry.register_calendar_source(
    "hr.contracts",
    label=_("Contracts and probation"),
    perm=VIEW,
    events=providers.calendar_contracts,
    feature=FEATURE,
)


def on_member_approved(sender, membership, **kwargs) -> None:
    services.hired(membership)


def on_member_left(sender, membership, terminated_on=None, details=None, **kwargs) -> None:
    services.left(membership, terminated_on=terminated_on, details=details)


member_approved.connect(on_member_approved, dispatch_uid="hr.member_approved")
member_left.connect(on_member_left, dispatch_uid="hr.member_left")
