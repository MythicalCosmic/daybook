"""Celery tasks of the AI features, queued with `transaction.on_commit`. They run on the `ai`
queue (`CELERY_TASK_ROUTES`), never next to the reminder engine.

Thin wrappers: services import this module to queue jobs, so it never imports `services`;
the work itself lives in plain modules both can import.
"""

from celery import shared_task

from apps.ai import drafts, speech

# The speech service answers 503 while it loads its models: try again this often.
SPEECH_RETRY_SECONDS = 20
SPEECH_RETRIES = 5


@shared_task(bind=True, max_retries=SPEECH_RETRIES)
def process_draft(self, draft_id: int) -> None:
    try:
        drafts.process(draft_id)
    except speech.SpeechBusy as exc:
        if self.request.retries >= SPEECH_RETRIES:
            drafts.fail(draft_id, exc.code)
            return
        raise self.retry(countdown=SPEECH_RETRY_SECONDS) from exc


@shared_task
def expire_drafts() -> int:
    return drafts.expire_stale()


@shared_task
def purge_voice_notes() -> int:
    return drafts.purge_audio()


@shared_task
def run_agents() -> int:
    """The beat tick: every scheduled agent whose time has come."""
    from apps.ai.agents import runner

    return runner.tick()


@shared_task
def run_agent(state_id: int) -> int:
    """ "Run now" from the dashboard."""
    from apps.ai.agents import runner

    return runner.run_state(state_id, forced=True)


@shared_task
def check_proof_photo(task_id: int, completed_at: str) -> str | None:
    from apps.ai.agents import photo_checker

    return photo_checker.check(task_id, completed_at)


@shared_task
def run_turn(turn_id: int) -> None:
    """One Ask AI question: the tool loop and the answer."""
    from apps.ai import chat

    chat.run_turn(turn_id)
