"""Jobs of package Q2 that run on their own (from `tasks.py`). A plain module, so `tasks.py`
stays free of the services: each looks its service up when it runs."""


def draft_questions(job_id: int) -> int:
    return 0  # Q2: apps.learning.drafting


def send_daily_questions() -> int:
    return 0  # Q2: apps.learning.daily


def run_checks() -> int:
    return 0  # Q2: apps.learning.checks


def expire_attempts() -> int:
    return 0  # Q2: apps.learning.attempts
