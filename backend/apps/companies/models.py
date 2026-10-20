import secrets
import zoneinfo
from datetime import datetime, time

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import Language, TimeStampedModel


def generate_invite_code() -> str:
    return secrets.token_urlsafe(8)


def validate_timezone(value: str) -> None:
    if value not in zoneinfo.available_timezones():
        raise ValidationError(_("Unknown timezone: %(value)s"), params={"value": value})


class Company(TimeStampedModel):
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    timezone = models.CharField(
        max_length=64, default="Asia/Tashkent", validators=[validate_timezone]
    )
    default_language = models.CharField(max_length=2, choices=Language.choices, default=Language.UZ)
    invite_code = models.CharField(
        max_length=32, unique=True, default=generate_invite_code, editable=False
    )
    rejoin_cooldown_hours = models.PositiveIntegerField(
        default=24, help_text=_("How long a rejected person waits before asking to join again.")
    )
    morning_report_at = models.TimeField(
        default=time(9, 0), help_text=_("When groups get today's plan, in the company's timezone.")
    )
    evening_report_at = models.TimeField(
        default=time(20, 0), help_text=_("When groups get the end-of-day summary.")
    )
    is_active = models.BooleanField(default=True)

    INVITE_PREFIX = "c_"

    class Meta:
        verbose_name_plural = "companies"
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def invite_start_param(self) -> str:
        return f"{self.INVITE_PREFIX}{self.invite_code}"

    @property
    def invite_link(self) -> str:
        if not settings.EMPLOYEE_BOT_USERNAME:
            return ""
        return f"https://t.me/{settings.EMPLOYEE_BOT_USERNAME}?start={self.invite_start_param}"

    def format_datetime(self, value: datetime) -> str:
        """Format a moment in the company's own timezone."""
        return timezone.localtime(value, zoneinfo.ZoneInfo(self.timezone)).strftime(
            "%d.%m.%Y %H:%M"
        )

    def regenerate_invite_code(self) -> None:
        self.invite_code = generate_invite_code()
        self.save(update_fields=["invite_code", "updated_at"])


class TenantQuerySet(models.QuerySet):
    def for_company(self, company):
        return self.filter(company=company)


class TenantModel(TimeStampedModel):
    """Base for every per-company model. Query it through `for_company`."""

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="%(class)ss")

    objects = TenantQuerySet.as_manager()

    class Meta:
        abstract = True
