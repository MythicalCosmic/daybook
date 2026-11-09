"""Models of attendance (docs/PLAN-OWNER.md §3.10).

Expected work lives in `WorkShift` rows (§2.7): weekly or rotating `WorkSchedule`s generate them
14 days ahead, the roster adds and moves them by hand, swaps hand them over. What really
happened lives in `AttendanceRecord`: one row per person and shift (or per unscheduled day),
from the check-in tap to the check-out. Location is read only at those taps.

Roster changes made in the dashboard start as drafts (`WorkShift.published_at` is empty): only
published shifts are expected work, appear in the employee app and earn nudges or absences.
Shifts generated from a person's schedule are published at once, because assigning the
schedule was the decision.
"""

import secrets

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Branch, Company, TenantModel, TenantQuerySet, weekday_field
from apps.core.models import TimeStampedModel
from apps.core.storage import private_storage, private_upload_to
from apps.members.models import Membership, Position
from apps.timeoff.models import TimeOff


def minutes_field(default: int, *, maximum: int = 24 * 60, **kwargs) -> models.PositiveIntegerField:
    return models.PositiveIntegerField(
        default=default, validators=[MaxValueValidator(maximum)], **kwargs
    )


class AttendanceSettings(TimeStampedModel):
    """One row per company, made on first read by `apps.attendance.conf.get_settings`. There is
    no "enabled" flag: the module is on when "attendance" is in `Company.features`."""

    class OutsideAction(models.TextChoices):
        FLAG = "flag", _("Allow and mark it")
        REJECT = "reject", _("Refuse the check-in")

    company = models.OneToOneField(
        Company, on_delete=models.CASCADE, related_name="attendance_settings"
    )
    require_location = models.BooleanField(
        default=True, help_text=_("People share their location when they check in or out.")
    )
    require_photo = models.BooleanField(
        default=False, help_text=_("People take a selfie when they check in.")
    )
    outside_action = models.CharField(
        max_length=6,
        choices=OutsideAction.choices,
        default=OutsideAction.FLAG,
        help_text=_("What happens when someone checks in outside the branch's geofence."),
    )
    grace_minutes = minutes_field(
        10, maximum=240, help_text=_("Minutes after the shift starts that still count as on time.")
    )
    early_leave_grace_minutes = minutes_field(
        10,
        maximum=240,
        help_text=_("Minutes before the shift ends that still count as a full day."),
    )
    remind_after_minutes = minutes_field(
        10, maximum=240, help_text=_("Remind someone who hasn't checked in this long after start.")
    )
    no_show_alert_minutes = minutes_field(
        30, maximum=480, help_text=_("Tell managers when someone hasn't checked in by then.")
    )
    auto_close_after_hours = models.PositiveSmallIntegerField(
        default=3,
        validators=[MinValueValidator(1), MaxValueValidator(24)],
        help_text=_("Close a forgotten check-out this many hours after the shift ends."),
    )
    max_accuracy_m = models.PositiveIntegerField(
        default=200,
        validators=[MinValueValidator(10), MaxValueValidator(5000)],
        help_text=_("Locations less precise than this are marked as low accuracy."),
    )
    tasks_follow_shifts = models.BooleanField(
        default=False, help_text=_("No daily tasks on a rostered day off.")
    )
    swaps_need_approval = models.BooleanField(
        default=True, help_text=_("A manager approves swaps and covers after the colleague agrees.")
    )
    open_shift_claim_needs_approval = models.BooleanField(
        default=True, help_text=_("A manager approves who takes an open shift.")
    )
    pre_shift_reminder_minutes = minutes_field(
        0, maximum=240, help_text=_("Remind people this long before their shift. 0: no reminder.")
    )
    early_check_in_minutes = minutes_field(
        120, maximum=480, help_text=_("How early a check-in still belongs to the coming shift.")
    )
    overtime_after_minutes = minutes_field(
        15, maximum=240, help_text=_("Extra time shorter than this isn't overtime.")
    )
    # Face ID terminals (FaceDevice): what a recognised face sets off.
    face_notify_employee = models.BooleanField(
        default=True,
        help_text=_("People get a bot message when the terminal checks them in or out."),
    )
    face_group_posts = models.BooleanField(
        default=False,
        help_text=_("Each arrival at a terminal is posted in the branch's attendance groups."),
    )
    face_group_photos = models.BooleanField(
        default=False, help_text=_("Those group posts carry the terminal's snapshot.")
    )
    face_alert_strangers = models.BooleanField(
        default=False,
        help_text=_("An unknown face alerts the branch's managers, at most every 10 minutes."),
    )
    face_repeat_minutes = models.PositiveSmallIntegerField(
        default=2,
        validators=[MinValueValidator(1), MaxValueValidator(60)],
        help_text=_("A second scan this soon after the last one changes nothing."),
    )
    face_photo_days = models.PositiveSmallIntegerField(
        default=30,
        validators=[MaxValueValidator(365)],
        help_text=_("Terminal snapshots are deleted after this many days. 0: none are kept."),
    )

    class Meta:
        verbose_name = _("attendance settings")
        verbose_name_plural = _("attendance settings")

    def __str__(self):
        return f"Attendance settings of {self.company}"


