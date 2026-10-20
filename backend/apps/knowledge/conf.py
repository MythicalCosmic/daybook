"""`get_settings(company)`: the lazy settings row of the knowledge base
(`apps.core.settings_rows.get_or_create_for`)."""

from apps.core.settings_rows import get_or_create_for
from apps.knowledge.models import KnowledgeSettings


def get_settings(company) -> KnowledgeSettings:
    return get_or_create_for(KnowledgeSettings, company)
