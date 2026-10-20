"""Lazy per-company settings rows (FinanceSettings, SalesSettings…), created on first read.

Each module's `conf.get_settings(company)` calls `get_or_create_for(SettingsModel, company)`.
The model has a unique link to the company (a `OneToOneField` or a unique `company` FK) and a
default for every other field, so a row can always be made from the company alone.
"""

from django.db import IntegrityError, models, transaction


def get_or_create_for[M: models.Model](model: type[M], company) -> M:
    """The company's row of `model`, created with the field defaults when it doesn't exist.

    Safe under concurrency: when two requests create the row at once, the loser of the unique
    constraint reads the winner's row instead of failing.
    """
    row = model._default_manager.filter(company=company).first()
    if row is not None:
        return row
    try:
        with transaction.atomic():
            return model._default_manager.create(company=company)
    except IntegrityError:
        return model._default_manager.get(company=company)
