"""Registrations with the shared registries and signal receivers of sales and cash.

Imported by `AppConfig.ready()`; register a function only once it exists.
"""

import importlib

from django.db.models.signals import post_save
from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext_noop

from apps.audit import registry as audit_registry
from apps.companies.models import Branch, Feature
from apps.companies.signals import company_created
from apps.console import registry
from apps.core.files import register_file_check
from apps.exports.registry import Column, register_exporter
from apps.finance import sources
from apps.inbox.registry import register_action, register_kind
from apps.members import scope
from apps.members.bot_menu import register_menu_button
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.sales import defaults, handlers, queries
from apps.sales.audit_actions import SalesAction
from apps.sales.models import CashMovement, CashShift

FEATURE = Feature.SALES

# The AI tools register at startup (autodiscover would import them later): a test that swaps the
# AI registry for an empty one must never be the first to import them, or they land in it.
importlib.import_module("apps.sales.ai_tools")

# Audit labels, and who may open a shift's or a movement's History tab.
audit_registry.register(SalesAction)


def _shift_in_scope(member, target_id) -> bool:
    shift = CashShift.objects.filter(pk=target_id, company_id=member.company_id).first()
    return shift is not None and scope.allows(scope.branch_ids(member), shift.branch_id)


def _movement_in_scope(member, target_id) -> bool:
    movement = CashMovement.objects.filter(pk=target_id, company_id=member.company_id).first()
    return movement is not None and scope.allows(scope.branch_ids(member), movement.branch_id)


audit_registry.register_target("cashshift", Perm.SALES_VIEW, check=_shift_in_scope)
audit_registry.register_target("cashmovement", Perm.SALES_VIEW, check=_movement_in_scope)

# Ledger rows link back to their shift, movement or receipt.
sources.register(
    "sales.cashshift",
    label=_("Cashier shift"),
    url_template="/c/{company_id}/sales/shifts?shift={id}",
)
sources.register(
    "sales.cashmovement",
    label=_("Cash movement"),
    url_template="/c/{company_id}/sales/cash?movement={id}",
)
sources.register(
    "sales.sale", label=_("Receipt"), url_template="/c/{company_id}/sales/entries?entry={id}"
)


# Private photos: Z-reports, terminal slips and payout receipts.
def _may_see(user, company_id, branch_id, owner_id) -> bool:
    member = (
        Membership.objects.select_related("role")
        .filter(user=user, company_id=company_id, status=Membership.Status.APPROVED)
        .first()
    )
    if member is None:
        return False
    if member.pk == owner_id:
        return True
    return member.has_perm(Perm.SALES_VIEW) and scope.allows(scope.branch_ids(member), branch_id)


def check_shift_photo(user, company_id, object_id) -> bool:
    shift = CashShift.objects.for_company(company_id).filter(pk=object_id).first()
    return shift is not None and _may_see(user, company_id, shift.branch_id, shift.cashier_id)


def check_movement_photo(user, company_id, object_id) -> bool:
    movement = CashMovement.objects.for_company(company_id).filter(pk=object_id).first()
    return movement is not None and _may_see(
        user, company_id, movement.branch_id, movement.created_by_id
    )


register_file_check("sales.shift_photo", check_shift_photo)
register_file_check("sales.movement_photo", check_movement_photo)

# Live badges and the version keys every sales page refreshes on.
registry.register_pulse(
    "sales.open_shifts", perm=Perm.SALES_VIEW, count=queries.open_shifts_count, feature=FEATURE
)
registry.register_pulse(
    "sales.to_verify", perm=Perm.SALES_MANAGE, count=queries.to_verify_count, feature=FEATURE
)
for _key in ("sales.shifts", "sales.cash", "sales.setup", "sales.entries", "sales.targets"):
    registry.register_pulse(_key, perm=Perm.SALES_VIEW, count=None, feature=FEATURE)

# The command palette, Needs you, the activity stream, branch cards, briefings, the portfolio.
registry.register_search(
    "sales.shift", perm=Perm.SALES_VIEW, search=queries.search, feature=FEATURE
)
registry.register_queue(
    "sales.verify",
    perm=Perm.SALES_MANAGE,
    label=_("Shifts to verify"),
    count=queries.verify_count,
    items=queries.verify_items,
    feature=FEATURE,
)
registry.register_queue(
    "sales.handover",
    perm=None,
    label=_("Cash handed to you"),
    count=queries.handover_count,
    items=queries.handover_items,
    feature=FEATURE,
)
registry.register_stream(
    "sales.shift_closed", perm=Perm.SALES_VIEW, fetch=queries.stream, feature=FEATURE
)
registry.register_branch_facts(
    "sales", perm=Perm.SALES_VIEW, facts=queries.branch_facts, feature=FEATURE
)
registry.register_brief_section(
    "sales", perm=Perm.SALES_VIEW, order=20, build=queries.brief_section, feature=FEATURE
)
registry.register_company_facts(
    "sales", perm=Perm.SALES_VIEW, facts=queries.company_facts, feature=FEATURE
)
registry.register_offboard_step(
    "sales",
    perm=None,
    order=30,
    label=_("Till and cash"),
    preview=queries.offboard_preview,
    feature=FEATURE,
)
registry.register_setup_step(
    "sales.registers",
    perm=Perm.SALES_MANAGE,
    order=60,
    label=_("Tills and payment methods"),
    description=_("Check each branch's till and how customers pay, then open a shift in Kassa."),
    url="sales/setup",
    done=queries.setup_done,
    feature=FEATURE,
)

