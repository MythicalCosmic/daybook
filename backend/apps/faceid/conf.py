"""`get_settings(company)`: the lazy settings row of Face ID, and `is_on(company)`
(`apps.core.settings_rows.get_or_create_for`)."""

from apps.companies.models import Feature
from apps.core.settings_rows import get_or_create_for
from apps.faceid.models import FaceIdSettings


def get_settings(company) -> FaceIdSettings:
    """The company's `FaceIdSettings`, made with the defaults on first read."""
    return get_or_create_for(FaceIdSettings, company)


def is_on(company) -> bool:
    """Whether the company runs Face ID (the `face_id` module): while it is off, terminals'
    events keep nothing personal and change nothing."""
    return company.has_feature(Feature.FACE_ID)


def counts_attendance(company, settings: FaceIdSettings | None = None) -> bool:
    """Whether linked people's scans check them in and out: the company runs attendance and
    Face ID's attendance switch is on."""
    settings = settings or get_settings(company)
    return settings.attendance and company.has_feature(Feature.ATTENDANCE)
