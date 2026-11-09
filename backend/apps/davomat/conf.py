"""The edition switch and Davomat's lazy settings row.

is_on()                  settings.EDITION == "davomat": everything Davomat-only checks it
organization()           the install's one organization (None before the first-run setup)
get_settings(company)    its `DavomatSettings`, made with the defaults on first read
"""

from django.conf import settings

from apps.companies.models import Company
from apps.core.settings_rows import get_or_create_for
from apps.davomat.models import DavomatSettings

DAVOMAT = "davomat"
DAYBOOK = "daybook"
PRODUCT = "Davomat"


def edition() -> str:
    return getattr(settings, "EDITION", DAYBOOK)


def is_on() -> bool:
    """Whether this install runs the Davomat edition. Daybook behaves exactly as before."""
    return edition() == DAVOMAT


def organization() -> Company | None:
    """The organization this install serves: its one company (the first active one, should
    there ever be several), or None while the first-run setup hasn't happened."""
    return Company.objects.filter(is_active=True).order_by("pk").first()


def get_settings(company) -> DavomatSettings:
    """The company's `DavomatSettings`, made with the defaults on first read."""
    return get_or_create_for(DavomatSettings, company)


def product_name(company: Company | None) -> str:
    if company is None:
        return PRODUCT
    row = DavomatSettings.objects.filter(company=company).only("product_name").first()
    return (row.product_name if row is not None else "") or PRODUCT