class ShiftTemplate(TenantModel):
    """A ready-made shift ("Morning 09:00-18:00") the roster builder drops onto a day."""

    name = models.CharField(max_length=60)
    starts_at = models.TimeField()
    ends_at = models.TimeField(help_text=_("Earlier than the start: the shift ends the next day."))
    break_minutes = minutes_field(60, maximum=480)
    color = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1), MaxValueValidator(8)]
    )
    position = models.ForeignKey(
        Position, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "starts_at", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"], name="attendance_unique_template_name"
            ),
        ]

    def __str__(self):
        return f"{self.name} {self.starts_at:%H:%M}–{self.ends_at:%H:%M}"


class WorkSchedule(TenantModel):
    """A working pattern people follow: the same hours each weekday, a rotation such as two
    days on and two off, or flexible hours (no shifts are generated for those)."""

    class Kind(models.TextChoices):
        WEEKLY = "weekly", _("Weekly")
        ROTATING = "rotating", _("Rotating")
        FLEXIBLE = "flexible", _("Flexible")

    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.WEEKLY)
    rotation = models.CharField(
        max_length=31,
        blank=True,
        validators=[RegexValidator(r"^[WO]*$", _("Use W for a work day and O for a day off."))],
        help_text=_('Rotating schedules: W for a work day, O for a day off, e.g. "WWOO".'),
    )
    rotation_start = models.DateField(
        null=True, blank=True, help_text=_("The day the rotation's first letter falls on.")
    )
    rotation_starts_at = models.TimeField(null=True, blank=True)
    rotation_ends_at = models.TimeField(
        null=True, blank=True, help_text=_("Earlier than the start: the shift ends the next day.")
    )
    rotation_break_minutes = minutes_field(60, maximum=480)
    color = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1), MaxValueValidator(8)]
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"],
                condition=Q(is_active=True),
                name="attendance_unique_active_schedule_name",
            ),
        ]

    def __str__(self):
        return self.name


class WorkScheduleDay(models.Model):
    """A weekly schedule's hours on one weekday; a weekday without a row is a day off."""

    schedule = models.ForeignKey(WorkSchedule, on_delete=models.CASCADE, related_name="days")
    weekday = weekday_field()
    starts_at = models.TimeField()
    ends_at = models.TimeField(help_text=_("Earlier than the start: the shift ends the next day."))
    break_minutes = minutes_field(60, maximum=480)

    class Meta:
        ordering = ["weekday"]
        constraints = [
            models.UniqueConstraint(
                fields=["schedule", "weekday"], name="attendance_one_schedule_day_per_weekday"
            ),
        ]

    def __str__(self):
        return f"{self.schedule} · {self.weekday}"


class MemberSchedule(TenantModel):
    """Which schedule a person follows from which day. Where they check in by default is
    `Membership.home_branch`; there is no second home branch here."""

    membership = models.OneToOneField(
        Membership, on_delete=models.CASCADE, related_name="work_schedule"
    )
    schedule = models.ForeignKey(
        WorkSchedule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assignments",
    )
    effective_from = models.DateField()

    def __str__(self):
        return f"{self.membership}: {self.schedule or '—'}"


