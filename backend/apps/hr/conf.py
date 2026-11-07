"""`get_settings(company)`: the lazy settings row of HR records
(`apps.core.settings_rows.get_or_create_for`)."""

from apps.core.settings_rows import get_or_create_for
from apps.hr.models import HRSettings


def get_settings(company) -> HRSettings:
    """The company's `HRSettings`, made with the defaults on first read."""
    return get_or_create_for(HRSettings, company)


def pharmacist_position_ids(settings: HRSettings) -> set[int]:
    """The positions that count as a pharmacist on duty."""
    return set(settings.pharmacist_positions.values_list("pk", flat=True))


def coverage_settings(company) -> HRSettings | None:
    """The settings while the pharmacist coverage rule runs for `company` (docs/PLAN-OWNER.md
    §14.9): HR switched on, the rule on, and the pharmacist positions chosen. None otherwise:
    nothing is checked, shown as a gap or sent, so a company sees no change until it sets
    the rule up."""
    if not company.has_feature("hr"):
        return None
    settings = get_settings(company)
    if not settings.coverage_enabled or not pharmacist_position_ids(settings):
        return None
    return settings
