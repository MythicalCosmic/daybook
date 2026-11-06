"""Registrations of stock with the shared registries (docs/PLAN-OWNER.md §14.6.4).

Imported by `AppConfig.ready()`; register a function only once it exists. Everything that a
person sees is registered with `feature="stock"`, so it is invisible and inert while the stock
module is off for the company.
"""

from django.utils.translation import gettext_lazy as _

from apps.audit import registry as audit_registry
from apps.finance import sources
from apps.inbox.registry import register_action, register_kind
from apps.inventory import notify
from apps.inventory.audit_actions import InventoryAction
from apps.inventory.services import RECEIPT

FEATURE = "stock"

audit_registry.register(InventoryAction)

# A goods receipt's payable links back to the receipt.
sources.register(
    RECEIPT, label=_("Goods receipt"), url_template="/c/{company_id}/stock/receipts/{id}"
)

# Notification kinds ------------------------------------------------------------------------------

register_kind(
    notify.EXPIRY_DIGEST,
    label=_("Medicines reaching their expiry warning, and mandatory medicines missing"),
    audience="owner",
    default_telegram=True,
)
register_kind(
    notify.TRANSFER_INCOMING,
    label=_("Goods sent to your pharmacy"),
    audience="employee",
    default_telegram=True,
)
register_action(notify.TRANSFER_INCOMING, notify.RECEIVED, notify.received_action)
register_kind(
    notify.TRANSFER_DISPUTED,
    label=_("Transfers that arrived short"),
    audience="owner",
    default_telegram=True,
    severity="warning",
)
register_kind(
    notify.RECALL,
    label=_("Recalled series found in stock"),
    audience="owner",
    default_telegram=True,
    severity="warning",
)
register_kind(
    notify.COUNT_SHORTAGE,
    label=_("Stock count shortages above the tolerance"),
    audience="owner",
    default_telegram=True,
    severity="warning",
)
register_kind(
    notify.COST_JUMP,
    label=_("Distributors raising their prices"),
    audience="owner",
    default_telegram=False,
)
register_kind(
    notify.DESTROY_DUE,
    label=_("Unfit goods to destroy"),
    audience="owner",
    default_telegram=True,
)
register_kind(
    notify.CONTROLLED_CLOSE_DUE,
    label=_("Closing the month of the controlled-substance register"),
    audience="owner",
    default_telegram=True,
)
register_kind(
    notify.CONTROLLED_MISMATCH,
    label=_("Differences in the controlled-substance register"),
    audience="owner",
    default_telegram=True,
    severity="critical",
)
register_kind(
    notify.RECEIPT_WAITING,
    label=_("Goods receipts waiting for posting"),
    audience="owner",
    default_telegram=True,
    queue_kind="inventory.receipts_to_post",
)
register_kind(
    notify.WRITEOFF_WAITING,
    label=_("Write-offs waiting for approval"),
    audience="owner",
    default_telegram=True,
    queue_kind="inventory.writeoffs_to_approve",
)
