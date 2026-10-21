"""`get_settings(company)`: the lazy settings row of the company calendar
(`apps.core.settings_rows.get_or_create_for`)."""

from apps.agenda.models import AgendaSettings
from apps.core.settings_rows import get_or_create_for


def get_settings(company) -> AgendaSettings:
    return get_or_create_for(AgendaSettings, company)
