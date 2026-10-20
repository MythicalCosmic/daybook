"""Registrations with the shared registries and signal receivers of the finance ledger.

Imported by `AppConfig.ready()`; register a function only once it exists.
"""

from django.utils.translation import gettext_lazy as _

from apps.audit import registry as audit_registry
from apps.companies.signals import company_created
from apps.console import registry
from apps.console.perms import AnyOf
from apps.core.files import register_file_check
from apps.exports.registry import register_exporter
from apps.finance import defaults, exporters, providers, services, sources
from apps.finance.audit_actions import FinanceAction
from apps.finance.models import Category, CompanyRate, Counterparty, FinanceSettings
from apps.inbox.registry import register_kind
from apps.members.permissions import Perm
from apps.members.signals import member_left

FINANCE = "finance"

audit_registry.register(FinanceAction)

# The exchange difference of a debt payment points back at the payment (services.ROW_SOURCE).
sources.register(
    "finance.transaction",
    label=_("Ledger entry"),
    url_template="/c/{company_id}/finance/transactions?txn={id}",
)
# Cash a leaver held, moved by the offboarding wizard (one transfer per account).
sources.register(
    providers.OFFBOARD_SOURCE,
    label=_("Offboarding"),
    url_template="/c/{company_id}/people/{id}",
)


# Demo rows other demos may replace (finance.demo: sales per branch and day, salaries per person).
sources.register("finance.demo", label=_("Demo data"), url_template="")


def make_defaults(sender, company, by=None, **kwargs) -> None:
    """A new company gets its cash desk, terminal and system categories."""
    defaults.ensure(company)


company_created.connect(make_defaults, dispatch_uid="finance.make_defaults")
member_left.connect(providers.on_member_left, dispatch_uid="finance.move_leaver_cash")

# Palette, badges, branch cards, briefings, portfolio, calendar --------------------------------

registry.register_search(
    "finance.transaction",
    perm=AnyOf(Perm.FINANCE_VIEW, Perm.FINANCE_RECORD),
    search=providers.search_transactions,
    feature=FINANCE,
)
registry.register_search(
    "finance.counterparty",
    perm=Perm.FINANCE_VIEW,
    search=providers.search_counterparties,
    feature=FINANCE,
)
registry.register_pulse(
    "finance.overdue", perm=Perm.FINANCE_VIEW, count=providers.overdue_count, feature=FINANCE
)
registry.register_pulse("finance.ledger", perm=None, count=None, feature=FINANCE)
registry.register_branch_facts(
    "finance", perm=Perm.FINANCE_VIEW, facts=providers.branch_facts, feature=FINANCE
)
registry.register_brief_section(
    "finance", perm=Perm.FINANCE_VIEW, order=40, build=providers.brief_section, feature=FINANCE
)
registry.register_company_facts(
    "finance", perm=Perm.FINANCE_VIEW, facts=providers.company_facts, feature=FINANCE
)
registry.register_calendar_source(
    "finance.debts_due",
    label=_("Debt due dates"),
    perm=Perm.FINANCE_VIEW,
    events=providers.calendar_events,
    feature=FINANCE,
)

# Offboarding, Get started, copy setup ------------------------------------------------------------

registry.register_offboard_step(
    "finance",
    perm=Perm.FINANCE_VIEW,
    order=40,
    label=_("Money they hold"),
    preview=providers.offboard_preview,
    feature=FINANCE,
)
registry.register_setup_step(
    "finance.opening_balances",
    perm=Perm.FINANCE_MANAGE,
    order=60,
    label=_("Opening balances"),
    description=_(
        "Enter what each cash desk, bank account and card holds today, and who owes what, so "
        "every report starts from the truth."
    ),
    url="finance/accounts?setup=opening",
    done=providers.opening_balances_done,
    feature=FINANCE,
)
registry.register_copy_part(
    "finance.categories",
    label=_("Finance categories"),
    perm=Perm.FINANCE_MANAGE,
    copy=services.copy_categories,
    feature=FINANCE,
)

# Exports ------------------------------------------------------------------------------------

register_exporter(
    "finance.transactions",
    perm=Perm.FINANCE_VIEW,
    label=_("Ledger entries"),
    columns=exporters.TRANSACTION_COLUMNS,
    rows=exporters.transaction_rows,
    sensitive=True,
    feature=FINANCE,
)
register_exporter(
    "finance.pnl",
    perm=Perm.FINANCE_VIEW,
    label=_("Profit and loss"),
    columns=exporters.PNL_COLUMNS,
    rows=exporters.pnl_rows,
    feature=FINANCE,
)
register_exporter(
    "finance.cash_flow",
    perm=Perm.FINANCE_VIEW,
    label=_("Cash flow"),
    columns=exporters.CASH_FLOW_COLUMNS,
    rows=exporters.cash_flow_rows,
    feature=FINANCE,
)
register_exporter(
    "finance.debts",
    perm=Perm.FINANCE_VIEW,
    label=_("Debts"),
    columns=exporters.DEBT_COLUMNS,
    rows=exporters.debt_rows,
    sensitive=True,
    feature=FINANCE,
)

# Notifications ------------------------------------------------------------------------------

register_kind(
    "finance.large_expense",
    label=_("A big expense was recorded"),
    audience="owner",
    default_telegram=True,
    severity="warning",
)
register_kind(
    "finance.balance_drift",
    label=_("Balances were corrected from the ledger"),
    audience="owner",
    default_telegram=False,
    severity="warning",
)

# Private files and record history ----------------------------------------------------------

register_file_check("finance.receipt", providers.receipt_check)
audit_registry.register_target(
    "transaction", Perm.FINANCE_VIEW, check=providers.transaction_history_check
)
audit_registry.register_target("debt", Perm.FINANCE_VIEW, check=providers.debt_history_check)
audit_registry.register_target(
    "moneyaccount", Perm.FINANCE_VIEW, check=providers.account_history_check
)
audit_registry.register_target(
    "transfer", Perm.FINANCE_VIEW, check=providers.transfer_history_check
)
audit_registry.register_target(
    "counterparty", Perm.FINANCE_VIEW, check=providers.company_row_check(Counterparty)
)
audit_registry.register_target(
    "category", Perm.FINANCE_VIEW, check=providers.company_row_check(Category)
)
audit_registry.register_target(
    "financesettings", Perm.FINANCE_MANAGE, check=providers.company_row_check(FinanceSettings)
)
audit_registry.register_target(
    "companyrate", Perm.FINANCE_VIEW, check=providers.company_row_check(CompanyRate)
)
