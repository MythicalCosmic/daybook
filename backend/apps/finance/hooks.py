"""Registrations with the shared registries and signal receivers of the finance ledger.

Imported by `AppConfig.ready()`; register a function only once it exists.
"""

from django.utils.translation import gettext_lazy as _

from apps.audit import registry as audit_registry
from apps.companies.signals import company_created
from apps.finance import defaults, sources
from apps.finance.audit_actions import FinanceAction

audit_registry.register(FinanceAction)

# The exchange difference of a debt payment points back at the payment (services.ROW_SOURCE).
sources.register(
    "finance.transaction",
    label=_("Ledger entry"),
    url_template="/c/{company_id}/finance/transactions/{id}",
)


def make_defaults(sender, company, by=None, **kwargs) -> None:
    """A new company gets its cash desk, terminal and system categories."""
    defaults.ensure(company)


company_created.connect(make_defaults, dispatch_uid="finance.make_defaults")
