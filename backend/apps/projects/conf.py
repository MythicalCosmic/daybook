"""`get_settings(company)`: the lazy settings row of projects
(`apps.core.settings_rows.get_or_create_for`)."""

from django.utils import translation
from django.utils.translation import gettext_lazy as _

from apps.core.settings_rows import get_or_create_for

# The lists a new project starts with; the last one is the done list.
DEFAULT_LISTS = (_("Backlog"), _("To do"), _("In progress"), _("Review"), _("Done"))


def get_settings(company):
    from apps.projects.models import ProjectSettings

    return get_or_create_for(ProjectSettings, company)


def default_list_names(company) -> list[str]:
    """The company's own default lists, else the built-in five in its language."""
    names = [str(name).strip()[:60] for name in get_settings(company).default_lists or []]
    names = [name for name in names if name]
    if len(names) >= 2:
        return names
    with translation.override(company.default_language):
        return [str(name) for name in DEFAULT_LISTS]
