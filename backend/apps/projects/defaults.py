"""Default rows of projects for a company."""

from apps.projects import conf


def ensure(company) -> None:
    """Create the missing default rows. Idempotent: it runs from the `company_created`
    receiver and from `manage.py ensure_company_defaults` after every deploy. Projects only
    need the company's settings row (the default lists live in it)."""
    conf.get_settings(company)
