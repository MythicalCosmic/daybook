"""`get_settings(company)`: the lazy settings row of attendance
(`apps.core.settings_rows.get_or_create_for`)."""

from apps.attendance.models import AttendanceSettings
from apps.core.settings_rows import get_or_create_for


def get_settings(company) -> AttendanceSettings:
    """The company's `AttendanceSettings`, made with the defaults on first read."""
    return get_or_create_for(AttendanceSettings, company)
