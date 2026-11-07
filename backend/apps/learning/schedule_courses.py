"""Jobs of package Q1 that run on their own (from `tasks.py`). A plain module, so `tasks.py`
stays free of the services: each looks its service up when it runs."""


def process_video(video_id: int) -> str:
    return "not built"  # Q1: apps.learning.media


def sync_audiences() -> int:
    return 0  # Q1: apps.learning.courses


def send_reminders() -> int:
    return 0  # Q1: apps.learning.reminders


def renew_due() -> int:
    return 0  # Q1: apps.learning.courses


def clean_uploads() -> int:
    return 0  # Q1: apps.learning.media