# Notifications (owner-audience kinds reach owners through the owner bot when they started it).
register_kind(
    "sales.handover",
    label=_("Cash handed to you"),
    audience="owner",
    default_telegram=True,
    queue_kind="sales.handover",
)
register_action("sales.handover", "received", handlers.received)
register_action("sales.handover", "not_received", handlers.not_received)
register_kind(
    "sales.shift_closed",
    label=_("Shift closed, to verify"),
    audience="owner",
    default_telegram=False,
    queue_kind="sales.verify",
)
register_action("sales.shift_closed", "verify", handlers.verify)
register_kind(
    "sales.cash_difference",
    label=_("Cash difference above tolerance"),
    audience="owner",
    default_telegram=True,
    severity="critical",
)
register_kind(
    "sales.handover_declined",
    label=_("Cash handover didn't arrive"),
    audience="owner",
    default_telegram=True,
    severity="critical",
)
register_kind(
    "sales.handover_late",
    label=_("Cash handover not confirmed"),
    audience="owner",
    default_telegram=True,
    severity="warning",
)
register_kind(
    "sales.branch_not_opened",
    label=_("Branch not opened on time"),
    audience="owner",
    default_telegram=True,
    severity="critical",
)
register_kind(
    "sales.shift_not_closed",
    label=_("Till left open"),
    audience="owner",
    default_telegram=True,
    severity="warning",
)
register_kind(
    "sales.big_payout",
    label=_("Big payout from a till"),
    audience="owner",
    default_telegram=True,
    severity="warning",
)
register_kind(
    "sales.cash_over_limit",
    label=_("Cash in a branch over its limit"),
    audience="owner",
    default_telegram=True,
    severity="warning",
)
register_kind(
    "sales.ai_mismatch",
    label=_("Shift photos don't match the totals"),
    audience="owner",
    default_telegram=True,
    severity="warning",
)
register_kind(
    "sales.shift_verified",
    label=_("Your shift was verified"),
    audience="employee",
    default_telegram=True,
)
register_kind(
    "sales.shift_disputed",
    label=_("Your shift needs another look"),
    audience="employee",
    default_telegram=True,
    severity="warning",
)
register_kind(
    "sales.till_open",
    label=_("Your till is still open"),
    audience="employee",
    default_telegram=True,
    severity="warning",
)

# Excel/CSV.
register_exporter(
    "sales.daily",
    perm=Perm.SALES_VIEW,
    label=_("Sales by day"),
    columns=[
        Column("day", _("Day"), "date"),
        Column("branch", _("Branch")),
        Column("sales", _("Sales"), "money"),
        Column("refunds", _("Refunds"), "money"),
        Column("net", _("Net sales"), "money"),
        Column("cash", _("Cash"), "money"),
        Column("non_cash", _("Cards and transfers"), "money"),
        Column("receipts", _("Receipts"), "number"),
        Column("avg_check", _("Average check"), "money"),
        Column("shifts", _("Shifts"), "number"),
        Column("cash_difference", _("Cash difference"), "money"),
    ],
    rows=queries.export_daily,
    feature=FEATURE,
)
register_exporter(
    "sales.shifts",
    perm=Perm.SALES_VIEW,
    label=_("Cashier shifts"),
    columns=[
        Column("code", _("Shift")),
        Column("business_day", _("Business day"), "date"),
        Column("branch", _("Branch")),
        Column("register", _("Till")),
        Column("cashier", _("Cashier")),
        Column("status", _("Status")),
        Column("opened_at", _("Opened"), "datetime"),
        Column("closed_at", _("Closed"), "datetime"),
        Column("opening_float", _("Float"), "money"),
        Column("net", _("Net sales"), "money"),
        Column("receipts", _("Receipts"), "number"),
        Column("expected_cash", _("Expected cash"), "money"),
        Column("counted_cash", _("Counted cash"), "money"),
        Column("difference", _("Difference"), "money"),
        Column("z_number", _("Z-report")),
        Column("verified_by", _("Verified by")),
    ],
    rows=queries.export_shifts,
    feature=FEATURE,
)


# A "🧾 Kassa" button in the employee bot's menu for people who run a till.
def _runs_a_till(member) -> bool:
    return member.company.has_feature(FEATURE) and member.has_perm(Perm.SALES_OPERATE)


register_menu_button(
    gettext_noop("🧾 Kassa"), order=20, visible=_runs_a_till, web_app_screen="kassa"
)


# Defaults: a new company (when it starts with sales on) and every new branch get their tills.
def make_defaults(sender, company, by=None, **kwargs) -> None:
    defaults.ensure(company)


def branch_saved(sender, instance: Branch, created: bool = False, raw: bool = False, **kwargs):
    # A company without sales gets its tills when the module is switched on (`defaults.ensure`).
    if raw or not instance.is_active or not instance.company.has_feature(FEATURE):
        return
    from django.db import transaction

    transaction.on_commit(lambda: defaults.ensure_branch(instance))


company_created.connect(make_defaults, dispatch_uid="sales.make_defaults")
post_save.connect(branch_saved, sender=Branch, dispatch_uid="sales.branch_saved")
