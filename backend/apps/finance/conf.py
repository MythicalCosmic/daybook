"""`get_settings(company)`: the lazy settings row of the finance ledger
(`apps.core.settings_rows.get_or_create_for`)."""

from apps.core.settings_rows import get_or_create_for
from apps.finance.models import FinanceSettings


def get_settings(company) -> FinanceSettings:
    """The company's `FinanceSettings`, made with the defaults on first read."""
    return get_or_create_for(FinanceSettings, company)
