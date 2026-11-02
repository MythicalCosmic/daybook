"""The automatic bonuses and fines (`AdjustmentRule`): a plain module the services and the
Celery jobs use. Filled in with the rules engine."""


def evaluate_monthly(company, period, *, by=None) -> int:
    """Propose the month's rule adjustments; returns how many changed."""
    return 0


def evaluate_daily(company, today, *, now=None) -> int:
    """Propose the daily rules' adjustments up to yesterday; returns how many changed."""
    return 0
