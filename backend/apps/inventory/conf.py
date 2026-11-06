"""`get_settings(company)`: the lazy settings row of stock (`StockSettings`).

Like `apps.core.settings_rows.get_or_create_for`, plus one default read from the company when
the row is made: the prescription log is on for a pharmacy (or both) and off for a distributor.
"""

from django.db import IntegrityError, transaction

from apps.companies.models import BusinessKind
from apps.inventory.models import StockSettings


def get_settings(company) -> StockSettings:
    """The company's `StockSettings`, made with the defaults on first read."""
    row = StockSettings.objects.filter(company=company).first()
    if row is not None:
        return row
    try:
        with transaction.atomic():
            return StockSettings.objects.create(
                company=company, rx_log=company.business_kind != BusinessKind.DISTRIBUTOR
            )
    except IntegrityError:
        return StockSettings.objects.get(company=company)


def locked_settings(company) -> StockSettings:
    """The row under `select_for_update`, for taking a document number."""
    get_settings(company)
    return StockSettings.objects.select_for_update().get(company=company)
