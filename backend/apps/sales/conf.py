"""`get_settings(company)`: the lazy settings row of sales and cash
(`apps.core.settings_rows.get_or_create_for`). A distributor's new row starts in invoices mode
(§14.7): it sells by invoice, not over a till; every other company starts with shift totals."""

from django.db import IntegrityError, transaction

from apps.core.settings_rows import get_or_create_for
from apps.sales.models import SalesSettings


def get_settings(company) -> SalesSettings:
    if getattr(company, "business_kind", "") != "distributor":
        return get_or_create_for(SalesSettings, company)
    row = SalesSettings.objects.filter(company=company).first()
    if row is not None:
        return row
    try:
        with transaction.atomic():
            return SalesSettings.objects.create(company=company, mode=SalesSettings.Mode.INVOICES)
    except IntegrityError:
        return SalesSettings.objects.get(company=company)
