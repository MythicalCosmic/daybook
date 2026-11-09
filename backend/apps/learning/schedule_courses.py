"""Jobs of package Q1 that run on their own (from `tasks.py`). A plain module, so `tasks.py`
stays free of the services: each looks its service up when it runs."""


def process_video(video_id: int) -> str:
    from apps.learning import media

    return media.process_video_job(video_id)


def sync_audiences() -> int:
    from apps.learning import courses

    return courses.sync_audiences()


def send_reminders() -> int:
    from apps.learning import reminders

    return reminders.send_reminders()


def renew_due() -> int:
    from apps.learning import courses

    return courses.renew_due()


def clean_uploads() -> int:
    from apps.learning import media

    return media.clean_uploads()


def transcribe_piece(lesson_id: int, job: str, piece: int, *, last_try: bool) -> str:
    from apps.learning import transcripts

    return transcripts.run_piece(lesson_id, job, piece, last_try=last_try)
