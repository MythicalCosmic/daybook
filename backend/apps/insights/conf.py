"""`get_settings(company)`: the lazy settings row of insights
(`apps.core.settings_rows.get_or_create_for`)."""

from apps.core.settings_rows import get_or_create_for
from apps.insights.models import InsightSettings


def get_settings(company) -> InsightSettings:
    """The company's `InsightSettings`, made with the defaults on first read."""
    return get_or_create_for(InsightSettings, company)
