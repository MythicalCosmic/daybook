"""Face ID terminals (the `face_id` module): the terminals at the staff doors, every scan they
send, and which of their Employee Nos is whom.

A Hikvision face recognition terminal (MinMoe DS-K1T341AMF and its kin) recognises people
itself, against its own list (Employee No, name, face, finger, card), and posts each event to
`/api/v1/devices/hik/<token>/` (`device_api`). We never match faces: faces and templates stay on
the terminal; we keep the events and their snapshots. Every scan is kept and shown, linked to a
Daybook person or not. When the company also runs attendance and `FaceIdSettings.attendance` is
on, a linked person's scan checks them in or out (`apps.attendance.services.scan`).
"""

import secrets

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Branch, Company, TenantModel
from apps.core.crypto import EncryptedTextField
from apps.core.models import TimeStampedModel
from apps.core.storage import private_storage, private_upload_to
from apps.faceid.hikvision import number_key
from apps.members.models import Membership


class FaceIdSettings(TimeStampedModel):
    """One row per company, made on first read by `apps.faceid.conf.get_settings`. The module
    itself is on when "face_id" is in `Company.features`."""

    class Telegram(models.TextChoices):
        OFF = "off", _("Nothing")
        ARRIVALS = "arrivals", _("Who came: each person's first scan of the day")
        EVERY_SCAN = "every_scan", _("Every scan")

    class ScanMode(models.TextChoices):
        ARRIVAL = "arrival", _("People scan only when they come")
        BOTH = "both", _("People scan when they come and when they leave")

    class BotStatus(models.TextChoices):
        OK = "ok", _("Connected")
        INVALID = "invalid", _("Telegram refuses the token")
        NOT_SET = "not_set", _("Not connected")

    company = models.OneToOneField(
        Company, on_delete=models.CASCADE, related_name="faceid_settings"
    )
    attendance = models.BooleanField(
        default=True,
        help_text=_("A linked person's scan checks them in or out (when Attendance is on)."),
    )
    # How a one-door terminal's scans count (entrances and exits do what they say either way):
    # "arrival", the first scan of a work session checks in and later ones are only seen, and
    # leaving isn't recorded (the day closes quietly); "both", in, then out.
    scan_mode = models.CharField(
        max_length=8,
        choices=ScanMode.choices,
        default=ScanMode.ARRIVAL,
        db_default=ScanMode.ARRIVAL,
        help_text=_("How people use a one-door terminal: only when they come, or both ways."),
    )
    telegram = models.CharField(
        max_length=10,
        choices=Telegram.choices,
        default=Telegram.ARRIVALS,
        help_text=_("What managers who see the branch get in Telegram, with the snapshot."),
    )
    group_posts = models.BooleanField(
        default=False, help_text=_("Arrivals are also posted in the branch's attendance groups.")
    )
    group_photos = models.BooleanField(
        default=False, help_text=_("Those group posts carry the snapshot.")
    )
    notify_employee = models.BooleanField(
        default=True,
        help_text=_("A linked person gets a bot message when the terminal checks them in or out."),
    )
    alert_strangers = models.BooleanField(
        default=False,
        help_text=_("An unknown face alerts the branch's managers, at most every 10 minutes."),
    )
    repeat_minutes = models.PositiveSmallIntegerField(
        default=2,
        validators=[MinValueValidator(1), MaxValueValidator(60)],
        help_text=_("A second scan this soon after the last one changes nothing."),
    )
    photo_days = models.PositiveSmallIntegerField(
        default=30,
        validators=[MaxValueValidator(365)],
        help_text=_("Snapshots are deleted after this many days. 0: none are kept."),
    )

    # The company's own Face ID bot (`apps.faceid.bot`): when connected, everything Face ID sends
    # to Telegram goes through it. The token is kept encrypted and never shown again.
    bot_token = EncryptedTextField(plain_max_length=100, blank=True)
    bot_id = models.PositiveBigIntegerField(null=True, blank=True)
    bot_username = models.CharField(max_length=64, blank=True)
    bot_name = models.CharField(max_length=128, blank=True)
    bot_status = models.CharField(
        max_length=8, choices=BotStatus.choices, default=BotStatus.NOT_SET, db_default="not_set"
    )
    bot_checked_at = models.DateTimeField(null=True, blank=True)
    # The poller's place in the bot's updates (`getUpdates` offset), reset with the token.
    bot_offset = models.BigIntegerField(default=0, db_default=0)

    class Meta:
        verbose_name = _("Face ID settings")
        verbose_name_plural = _("Face ID settings")

    def __str__(self):
        return f"Face ID settings of {self.company}"


