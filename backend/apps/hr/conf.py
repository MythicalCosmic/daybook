"""`get_settings(company)`: the lazy settings row of HR records
(`apps.core.settings_rows.get_or_create_for`)."""

from apps.core.settings_rows import get_or_create_for
from apps.hr.models import HRSettings


def get_settings(company) -> HRSettings:
    """The company's `HRSettings`, made with the defaults on first read."""
    return get_or_create_for(HRSettings, company)
