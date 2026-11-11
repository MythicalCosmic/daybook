"""`get_settings(company)`: the lazy contract reminder row (`apps.core.settings_rows`)."""

from apps.contracts.models import ContractSettings
from apps.core.settings_rows import get_or_create_for


def get_settings(company) -> ContractSettings:
    """The company's `ContractSettings`, made with the defaults on first read."""
    return get_or_create_for(ContractSettings, company)
