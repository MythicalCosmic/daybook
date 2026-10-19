from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.core.models import Language


class User(AbstractUser):
    """Everyone who logs in: dashboard users and every Telegram user who starts a bot."""

    telegram_id = models.BigIntegerField(unique=True, null=True, blank=True)
    telegram_username = models.CharField(max_length=64, blank=True)
    language = models.CharField(max_length=2, choices=Language.choices, default=Language.UZ)

    def __str__(self):
        if full_name := self.get_full_name():
            return full_name
        if self.telegram_username:
            return f"@{self.telegram_username}"
        return self.username

    @property
    def is_platform_admin(self) -> bool:
        return self.is_superuser or (
            self.telegram_id is not None and self.telegram_id in settings.PLATFORM_ADMIN_TG_IDS
        )
