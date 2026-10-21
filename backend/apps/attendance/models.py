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
