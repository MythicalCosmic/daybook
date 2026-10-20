import secrets
import zoneinfo
from datetime import datetime, time

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import Language, TimeStampedModel
from apps.core.money import CurrencyField, MoneyField


def generate_invite_code() -> str:
    return secrets.token_urlsafe(8)


def validate_timezone(value: str) -> None:
    if value not in zoneinfo.available_timezones():
        raise ValidationError(_("Unknown timezone: %(value)s"), params={"value": value})


class Feature(models.TextChoices):
    """Modules an owner switches on per company. `Company.features` is the only module switch."""

    FINANCE = "finance", _("Finance")
    SALES = "sales", _("Sales and cash")
    STOCK = "stock", _("Stock")
    ATTENDANCE = "attendance", _("Attendance")
    HR = "hr", _("HR")
    PAYROLL = "payroll", _("Payroll")
    AI = "ai", _("AI assistant")
    RECOGNITION = "recognition", _("Recognition")


def default_workdays() -> list[int]:
    return [0, 1, 2, 3, 4, 5]  # Monday to Saturday


def every_weekday() -> list[int]:
    return [0, 1, 2, 3, 4, 5, 6]


def weekday_field() -> models.PositiveSmallIntegerField:
    """A weekday as Python numbers it: 0 = Monday … 6 = Sunday."""
    return models.PositiveSmallIntegerField(validators=[MaxValueValidator(6)])


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
    morning_digest = models.BooleanField(
        default=True,
        help_text=_(
            "At the morning report time, everyone gets their tasks for the day from the bot."
        ),
    )
    is_active = models.BooleanField(default=True)
    base_currency = CurrencyField(
        help_text=_("The currency reports and the ledger add up in. Locked once money is booked.")
    )
    logo = models.ImageField(upload_to="logos/", blank=True)
    workdays = ArrayField(
        weekday_field(),
        default=default_workdays,
        blank=True,
        help_text=_("Days people work unless their shifts say otherwise (0 = Monday)."),
    )
    owner_sees_personal_tasks = models.BooleanField(
        default=True, help_text=_("Owners see the personal tasks employees make for themselves.")
    )
    features = ArrayField(
        models.CharField(max_length=16, choices=Feature.choices),
        default=list,
        blank=True,
        help_text=_("Modules switched on for this company."),
    )
    setup_completed_at = models.DateTimeField(
        null=True, blank=True, help_text=_("When the owner finished or dismissed Get started.")
    )
    team_directory_phones = models.BooleanField(
        default=True, help_text=_("Colleagues see each other's phone numbers in the app.")
    )

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

    def has_feature(self, feature: str) -> bool:
        return feature in self.features


class TenantQuerySet(models.QuerySet):
    def for_company(self, company):
        return self.filter(company=company)


class TenantModel(TimeStampedModel):
    """Base for every per-company model. Query it through `for_company`."""

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="%(class)ss")

    objects = TenantQuerySet.as_manager()

    class Meta:
        abstract = True


class Branch(TenantModel):
    """A shop, office or kitchen of the company. Data that happens somewhere carries one."""

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="branches")
    name = models.CharField(max_length=100)
    code = models.CharField(
        max_length=8, blank=True, help_text=_("Short code printed on shift and invoice numbers.")
    )
    address = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    geofence_m = models.PositiveSmallIntegerField(
        default=150, help_text=_("How far from the branch a check-in may be, in metres.")
    )
    opens_at = models.TimeField(null=True, blank=True)
    closes_at = models.TimeField(null=True, blank=True)
    open_weekdays = ArrayField(weekday_field(), default=every_weekday, blank=True)
    manager = models.ForeignKey(
        "members.Membership",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_branches",
    )
    cash_limit = MoneyField(
        null=True, blank=True, help_text=_("Cash above this in the branch raises an alert.")
    )
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name_plural = "branches"
        ordering = ["order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"], name="unique_branch_name_per_company"
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        manager = self.manager
        if manager is not None and manager.company_id != self.company_id:
            raise ValidationError({"manager": _("Must belong to the same company.")})
