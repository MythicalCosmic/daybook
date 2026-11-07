"""Default rows of learning for a company."""


def ensure(company) -> None:
    """Create the missing default rows. Idempotent: it runs from the `company_created`
    receiver and from `manage.py ensure_company_defaults` after every deploy.

    Learning makes nothing on its own: the settings row is lazy (`conf.get_settings`) and the
    pharmacy topics are one click in the dashboard."""