def new_device_token() -> str:
    """The secret in a terminal's URL path: 24 URL-safe characters (144 random bits)."""
    return secrets.token_urlsafe(18)


class FaceDevice(TenantModel):
    """A terminal at a branch's staff door. What it says about itself (address, model, clock) is
    learned from its requests."""

    class Direction(models.TextChoices):
        IN = "in", _("Entrance: every scan checks in")
        OUT = "out", _("Exit: every scan checks out")
        TOGGLE = "toggle", _("One door: in, then out")

    class Vendor(models.TextChoices):
        HIKVISION = "hikvision", _("Hikvision")

    name = models.CharField(max_length=80)
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="face_devices")
    direction = models.CharField(
        max_length=6,
        choices=Direction.choices,
        default=Direction.TOGGLE,
        help_text=_("One door: no open check-in means in, otherwise out."),
    )
    token = models.CharField(max_length=40, unique=True, default=new_device_token)
    vendor = models.CharField(max_length=12, choices=Vendor.choices, default=Vendor.HIKVISION)
    enabled = models.BooleanField(default=True)
    mac = models.CharField(max_length=32, blank=True)
    serial = models.CharField(max_length=64, blank=True)
    ip = models.CharField(max_length=45, blank=True, help_text=_("The address it reports."))
    model = models.CharField(max_length=64, blank=True)
    last_event_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(
        null=True, blank=True, help_text=_("Any request, heartbeats included.")
    )
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    clock_offset_s = models.IntegerField(
        null=True,
        blank=True,
        help_text=_("How far the terminal's clock is from ours, in seconds (ahead is positive)."),
    )
    clock_checked_at = models.DateTimeField(null=True, blank=True)
    # A terminal pointed at us for the first time uploads its whole stored history, oldest first:
    # those scans are skipped (nothing kept) and only counted.
    history_skipped = models.PositiveIntegerField(
        default=0,
        db_default=0,
        help_text=_("Old scans the terminal sent that were skipped."),
    )
    history_until = models.DateTimeField(
        null=True, blank=True, help_text=_("The newest skipped old scan's time.")
    )
    history_seen_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["name", "pk"]

    def __str__(self):
        return self.name


