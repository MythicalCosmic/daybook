from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import Language


class User(AbstractUser):
    """Everyone who logs in: dashboard users and every Telegram user who starts a bot."""

    telegram_id = models.BigIntegerField(unique=True, null=True, blank=True)
    telegram_username = models.CharField(max_length=64, blank=True)
    language = models.CharField(max_length=2, choices=Language.choices, default=Language.UZ)
    phone = models.CharField(
        max_length=20,
        blank=True,
        help_text=_("Only set from a contact the person shared in Telegram."),
    )
    employee_bot_blocked_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("When Telegram said this person blocked the employee bot."),
    )
    owner_bot_started_at = models.DateTimeField(
        null=True, blank=True, help_text=_("When this person first started the owner bot.")
    )
    owner_bot_blocked_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("When Telegram said this person blocked the owner bot."),
    )
    bot_company = models.ForeignKey(
        "companies.Company",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text=_(
            "For someone in several companies: the one the employee bot's lists and new tasks "
            "use. Empty: the one with the most open work for them."
        ),
    )
    photo = models.ImageField(upload_to="avatars/", blank=True)
    photo_checked_at = models.DateTimeField(
        null=True, blank=True, help_text=_("When the Telegram profile photo was last fetched.")
    )

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
