"""Default rows of attendance for a company."""


def ensure(company) -> None:
    """Create the missing default rows. Idempotent: it runs from the `company_created`
    receiver and from `manage.py ensure_company_defaults` after every deploy."""
