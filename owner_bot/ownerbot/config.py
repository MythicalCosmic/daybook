"""The owner bot's settings, read from the backend's Django settings (one place parses env)."""

from dataclasses import dataclass

from django.conf import settings as django_settings


@dataclass(frozen=True)
class Settings:
    BOT_TOKEN: str
    FSM_REDIS_URL: str
    DASHBOARD_URL: str


def load_settings() -> Settings:
    return Settings(
        BOT_TOKEN=django_settings.OWNER_BOT_TOKEN,
        FSM_REDIS_URL=django_settings.BOT_FSM_REDIS_URL,
        DASHBOARD_URL=django_settings.DASHBOARD_URL,
    )
