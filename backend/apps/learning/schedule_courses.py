"""Jobs of package Q1 that run on their own (from `tasks.py`). A plain module, so `tasks.py`
stays free of the services: each looks its service up when it runs."""


def process_video(video_id: int) -> str:
    from apps.learning import media

    return media.process_video_job(video_id)


def sync_audiences() -> int:
    return 0  # Q1: apps.learning.courses


def send_reminders() -> int:
    return 0  # Q1: apps.learning.reminders


def renew_due() -> int:
    return 0  # Q1: apps.learning.courses


def clean_uploads() -> int:
    from apps.learning import media

    return media.clean_uploads()