class WorkShiftQuerySet(TenantQuerySet):
    def live(self):
        """Published shifts that still stand: what people are expected to work."""
        return self.filter(published_at__isnull=False).exclude(status=WorkShift.Status.CANCELLED)

    def working(self):
        """Live shifts someone works (not leave, not open)."""
        return self.live().filter(status=WorkShift.Status.PLANNED, membership__isnull=False)


class WorkShift(TenantModel):
    """One shift of expected work. `membership` empty: an open shift anyone eligible may
    claim. `date` is the local day it starts on; an overnight shift belongs to that day."""

    class Status(models.TextChoices):
        PLANNED = "planned", _("Planned")
        OPEN = "open", _("Open")
        LEAVE = "leave", _("On leave")
        CANCELLED = "cancelled", _("Cancelled")

    class Source(models.TextChoices):
        SCHEDULE = "schedule", _("From the schedule")
        MANUAL = "manual", _("Added by hand")
        SWAP = "swap", _("Swapped or covered")

    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, null=True, blank=True, related_name="work_shifts"
    )
    date = models.DateField()
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    break_minutes = minutes_field(60, maximum=480)
    branch = models.ForeignKey(
        Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="work_shifts"
    )
    position = models.ForeignKey(
        Position,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text=_("Who may claim an open shift."),
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PLANNED)
    time_off = models.ForeignKey(
        TimeOff, on_delete=models.SET_NULL, null=True, blank=True, related_name="work_shifts"
    )
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.MANUAL)
    note = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    published_at = models.DateTimeField(
        null=True, blank=True, help_text=_("Empty: a roster draft only managers see.")
    )

    objects = WorkShiftQuerySet.as_manager()

    class Meta:
        ordering = ["starts_at", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["membership", "date", "starts_at"],
                condition=Q(membership__isnull=False) & ~Q(status="cancelled"),
                name="attendance_one_shift_per_start",
            ),
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")), name="attendance_shift_ends_after_start"
            ),
        ]
        indexes = [
            models.Index(fields=["company", "date"]),
            models.Index(fields=["membership", "date"]),
        ]

    def __str__(self):
        who = self.membership or _("Open shift")
        return f"{who} · {self.date:%d.%m}"

    @property
    def minutes(self) -> int:
        """Planned working minutes, the break left out."""
        span = int((self.ends_at - self.starts_at).total_seconds() // 60)
        return max(0, span - self.break_minutes)

    @property
    def is_published(self) -> bool:
        return self.published_at is not None


class ShiftSwap(TenantModel):
    """A request to hand a shift over: **cover** offers my shift to a named colleague or anyone
    eligible, **swap** exchanges two shifts, **claim** takes an open shift. The colleague
    accepts; when the settings ask for it a manager then approves (queue `attendance.swaps`)."""

    class Kind(models.TextChoices):
        COVER = "cover", _("Cover")
        SWAP = "swap", _("Swap")
        CLAIM = "claim", _("Claim an open shift")

    class Status(models.TextChoices):
        REQUESTED = "requested", _("Waiting for a colleague")
        ACCEPTED = "accepted", _("Waiting for approval")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")
        CANCELLED = "cancelled", _("Cancelled")
        EXPIRED = "expired", _("Expired")

    OPEN_STATUSES = (Status.REQUESTED, Status.ACCEPTED)

    shift = models.ForeignKey(WorkShift, on_delete=models.CASCADE, related_name="swaps")
    requested_by = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="swap_requests"
    )
    kind = models.CharField(max_length=5, choices=Kind.choices)
    other_shift = models.ForeignKey(
        WorkShift, on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    target = models.ForeignKey(
        Membership,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="swaps_offered",
        help_text=_("The colleague asked; empty: anyone eligible."),
    )
    accepted_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.REQUESTED)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True)
    decision_note = models.CharField(max_length=300, blank=True)
    expires_at = models.DateTimeField(help_text=_("The shift's start: the request lapses then."))

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["company", "status"])]

    def __str__(self):
        return f"{self.get_kind_display()} · {self.shift}"

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN_STATUSES


