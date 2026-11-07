"""`get_settings(company)`: the lazy settings row of recognition, and `is_on(company)`
(`apps.core.settings_rows.get_or_create_for`)."""

from apps.companies.models import Feature
from apps.core.settings_rows import get_or_create_for
from apps.recognition.models import RecognitionSettings


def get_settings(company) -> RecognitionSettings:
    """The company's `RecognitionSettings`, made with the defaults on first read."""
    return get_or_create_for(RecognitionSettings, company)


def is_on(company) -> bool:
    """Whether the company runs recognition (the `recognition` module): nothing is awarded,
    counted or shown while it is off."""
    return company.has_feature(Feature.RECOGNITION)
