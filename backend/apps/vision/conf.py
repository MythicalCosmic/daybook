"""`get_settings(company)`: the lazy settings row of Ko‘z, and `is_on(company)`
(`apps.core.settings_rows.get_or_create_for`)."""

from apps.companies.models import Feature
from apps.core.settings_rows import get_or_create_for
from apps.vision.models import VisionSettings


def get_settings(company) -> VisionSettings:
    """The company's `VisionSettings`, made with the defaults on first read."""
    return get_or_create_for(VisionSettings, company)


def is_on(company) -> bool:
    """Whether the company runs Ko‘z (the `vision` module): while it is off its endpoints answer
    404, its boxes are refused (403 `module_off`) and its jobs leave it alone."""
    return company.has_feature(Feature.VISION)


def sells(company) -> bool:
    """Receipts and conversion need the sales module (docs/KOZ.md §2)."""
    return company.has_feature(Feature.SALES)


def tracks_attendance(company) -> bool:
    """Who is on shift and the people checked in need the attendance module."""
    return company.has_feature(Feature.ATTENDANCE)
