"""Davomat (docs/DAVOMAT.md): the standalone Face ID attendance edition of Daybook.

One install is one organization: one `Company`, many branches. Its people are `Membership`s, as
everywhere in Daybook:

* **Users** sign in to the web app with a username and a password; their role says what they
  may do (owner, administrator, manager, viewer: `queries.role_kind`).
* **Employees** scan at the terminals and never sign in: a membership with an `Employee` row
  (added by hand, from a list, or by a terminal's unknown number). An employee may be a user too.

Telegram is one bot per install, the organization's own: its token is stored encrypted
(`DavomatSettings.bot_token`); people link their Telegram with a one-time code (`TelegramLink`).
"""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Company, TenantModel
from apps.core.crypto import EncryptedTextField
from apps.core.models import TimeStampedModel
from apps.members.models import Membership


class DavomatSettings(TimeStampedModel):
    """One row per company, made on first read by `apps.davomat.conf.get_settings`."""

    class BotStatus(models.TextChoices):
        OK = "ok", _("Connected")
        INVALID = "invalid", _("Telegram refuses the token")
        NOT_SET = "not_set", _("Not connected")

    company = models.OneToOneField(
        Company, on_delete=models.CASCADE, related_name="davomat_settings"
    )
    product_name = models.CharField(
        max_length=60,
        blank=True,
        help_text=_("The app's name on the sign-in page and in the bot. Empty: Davomat."),
    )
    auto_create_employees = models.BooleanField(
        default=True,
        help_text=_("A terminal's unknown number becomes a new employee, named as on it."),
    )
    bot_token = EncryptedTextField(plain_max_length=100, blank=True)
    bot_id = models.PositiveBigIntegerField(null=True, blank=True)
    bot_username = models.CharField(max_length=64, blank=True)
    bot_name = models.CharField(max_length=128, blank=True)
    bot_status = models.CharField(
        max_length=8, choices=BotStatus.choices, default=BotStatus.NOT_SET
    )
    bot_checked_at = models.DateTimeField(null=True, blank=True)
    # Bumped on every token change (and written to Redis): the bot restarts with the new one.
    token_version = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("Davomat settings")
        verbose_name_plural = _("Davomat settings")

    def __str__(self):
        return f"Davomat settings of {self.company}"


class Employee(TenantModel):
    """Someone who scans at the terminals (`membership`); they never sign in unless they are a
    user too. Name, position, department and branches live on the membership, the phone and
    the photo on its user, the hire date on HR's profile (`hr.queries.employment_dates`)."""

    class Source(models.TextChoices):
        MANUAL = "manual", _("Added by hand")
        IMPORT = "import", _("Imported from a list")
        TERMINAL = "terminal", _("Added by a terminal")

    membership = models.OneToOneField(
        Membership, on_delete=models.CASCADE, related_name="davomat_employee"
    )
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.MANUAL)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return str(self.membership)


class TelegramLink(TenantModel):
    """A one-time code that links whoever opens it in the organization's bot to `membership`
    (`/start link_<code>`). Only its hash is kept; it works once, for `LIFETIME`."""

    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="davomat_telegram_links"
    )
    code_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    telegram_id = models.BigIntegerField(
        null=True, blank=True, help_text=_("The Telegram account that used it.")
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["membership", "used_at"], name="davomat_link_open")]

    def __str__(self):
        return f"Telegram link for {self.membership}"
