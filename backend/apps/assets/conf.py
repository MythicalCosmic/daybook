"""`get_settings(company)`: the lazy asset policy row (`apps.core.settings_rows`)."""

from apps.assets.models import AssetSettings
from apps.core.settings_rows import get_or_create_for


def get_settings(company) -> AssetSettings:
    """The company's `AssetSettings`, made with the defaults on first read."""
    return get_or_create_for(AssetSettings, company)
