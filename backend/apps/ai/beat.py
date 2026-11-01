"""Celery beat entries of the AI features, merged into `CELERY_BEAT_SCHEDULE`.

Read by file path when the settings load: import only the standard library and
`celery.schedules`. Keys must be unique across apps (duplicates stop the settings).
"""

from celery.schedules import crontab

SCHEDULE = {
    # The agents (apps.ai.agents): each runs when its own next time has come.
    "ai-agents-tick": {
        "task": "apps.ai.tasks.run_agents",
        "schedule": crontab(minute="*/5"),
    },
    # Ready drafts nobody used for a day expire; drafts whose job died fail.
    "ai-expire-drafts": {
        "task": "apps.ai.tasks.expire_drafts",
        "schedule": crontab(minute="*/15"),
    },
    # Voice recordings are kept `voice_retention_days` (30); the transcripts stay.
    "ai-purge-voice-notes": {
        "task": "apps.ai.tasks.purge_voice_notes",
        "schedule": crontab(hour=3, minute=40),
    },
}
