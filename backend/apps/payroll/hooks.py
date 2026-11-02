"""Registrations with the shared registries and signal receivers of payroll.

Imported by `AppConfig.ready()`; register a function only once it exists.
"""

from django.utils.translation import gettext_lazy as _

from apps.audit import registry as audit_registry
from apps.audit.redaction import register_sensitive
from apps.console import registry
from apps.console.perms import AnyOf
from apps.core.files import register_file_check
from apps.finance import sources
from apps.inbox.registry import register_action, register_kind
from apps.members.permissions import Perm
from apps.payroll import actions, providers, queries
from apps.payroll.audit_actions import PayrollAction
from apps.payroll.models import Adjustment, Advance, Compensation, Payslip

VIEW, PROPOSE, MANAGE = Perm.PAYROLL_VIEW, Perm.PAYROLL_PROPOSE, Perm.PAYROLL_MANAGE
FINALIZE, PAY = Perm.PAYROLL_FINALIZE, Perm.PAYROLL_PAY
FEATURE = "payroll"

audit_registry.register(PayrollAction)
for model_name in ("adjustment", "advance", "payrollrun", "payslip", "taskrate", "adjustmentrule"):
    audit_registry.register_target(model_name, VIEW)
register_sensitive(Compensation, {"amount": VIEW})
register_sensitive(Adjustment, {"amount": VIEW})
register_sensitive(Advance, {"amount": VIEW})
register_sensitive(Payslip, {"base_pay": VIEW, "gross": VIEW, "deductions": VIEW, "net": VIEW})

# Where payroll's ledger rows come from (finance links them back to the record).
sources.register(
    "payroll.payslip", label=_("Payslip"), url_template="/c/{company_id}/payroll/payslips/{id}"
)
sources.register(
    "payroll.advance", label=_("Advance"), url_template="/c/{company_id}/payroll/advances/{id}"
)
sources.register(
    "payroll.run", label=_("Payroll run"), url_template="/c/{company_id}/payroll/runs/{id}"
)

# Sidebar badges and version keys.
registry.register_pulse(
    "payroll.pending", perm=MANAGE, count=queries.pending_count, feature=FEATURE
)
registry.register_pulse(
    "payroll.advances", perm=AnyOf(MANAGE, PAY), count=queries.advances_count, feature=FEATURE
)
registry.register_pulse(
    "payroll.adjustments", perm=AnyOf(VIEW, PROPOSE), count=None, feature=FEATURE
)
registry.register_pulse("payroll.pay", perm=VIEW, count=None, feature=FEATURE)
registry.register_pulse("payroll.runs", perm=VIEW, count=None, feature=FEATURE)
registry.register_pulse("payroll.rules", perm=MANAGE, count=None, feature=FEATURE)
registry.register_pulse("payroll.settings", perm=MANAGE, count=None, feature=FEATURE)

# Needs you.
registry.register_queue(
    "payroll.adjustments",
    perm=MANAGE,
    label=_("Bonuses and fines to approve"),
    count=providers.adjustment_count,
    items=providers.adjustment_items,
    feature=FEATURE,
)
registry.register_queue(
    "payroll.advances",
    perm=MANAGE,
    label=_("Advances to approve"),
    count=providers.advance_count,
    items=providers.advance_items,
    feature=FEATURE,
)
registry.register_queue(
    "payroll.disputes",
    perm=MANAGE,
    label=_("Disputed fines"),
    count=providers.dispute_count,
    items=providers.dispute_items,
    feature=FEATURE,
)

# The team directory and the Person 360 header.
registry.register_person_fields(
    "payroll", perm=VIEW, fetch=providers.person_fields, feature=FEATURE
)
registry.register_setup_step(
    "payroll.pay_setups",
    perm=MANAGE,
    order=90,
    label=_("Pay setups"),
    description=_("Set each person's pay so payroll can work out their payslips."),
    url="payroll/pay",
    done=providers.setup_done,
    feature=FEATURE,
)

register_file_check("payroll.payslip", providers.payslip_check, allow_suspended=True)

# Notifications. Approvals live in Needs you; their Telegram copy carries the buttons.
register_kind(
    "payroll.adjustment",
    label=_("Bonuses and fines to approve"),
    audience="owner",
    default_telegram=True,
    queue_kind="payroll.adjustments",
)
register_action("payroll.adjustment", "approve", actions.approve_adjustment)
register_action("payroll.adjustment", "reject", actions.reject_adjustment)
register_kind(
    "payroll.advance",
    label=_("Advances to approve"),
    audience="owner",
    default_telegram=True,
    queue_kind="payroll.advances",
)
register_action("payroll.advance", "approve", actions.approve_advance)
register_action("payroll.advance", "reject", actions.reject_advance)
register_kind(
    "payroll.dispute",
    label=_("Disputed fines"),
    audience="owner",
    default_telegram=True,
    queue_kind="payroll.disputes",
)
register_kind(
    "payroll.advance_to_pay",
    label=_("Approved advances to pay"),
    audience="owner",
    default_telegram=True,
)
register_kind(
    "payroll.run_prepared",
    label=_("Payroll ready to check"),
    audience="owner",
    default_telegram=True,
)
register_kind(
    "payroll.pay_day",
    label=_("Pay day reminders"),
    audience="owner",
    default_telegram=True,
    severity="warning",
)
register_kind(
    "payroll.adjustment_decided",
    label=_("Your bonuses and fines"),
    audience="employee",
    default_telegram=True,
)
register_kind(
    "payroll.advance_decided",
    label=_("Your advances"),
    audience="employee",
    default_telegram=True,
)
register_kind(
    "payroll.payslip",
    label=_("Your payslips"),
    audience="employee",
    default_telegram=True,
)
register_action("payroll.payslip", "received", actions.payslip_received)
