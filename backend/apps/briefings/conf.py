"""`get_settings(company)`: the lazy settings row of briefings
(`apps.core.settings_rows.get_or_create_for`)."""

from apps.briefings.models import BriefingSettings
from apps.core.settings_rows import get_or_create_for


def get_settings(company) -> BriefingSettings:
    return get_or_create_for(BriefingSettings, company)
