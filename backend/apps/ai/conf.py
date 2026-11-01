"""`get_settings(company)`: the lazy settings row of the AI features
(`apps.core.settings_rows.get_or_create_for`), and `ai_on(company)`: whether the company's AI
is switched on (the owner's consent, the module, and no platform block)."""

from apps.ai.models import AISettings
from apps.companies.models import Feature
from apps.core.settings_rows import get_or_create_for


def get_settings(company) -> AISettings:
    return get_or_create_for(AISettings, company)


def ai_on(company, ai_settings: AISettings | None = None) -> bool:
    """An owner turned AI on, "ai" is among the company's modules and the platform hasn't
    blocked it. Claude is a separate question (apps.ai.availability): without a key the
    rules engine still turns voice and text into tasks."""
    row = ai_settings or get_settings(company)
    return row.enabled and not row.platform_blocked and company.has_feature(Feature.AI)
