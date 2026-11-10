"""Celery tasks of insights, queued with `transaction.on_commit`.

Thin wrappers: services import this module to queue jobs, so it never imports
`services`; the work itself lives in plain modules both can import.
"""

from celery import shared_task


@shared_task
def detect() -> dict:
    """Every 30 minutes: run the rules for each company whose slot of the day started
    (07:00, 13:00, 19:00 company time) and send the urgent insights waiting for the end of
    the quiet hours."""
    from apps.insights import engine

    return engine.tick()


@shared_task
def detect_company(company_id: int) -> dict:
    """Run the rules for one company now."""
    from apps.companies.models import Company
    from apps.insights import engine

    company = Company.objects.filter(pk=company_id, is_active=True).first()
    if company is None:
        return {}
    return engine.run(company)