class AttendanceRecord(TenantModel):
    """What happened on one shift (or one unscheduled day): check-in, check-out, where, and
    the minutes that follow from them."""

    class Status(models.TextChoices):
        OPEN = "open", _("Checked in")
        CLOSED = "closed", _("Checked out")
        AUTO_CLOSED = "auto_closed", _("Closed automatically")
        ABSENT = "absent", _("Absent")
        EXCUSED = "excused", _("Excused")

    class Source(models.TextChoices):
        APP = "app", _("Mini app")
        BOT = "bot", _("Bot")
        MANUAL = "manual", _("Manager")
        SYSTEM = "system", _("System")
        FACE = "face", _("Face ID terminal")

    class Overtime(models.TextChoices):
        NONE = "none", _("None")
        PENDING = "pending", _("Waiting for approval")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")

    class Flag(models.TextChoices):
        OUTSIDE_GEOFENCE = "outside_geofence", _("Outside the branch")
        LOW_ACCURACY = "low_accuracy", _("Imprecise location")
        NO_LOCATION = "no_location", _("No location")
        UNSCHEDULED = "unscheduled", _("No shift planned")
        AUTO_CLOSED = "auto_closed", _("Check-out forgotten")
        EDITED = "edited", _("Edited by a manager")
        OTHER_BRANCH = "other_branch", _("At another branch")
        MISSED_ENTRY = "missed_entry", _("Came in without a scan")

    ATTENDED = (Status.OPEN, Status.CLOSED, Status.AUTO_CLOSED)

    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="attendance_records"
    )
    shift = models.ForeignKey(
        WorkShift, on_delete=models.SET_NULL, null=True, blank=True, related_name="records"
    )
    date = models.DateField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    check_in_at = models.DateTimeField(null=True, blank=True)
    check_out_at = models.DateTimeField(null=True, blank=True)
    in_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    in_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    in_accuracy_m = models.PositiveIntegerField(null=True, blank=True)
    out_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    out_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    out_accuracy_m = models.PositiveIntegerField(null=True, blank=True)
    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_records",
    )
    in_distance_m = models.PositiveIntegerField(null=True, blank=True)
    out_distance_m = models.PositiveIntegerField(null=True, blank=True)
    in_photo = models.FileField(
        storage=private_storage, upload_to=private_upload_to("attendance/selfies"), blank=True
    )
    in_source = models.CharField(max_length=6, choices=Source.choices, blank=True)
    out_source = models.CharField(max_length=6, choices=Source.choices, blank=True)
    late_minutes = models.PositiveIntegerField(default=0)
    early_leave_minutes = models.PositiveIntegerField(default=0)
    worked_minutes = models.PositiveIntegerField(default=0)
    overtime_minutes = models.PositiveIntegerField(default=0)
    is_late = models.BooleanField(default=False)
    overtime_status = models.CharField(
        max_length=8, choices=Overtime.choices, default=Overtime.NONE
    )
    flags = ArrayField(
        models.CharField(max_length=24, choices=Flag.choices), default=list, blank=True
    )
    note = models.CharField(max_length=300, blank=True)
    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["-date", "-check_in_at", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["membership"],
                condition=Q(status="open"),
                name="attendance_one_open_record",
            ),
            models.UniqueConstraint(
                fields=["membership", "shift"],
                condition=Q(shift__isnull=False),
                name="attendance_one_record_per_shift",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "date"]),
            models.Index(fields=["company", "membership", "date"]),
        ]

    def __str__(self):
        return f"{self.membership} · {self.date:%d.%m}"

    @property
    def attended(self) -> bool:
        return self.status in self.ATTENDED


class AttendanceCorrection(TenantModel):
    """ "I forgot to check in": a person asks to fix a day's times; a manager decides."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting for approval")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")

    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="attendance_corrections"
    )
    record = models.ForeignKey(
        AttendanceRecord,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="corrections",
    )
    date = models.DateField()
    check_in_at = models.DateTimeField(null=True, blank=True)
    check_out_at = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=300)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["company", "status"])]

    def __str__(self):
        return f"{self.membership} · {self.date:%d.%m}"


class JobMark(TenantModel):
    """ "Done once" markers of the periodic jobs (a nudge sent for a shift, a morning post for a
    branch and day), so a job that runs every few minutes acts only once."""

    key = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company", "key"], name="attendance_unique_job_mark"),
        ]

    def __str__(self):
        return self.key


# Face ID terminals -------------------------------------------------------------------------


def new_device_token() -> str:
    """The secret in a terminal's URL path: 24 URL-safe characters (144 random bits)."""
    return secrets.token_urlsafe(18)


