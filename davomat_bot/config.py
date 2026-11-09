"""The bot's settings, read from the backend's Django settings (one place parses env), plus
the few only the bot process has: its heartbeat file and how often it looks for a new token."""

from dataclasses import dataclass

from django.conf import settings as django_settings

from davomat_bot.health import heartbeat_path


@dataclass(frozen=True)
class Settings:
    FSM_REDIS_URL: str
    DASHBOARD_URL: str
    HEARTBEAT_PATH: str
    # Seconds between looks: for a token while there is none, at the token version in Redis,
    # and at the stored token itself (in case Redis missed a change).
    TOKEN_WAIT_SECONDS: float = 30
    VERSION_CHECK_SECONDS: float = 10
    TOKEN_CHECK_SECONDS: float = 60


def load_settings() -> Settings:
    return Settings(
        FSM_REDIS_URL=django_settings.BOT_FSM_REDIS_URL,
        DASHBOARD_URL=django_settings.DASHBOARD_URL,
        HEARTBEAT_PATH=heartbeat_path(),
    )