class FaceEvent(TenantModel):
    """One event a terminal posted, and what came of it."""

    class Kind(models.TextChoices):
        PERSON = "person", _("Person")
        STRANGER = "stranger", _("Unknown face")
        OTHER = "other", _("Other event")

    class Method(models.TextChoices):
        FACE = "face", _("Face")
        FINGERPRINT = "fingerprint", _("Fingerprint")
        CARD = "card", _("Card")
        OTHER = "other", _("Other")

    class Action(models.TextChoices):
        CHECKED_IN = "checked_in", _("Checked in")
        CHECKED_OUT = "checked_out", _("Checked out")
        SEEN = "seen", _("Scanned")
        REPEAT = "repeat", _("Repeat scan")
        NOT_LINKED = "not_linked", _("Not in Daybook")
        STRANGER = "stranger", _("Unknown face")
        IGNORED = "ignored", _("Logged only")
        MODULE_OFF = "module_off", _("Face ID is off")

    class Flag(models.TextChoices):
        CLOCK_OFF = "clock_off", _("Terminal clock is wrong")
        DELIVERED_LATE = "delivered_late", _("Arrived late, no messages")
        AUTO_LINKED = "auto_linked", _("Linked automatically")
        OTHER_BRANCH = "other_branch", _("At another branch")
        MISSED_ENTRY = "missed_entry", _("Came in without a scan")
        LATE_CHECK_OUT = "late_check_out", _("Replaced an automatic check-out")
        ALREADY_IN = "already_in", _("Already checked in")
        OUT_OF_ORDER = "out_of_order", _("Older than the attendance record")
        BREAK = "break", _("Break scan")
        NOT_APPROVED = "not_approved", _("Person not active")
        IGNORED_NUMBER = "ignored_number", _("Number ignored")
        REFUSED = "refused", _("Attendance refused it")
        UNREADABLE = "unreadable", _("Couldn't read the event")
        ALERTED = "alerted", _("Managers alerted")
        ARRIVAL = "arrival", _("First scan of the day")
        SIMULATED = "simulated", _("Test scan")

    device = models.ForeignKey(FaceDevice, on_delete=models.CASCADE, related_name="events")
    received_at = models.DateTimeField()
    event_at = models.DateTimeField(
        help_text=_("The terminal's time, or when it arrived if the terminal's clock is wrong.")
    )
    device_time = models.DateTimeField(null=True, blank=True)
    serial_no = models.PositiveBigIntegerField(null=True, blank=True)
    # As the terminal shows it ("00000002"), and without its leading zeros for matching ("2").
    employee_no = models.CharField(max_length=32, blank=True)
    number_key = models.CharField(max_length=32, blank=True)
    name_on_device = models.CharField(max_length=100, blank=True)
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.OTHER)
    method = models.CharField(max_length=12, choices=Method.choices, blank=True)
    verify_mode = models.CharField(max_length=48, blank=True)
    minor = models.PositiveIntegerField(null=True, blank=True)
    attendance_status = models.CharField(max_length=16, blank=True)
    membership = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="face_events"
    )
    # The attendance record the scan made or touched (apps.attendance; empty without it).
    record_id = models.PositiveBigIntegerField(null=True, blank=True)
    action = models.CharField(max_length=12, choices=Action.choices, default=Action.IGNORED)
    photo = models.FileField(
        storage=private_storage, upload_to=private_upload_to("faceid"), blank=True
    )
    raw = models.JSONField(default=dict, blank=True)
    flags = ArrayField(
        models.CharField(max_length=24, choices=Flag.choices), default=list, blank=True
    )

    class Meta:
        ordering = ["-event_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["device", "serial_no"],
                condition=Q(serial_no__isnull=False),
                name="faceid_event_once",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "-event_at"], name="faceid_company_at"),
            models.Index(fields=["device", "-event_at"], name="faceid_device_at"),
            models.Index(fields=["membership", "-event_at"], name="faceid_member_at"),
            models.Index(fields=["company", "number_key"], name="faceid_company_number"),
        ]

    def __str__(self):
        return f"{self.device} · {self.get_action_display()}"


class FaceLink(TenantModel):
    """Who a terminal's Employee No is in the company (a person may have several numbers), or a
    number set aside (`ignored`: a guard, a visitor's card) so it never asks again."""

    employee_no = models.CharField(max_length=32)
    # The number without its leading zeros: "00000002" and "2" are one number.
    number_key = models.CharField(max_length=32)
    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, null=True, blank=True, related_name="face_links"
    )
    ignored = models.BooleanField(default=False)
    auto = models.BooleanField(default=False, help_text=_("Linked automatically by name."))
    linked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["employee_no"]
        constraints = [
            models.UniqueConstraint(fields=["company", "number_key"], name="faceid_number_once"),
            models.CheckConstraint(
                condition=Q(membership__isnull=False) | Q(ignored=True),
                name="faceid_link_has_person",
            ),
        ]

    def __str__(self):
        return f"{self.employee_no} · {self.membership or '—'}"

    def save(self, *args, **kwargs):
        self.number_key = number_key(self.employee_no)
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = {*kwargs["update_fields"], "number_key"}
        super().save(*args, **kwargs)


class FaceBotChat(TenantModel):
    """Someone the company's Face ID bot may write to (or tried to): Telegram lets a bot write
    only to people who pressed Start in it. `started_at` is set by /start (or a delivered
    message); `refused_at` by Telegram's 403. Refused and not started since: nothing is sent
    until they press Start."""

    telegram_id = models.BigIntegerField()
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    refused_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company", "telegram_id"], name="faceid_bot_chat_once")
        ]

    def __str__(self):
        return f"{self.telegram_id} · {self.company_id}"

    @property
    def refused(self) -> bool:
        """Telegram said no (403) and they haven't pressed Start since."""
        if self.refused_at is None:
            return False
        return self.started_at is None or self.started_at < self.refused_at