class FaceDevice(TenantModel):
    """A face recognition terminal at a branch's staff door (Hikvision MinMoe and the like).

    The terminal recognises people itself, against its own list (Employee No, name, face, finger,
    card), and posts every event to `/api/v1/devices/hik/<token>/` (`apps.attendance.device_api`).
    Faces and templates stay on the terminal: only events and snapshots reach us. What the
    terminal says about itself (address, model, clock) is learned from its requests."""

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
    clock_offset_s = models.IntegerField(
        null=True,
        blank=True,
        help_text=_("How far the terminal's clock is from ours, in seconds (ahead is positive)."),
    )
    clock_checked_at = models.DateTimeField(null=True, blank=True)
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
    """One event a terminal posted, and what it did: a check-in or check-out, a repeat scan, a
    number nobody is linked to, an unknown face, or something logged only."""

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
        REPEAT = "repeat", _("Repeat scan")
        NOT_LINKED = "not_linked", _("Number not linked")
        STRANGER = "stranger", _("Unknown face")
        IGNORED = "ignored", _("Logged only")
        MODULE_OFF = "module_off", _("Attendance is off")

    class Flag(models.TextChoices):
        CLOCK_OFF = "clock_off", _("Terminal clock is wrong")
        DELIVERED_LATE = "delivered_late", _("Arrived late, no messages")
        AUTO_LINKED = "auto_linked", _("Linked by name")
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
        SIMULATED = "simulated", _("Simulated")

    device = models.ForeignKey(FaceDevice, on_delete=models.CASCADE, related_name="events")
    received_at = models.DateTimeField()
    event_at = models.DateTimeField(
        help_text=_("The terminal's time, or when it arrived if the terminal's clock is wrong.")
    )
    device_time = models.DateTimeField(null=True, blank=True)
    serial_no = models.PositiveBigIntegerField(null=True, blank=True)
    employee_no = models.CharField(max_length=32, blank=True)
    name_on_device = models.CharField(max_length=100, blank=True)
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.OTHER)
    method = models.CharField(max_length=12, choices=Method.choices, blank=True)
    verify_mode = models.CharField(max_length=48, blank=True)
    minor = models.PositiveIntegerField(null=True, blank=True)
    attendance_status = models.CharField(max_length=16, blank=True)
    membership = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="face_events"
    )
    record = models.ForeignKey(
        AttendanceRecord,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="face_events",
    )
    action = models.CharField(max_length=12, choices=Action.choices, default=Action.IGNORED)
    photo = models.FileField(
        storage=private_storage, upload_to=private_upload_to("attendance/face"), blank=True
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
                name="attendance_face_event_once",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "-event_at"], name="att_face_company_at"),
            models.Index(fields=["device", "-event_at"], name="att_face_device_at"),
            models.Index(fields=["membership", "-event_at"], name="att_face_member_at"),
        ]

    def __str__(self):
        return f"{self.device} · {self.get_action_display()}"


class FaceLink(TenantModel):
    """Who a terminal's Employee No is in the company (a person may have several numbers), or a
    number set aside (`ignored`: a guard, a visitor's card) so it never asks again."""

    employee_no = models.CharField(max_length=32)
    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, null=True, blank=True, related_name="face_links"
    )
    ignored = models.BooleanField(default=False)
    auto = models.BooleanField(default=False, help_text=_("Linked by the name on the terminal."))
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
            models.UniqueConstraint(
                fields=["company", "employee_no"], name="attendance_face_number_once"
            ),
            models.CheckConstraint(
                condition=Q(membership__isnull=False) | Q(ignored=True),
                name="attendance_face_link_has_person",
            ),
        ]

    def __str__(self):
        return f"{self.employee_no} · {self.membership or '—'}"
