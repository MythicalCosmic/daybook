"""Celery tasks of fixed assets: thin wrappers over `posting` and `watch`."""

from celery import shared_task


@shared_task
def post_depreciation() -> int:
    """Every finished month posted and booked, for each company with the assets module."""
    from apps.assets import posting
    from apps.companies.models import Company, Feature

    made = 0
    for company in Company.objects.filter(features__contains=[Feature.ASSETS], is_active=True):
        made += posting.post_company(company)
        posting.book_company(company)
    return made


@shared_task
def watch_upkeep() -> int:
    from apps.assets import watch

    return watch.watch_upkeep()
