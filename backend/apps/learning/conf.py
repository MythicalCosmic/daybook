"""`get_settings(company)`: the lazy settings row of learning, and `is_on(company)`
(`apps.core.settings_rows.get_or_create_for`)."""

from apps.companies.models import Feature
from apps.core.settings_rows import get_or_create_for
from apps.learning.models import LearningSettings


def get_settings(company) -> LearningSettings:
    """The company's `LearningSettings`, made with the defaults on first read."""
    return get_or_create_for(LearningSettings, company)


def is_on(company) -> bool:
    """Whether the company runs learning (the `learning` module): its jobs do nothing, its
    endpoints answer 404 and its screens hide while it is off."""
    return company.has_feature(Feature.LEARNING)
