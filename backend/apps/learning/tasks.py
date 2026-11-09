"""Celery tasks of learning, queued with `transaction.on_commit`.

Thin wrappers: services import this module to queue jobs, so it never imports `services`; the
work lives in `schedule_courses.py` (Q1) and `schedule_quizzes.py` (Q2), which both can import.
`process_video` runs on the "media" queue (its own worker, ffmpeg); `transcribe_lesson` and
`draft_questions` on "ai".
"""

from celery import shared_task

from apps.learning import schedule_courses, schedule_quizzes

# Q1 ---------------------------------------------------------------------------------------


@shared_task(queue="media", acks_late=True)
def process_video(video_id: int) -> str:
    """Probe an uploaded video, make the 720p MP4 and the poster, delete the original."""
    return schedule_courses.process_video(video_id)


@shared_task
def sync_audiences() -> int:
    return schedule_courses.sync_audiences()


@shared_task
def send_reminders() -> int:
    return schedule_courses.send_reminders()


@shared_task
def renew_due() -> int:
    return schedule_courses.renew_due()


@shared_task
def clean_uploads() -> int:
    return schedule_courses.clean_uploads()


# The speech service answers 503 while it loads its models: the piece tries again this often.
TRANSCRIBE_RETRIES = 5
TRANSCRIBE_RETRY_SECONDS = 20


@shared_task(bind=True, queue="ai", max_retries=TRANSCRIBE_RETRIES)
def transcribe_lesson(self, lesson_id: int, job: str, piece: int) -> str:
    """One piece of a lesson video's sound to the speech service, then the next
    (`transcripts.py`)."""
    outcome = schedule_courses.transcribe_piece(
        lesson_id, job, piece, last_try=self.request.retries >= TRANSCRIBE_RETRIES
    )
    if outcome == "busy":
        raise self.retry(countdown=TRANSCRIBE_RETRY_SECONDS)
    return outcome


# Q2 ---------------------------------------------------------------------------------------


@shared_task(queue="ai")
def draft_questions(job_id: int) -> int:
    """Write questions from a page or a lesson (Claude, or the rules without it)."""
    return schedule_quizzes.draft_questions(job_id)


@shared_task
def send_daily_questions() -> int:
    return schedule_quizzes.send_daily_questions()


@shared_task
def run_checks() -> int:
    return schedule_quizzes.run_checks()


@shared_task
def expire_attempts() -> int:
    return schedule_quizzes.expire_attempts()
