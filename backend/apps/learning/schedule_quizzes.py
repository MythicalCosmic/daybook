"""Jobs of package Q2 that run on their own (from `tasks.py`). A plain module, so `tasks.py`
stays free of the services: each looks its service up when it runs."""


def draft_questions(job_id: int) -> int:
    from apps.learning import drafting

    return drafting.run_job(job_id)


def send_daily_questions() -> int:
    from apps.learning import daily

    return daily.send_daily_questions()


def run_checks() -> int:
    from apps.learning import checks

    return checks.run_checks()


def expire_attempts() -> int:
    from apps.learning import attempts

    return attempts.expire_attempts()
