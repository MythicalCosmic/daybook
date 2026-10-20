"""Default rows of the knowledge base for a company."""

from django.utils import translation
from django.utils.translation import gettext as _

from apps.knowledge.models import Space


def ensure(company) -> None:
    """Create the missing default rows. Idempotent: it runs from the `company_created`
    receiver and from `manage.py ensure_company_defaults` after every deploy.

    A company that has never had a space gets one shelf to start from, named in the company's
    language. Once any space exists (even an archived one) nothing is added again."""
    if Space.objects.filter(company=company).exists():
        return
    with translation.override(company.default_language):
        Space.objects.create(
            company=company,
            name=_("Company handbook"),
            icon="📘",
            description=_("Rules, how-tos and everything a new colleague should read first."),
        )
