from celery import shared_task


@shared_task
def ping() -> str:
    """Smoke-test task: proves a worker is consuming from the broker."""
    return "pong"
