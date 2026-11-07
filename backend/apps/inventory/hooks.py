"""Registrations of stock with the shared registries (docs/PLAN-OWNER.md §14.6.4).

Imported by `AppConfig.ready()`; register a function only once it exists. Everything that a
person sees is registered with `feature="stock"`, so it is invisible and inert while the stock
module is off for the company.
"""

from django.utils.translation import gettext_lazy as _

from apps.audit import registry as audit_registry
from apps.console import registry
from apps.core.files import register_file_check
from apps.exports.registry import register_exporter
from apps.finance import sources
from apps.inbox.registry import register_action, register_kind
from apps.inventory import notify, providers
from apps.inventory.audit_actions import InventoryAction
from apps.inventory.providers import CONTROLLED, FACTS, MANAGE, READ
from apps.inventory.services import RECEIPT

FEATURE = "stock"

audit_registry.register(InventoryAction)
# A record's History tab: the people who run stock (audit targets take one permission).
for target in (
    "product",
    "stockbatch",
    "goodsreceipt",
    "stocktransfer",
    "writeoff",
    "stockcount",
    "stocksettings",
    "recallnotice",
):
    audit_registry.register_target(target, MANAGE)
audit_registry.register_target("rxrecord", CONTROLLED)
audit_registry.register_target("controlledperiod", CONTROLLED)

# Badges and version keys ------------------------------------------------------------------------

registry.register_pulse("inventory", perm=READ, count=None, feature=FEATURE)
registry.register_pulse(
    "inventory.expiring", perm=READ, count=providers.expiring_count, feature=FEATURE
)
registry.register_pulse("inventory.low", perm=READ, count=providers.low_count, feature=FEATURE)
registry.register_pulse(
    "inventory.to_post", perm=MANAGE, count=providers.receipts_to_post_count, feature=FEATURE
)
for key in ("writeoffs", "recalls", "controlled", "defektura"):
    registry.register_pulse(f"inventory.{key}", perm=READ, count=None, feature=FEATURE)

# The command palette, Needs you, the brief, Get started, the portfolio, copying setup -----------

registry.register_search(
    "inventory.product", perm=READ, search=providers.search_products, feature=FEATURE
)
registry.register_search(
    "inventory.batch", perm=READ, search=providers.search_batches, feature=FEATURE
)
registry.register_search(
    "inventory.receipt", perm=READ, search=providers.search_receipts, feature=FEATURE
)
registry.register_queue(
    "inventory.receipts_to_post",
    perm=MANAGE,
    label=_("Goods receipts to post"),
    count=providers.receipts_to_post_count,
    items=providers.receipts_to_post,
    feature=FEATURE,
)
registry.register_queue(
    "inventory.writeoffs_to_approve",
    perm=MANAGE,
    label=_("Write-offs to approve"),
    count=providers.writeoffs_count,
    items=providers.writeoffs_to_approve,
    feature=FEATURE,
)
registry.register_queue(
    "inventory.transfers_disputed",
    perm=MANAGE,
    label=_("Transfers that arrived short"),
    count=providers.disputed_count,
    items=providers.disputed_transfers,
    feature=FEATURE,
)
registry.register_brief_section(
    "inventory", perm=READ, order=25, build=providers.brief_section, feature=FEATURE
)
registry.register_setup_step(
    "inventory.catalogue",
    perm=MANAGE,
    order=80,
    label=_("Import your medicines"),
    description=_(
        "Your catalogue from a spreadsheet: names, active ingredients, barcodes, prescription "
        "flags and prices. A dry run shows what will change first."
    ),
    url="stock/products?import=1",
    done=providers.catalogue_done,
    feature=FEATURE,
)
registry.register_setup_step(
    "inventory.opening_stock",
    perm=MANAGE,
    order=81,
    label=_("Enter opening stock with series and expiry"),
    description=_(
        "What is on the shelves today, by series, expiry date and cost, so expiry warnings and "
        "the legal price caps work from day one."
    ),
    url="stock/levels?opening=1",
    done=providers.opening_done,
    feature=FEATURE,
)
registry.register_setup_step(
    "inventory.suppliers",
    perm=MANAGE,
    order=82,
    label=_("Add distributors and their payment terms"),
    description=_(
        "Each delivery opens a payable due after the distributor's terms, so you see what you "
        "owe and when."
    ),
    url="stock/suppliers",
    done=providers.suppliers_done,
    feature=FEATURE,
)
registry.register_company_facts(
    "inventory", perm=FACTS, facts=providers.company_facts, feature=FEATURE
)
registry.register_copy_part(
    "inventory.categories",
    label=_("Medicine categories"),
    perm=MANAGE,
    copy=providers.copy_categories,
    feature=FEATURE,
)
registry.register_copy_part(
    "inventory.pricing",
    label=_("Stock settings and pricing rules"),
    perm=MANAGE,
    copy=providers.copy_pricing,
    feature=FEATURE,
)

# Private files ----------------------------------------------------------------------------------

register_file_check("inventory.receipt_file", providers.may_open_receipt_file)
register_file_check("inventory.writeoff_act", providers.may_open_writeoff_act)
register_file_check("inventory.writeoff_file", providers.may_open_writeoff_file)
register_file_check("inventory.recall_file", providers.may_open_recall_file)
register_file_check("inventory.rx_photo", providers.may_open_rx_photo)
register_file_check("inventory.journal", providers.may_open_journal)

# Excel exports ----------------------------------------------------------------------------------

register_exporter(
    "inventory.levels",
    perm=READ,
    label=_("Stock by pharmacy"),
    columns=providers.LEVEL_COLUMNS,
    rows=providers.level_rows,
    feature=FEATURE,
)
register_exporter(
    "inventory.batches",
    perm=READ,
    label=_("Batches on hand"),
    columns=providers.BATCH_COLUMNS,
    rows=providers.batch_rows,
    feature=FEATURE,
)
register_exporter(
    "inventory.movements",
    perm=READ,
    label=_("Stock movements"),
    columns=providers.MOVEMENT_COLUMNS,
    rows=providers.movement_rows,
    feature=FEATURE,
)
register_exporter(
    "inventory.expiry",
    perm=READ,
    label=_("Expiring medicines"),
    columns=providers.EXPIRY_COLUMNS,
    rows=providers.expiry_rows,
    feature=FEATURE,
)
register_exporter(
    "inventory.writeoffs",
    perm=READ,
    label=_("Write-offs"),
    columns=providers.WRITEOFF_COLUMNS,
    rows=providers.writeoff_rows,
    feature=FEATURE,
)
register_exporter(
    "inventory.rx_log",
    perm=CONTROLLED,
    label=_("Prescription log"),
    columns=providers.RX_COLUMNS,
    rows=providers.rx_rows,
    sensitive=True,
    feature=FEATURE,
)
register_exporter(
    "inventory.controlled",
    perm=CONTROLLED,
    label=_("Controlled-substance register"),
    columns=providers.CONTROLLED_COLUMNS,
    rows=providers.controlled_rows,
    feature=FEATURE,
)

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
