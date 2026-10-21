"""`get_settings(company)`: the lazy settings row of sales and cash
(`apps.core.settings_rows.get_or_create_for`)."""

from apps.core.settings_rows import get_or_create_for
from apps.sales.models import SalesSettings


def get_settings(company) -> SalesSettings:
    return get_or_create_for(SalesSettings, company)
