from dataclasses import dataclass

from django.conf import settings as django_settings


@dataclass(frozen=True)
class Settings:
    BOT_TOKEN: str
    FSM_REDIS_URL: str
    MINIAPP_URL: str
    PLATFORM_ADMIN_IDS: tuple[int, ...]


def load_settings() -> Settings:
    """Read from the backend's Django settings so env parsing lives in one place."""
    return Settings(
        BOT_TOKEN=django_settings.EMPLOYEE_BOT_TOKEN,
        FSM_REDIS_URL=django_settings.BOT_FSM_REDIS_URL,
        MINIAPP_URL=django_settings.EMPLOYEE_MINIAPP_URL,
        PLATFORM_ADMIN_IDS=tuple(django_settings.PLATFORM_ADMIN_TG_IDS),
    )


settings = load_settings()
