"""Celery tasks of business goals. Thin wrappers: the work lives in `services`."""

from celery import shared_task


@shared_task
def weekly_goals() -> int:
    """Monday morning: a point for every live goal, and a note to the owners for each goal that
    turned at risk or off track."""
    from apps.goals import services

    return services.weekly()
