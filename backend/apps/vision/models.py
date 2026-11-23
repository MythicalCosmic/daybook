"""Ko‘z (the `vision` module, docs/KOZ.md): the cameras a pharmacy already has, as a sensor.

A Ko‘z box (`Agent`) is the agent on a PC at one branch. It reads the camera streams, finds
people with a local detector and sends Daybook only numbers (`MinuteStat`, and live counts kept
in the cache, never here), alerts (`Alert`, with an annotated photo) and, when someone asks,
snapshots and short video clips (`Clip`). Live frames are never stored: they live 10 s in the
cache (`apps.vision.live`). Nobody is identified: the detector finds person shapes only.

Tokens and pairing codes are kept as hashes only (`apps.vision.pairing`). Every file is private
(`apps.core.storage.private_storage`) and opens through a signed link (`apps.vision.providers`).
"""

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Branch, Company, TenantModel
from apps.core.models import TimeStampedModel
from apps.core.storage import private_storage, private_upload_to
from apps.members.models import Membership


def _between(low: int, high: int) -> list:
    return [MinValueValidator(low), MaxValueValidator(high)]


class VisionSettings(TimeStampedModel):
    """One row per company, made on first read by `apps.vision.conf.get_settings`. The module
    itself is on when "vision" is in `Company.features`. Ranges and defaults: docs/KOZ.md §6.7."""

    # field -> (lowest, highest) of the numbers an owner may set.
    RANGES = {
        "queue_people": (1, 20),
        "queue_wait_s": (15, 1800),
        "unattended_s": (15, 1800),
        "clear_after_s": (5, 120),
        "cooldown_s": (0, 3600),
        "analysis_fps": (1, 5),
        "live_fps": (1, 4),
        "record_hours": (1, 168),
        "stats_keep_days": (30, 800),
        "photos_keep_days": (1, 365),
        "clips_keep_days": (1, 365),
    }

    company = models.OneToOneField(
        Company, on_delete=models.CASCADE, related_name="vision_settings"
    )
    # The alert rules the boxes apply (§5.8).
    queue_people = models.PositiveSmallIntegerField(default=3, validators=_between(1, 20))
    queue_wait_s = models.PositiveIntegerField(default=120, validators=_between(15, 1800))
    unattended_s = models.PositiveIntegerField(default=90, validators=_between(15, 1800))
    clear_after_s = models.PositiveSmallIntegerField(default=15, validators=_between(5, 120))
    # An alert of a kind on a camera is announced again only this long after the last one.
    cooldown_s = models.PositiveIntegerField(default=120, validators=_between(0, 3600))
    # How the boxes work.
    analysis_fps = models.PositiveSmallIntegerField(default=2, validators=_between(1, 5))
    live_fps = models.PositiveSmallIntegerField(default=2, validators=_between(1, 4))
    privacy_blur = models.BooleanField(default=False)
    alert_photo = models.BooleanField(default=True)
    record_counter = models.BooleanField(default=True)
    record_hours = models.PositiveSmallIntegerField(default=24, validators=_between(1, 168))
    # Who hears about alerts (§7).
    notify_on_shift = models.BooleanField(default=True)
    notify_managers = models.BooleanField(default=True)
    # How long things are kept (§8).
    stats_keep_days = models.PositiveSmallIntegerField(default=400, validators=_between(30, 800))
    photos_keep_days = models.PositiveSmallIntegerField(default=30, validators=_between(1, 365))
    clips_keep_days = models.PositiveSmallIntegerField(default=30, validators=_between(1, 365))

    class Meta:
        verbose_name = _("Ko‘z settings")
        verbose_name_plural = _("Ko‘z settings")

    def __str__(self):
        return f"Ko‘z settings of {self.company}"


class Agent(TenantModel):
    """A Ko‘z box: the agent on a PC at one branch, even when it is software on a PC the
    pharmacy already has. It has at most one token at a time (only its SHA-256 is kept) and at
    most one pairing code (hashed, 15 minutes, single use). A removed box keeps its row, so its
    cameras keep their history."""

    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="vision_agents")
    name = models.CharField(max_length=80)
    token_hash = models.CharField(max_length=64, blank=True, editable=False)
    paired_at = models.DateTimeField(null=True, blank=True)
    pairing_hash = models.CharField(max_length=64, blank=True, editable=False)
    pairing_expires_at = models.DateTimeField(null=True, blank=True)
    # What the box says about the PC when it pairs and reports.
    hostname = models.CharField(max_length=100, blank=True)
    os = models.CharField(max_length=100, blank=True)
    version = models.CharField(max_length=32, blank=True)
    # Written at most once a minute (the live reports themselves stay in the cache).
    last_seen_at = models.DateTimeField(null=True, blank=True)
    removed_at = models.DateTimeField(null=True, blank=True)
    # Made by the demo builder: its live numbers come from the clock (apps.vision.demo_live).
    demo = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["branch__order", "branch__name", "name", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["token_hash"], condition=~Q(token_hash=""), name="vision_unique_token"
            ),
            models.UniqueConstraint(
                fields=["pairing_hash"],
                condition=~Q(pairing_hash=""),
                name="vision_unique_pairing_code",
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def paired(self) -> bool:
        return bool(self.token_hash)


class Camera(TenantModel):
    """A camera a box sees, by the box's own stable name for it (`key`, docs/KOZ.md §3). Made
    by the box's inventory (role `other`, off); the owner names it, gives it a role, draws its
    zones and maps a counter camera to its till. Never deleted: a camera the box no longer lists
    is offline, with its history."""

    class Role(models.TextChoices):
        COUNTER = "counter", _("Counter")
        ENTRANCE = "entrance", _("Entrance")
        FLOOR = "floor", _("Sales floor")
        STOREROOM = "storeroom", _("Storeroom")
        OTHER = "other", _("Other")

    class Source(models.TextChoices):
        NVR = "nvr", _("Recorder channel")
        RTSP = "rtsp", _("RTSP stream")
        WEBCAM = "webcam", _("Webcam")
        FILE = "file", _("Video file")
        SIM = "sim", _("Generated scene")

    agent = models.ForeignKey(Agent, on_delete=models.PROTECT, related_name="cameras")
    # The box's branch, kept on the camera for branch scope.
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="vision_cameras")
    key = models.CharField(max_length=64)
    name = models.CharField(max_length=80)
    # The owner renamed it: the box's inventory no longer changes the name.
    renamed = models.BooleanField(default=False)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.OTHER)
    enabled = models.BooleanField(default=False)
    source = models.CharField(max_length=8, choices=Source.choices, blank=True)
    channel = models.PositiveIntegerField(null=True, blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    online = models.BooleanField(default=False)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    # Up to 8 zones, coordinates normalized to the frame (apps.vision.zones, docs/KOZ.md §4).
    zones = models.JSONField(default=list, blank=True)
    register = models.ForeignKey(
        "sales.Register", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # The latest full frame the box sent, for setting the camera up.
    snapshot = models.FileField(
        storage=private_storage, upload_to=private_upload_to("vision/snapshots"), blank=True
    )
    snapshot_at = models.DateTimeField(null=True, blank=True)
    snapshot_requested_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["branch__order", "branch__name", "name", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["agent", "key"], name="vision_unique_camera_key"),
        ]

    def __str__(self):
        return self.name


class MinuteStat(TenantModel):
    """One camera's numbers for one minute (docs/KOZ.md §5.7), upserted by (camera, minute), so
    a box sending a minute again changes nothing. `staff_seconds`: seconds of the minute with
    at least one person in a staff zone."""

    # Without a company index of its own: (company, minute) below serves the company's queries.
    company = models.ForeignKey(
        Company, on_delete=models.PROTECT, related_name="vision_minutes", db_index=False
    )
    # Without an index of its own either: the unique (camera, minute) one serves it.
    camera = models.ForeignKey(
        Camera, on_delete=models.CASCADE, related_name="minutes", db_index=False
    )
    minute = models.DateTimeField()
    frames = models.PositiveIntegerField(default=0)
    people_avg = models.FloatField(default=0)
    people_max = models.PositiveSmallIntegerField(default=0)
    entered = models.PositiveIntegerField(default=0)
    exited = models.PositiveIntegerField(default=0)
    queue_avg = models.FloatField(default=0)
    queue_max = models.PositiveSmallIntegerField(default=0)
    wait_max_s = models.PositiveIntegerField(default=0)
    staff_seconds = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(60)])

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["camera", "minute"], name="vision_one_stat_a_minute"),
        ]
        indexes = [models.Index(fields=["company", "minute"], name="vision_stat_company_minute")]

    def __str__(self):
        return f"{self.camera_id} {self.minute:%Y-%m-%d %H:%M}"


class Alert(TenantModel):
    """A queue at the counter, nobody at the counter while customers wait (both from a box's
    events, §5.8), or a box that stopped reporting (`agent_offline`). Announced in Telegram to
    the people on shift and the managers (`apps.vision.notify`), at most every `cooldown_s` per
    kind and camera; the first who presses "Men boraman" acknowledges it for everyone."""

    class Kind(models.TextChoices):
        QUEUE = "queue", _("Queue")
        UNATTENDED = "unattended", _("Nobody at the counter")
        AGENT_OFFLINE = "agent_offline", _("Ko‘z box offline")

    class State(models.TextChoices):
        OPEN = "open", _("Open")
        RESOLVED = "resolved", _("Resolved")

    class Ending(models.TextChoices):
        ENDED = "ended", _("Ended")
        STALE = "stale", _("No news for two hours")
        BACK = "back", _("Back online")
        REMOVED = "removed", _("Box removed")

    CAMERA_KINDS = (Kind.QUEUE, Kind.UNATTENDED)

    kind = models.CharField(max_length=14, choices=Kind.choices)
    state = models.CharField(max_length=8, choices=State.choices, default=State.OPEN)
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="vision_alerts")
    agent = models.ForeignKey(Agent, on_delete=models.PROTECT, related_name="alerts")
    camera = models.ForeignKey(
        Camera, on_delete=models.PROTECT, null=True, blank=True, related_name="alerts"
    )
    # The box's id for the incident: its start, updates and end carry it.
    incident_id = models.UUIDField(null=True, blank=True)
    started_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    # When the box last said anything about it (open alerts with no news for 2 hours close).
    last_event_at = models.DateTimeField()
    queue = models.PositiveSmallIntegerField(default=0)
    wait_s = models.PositiveIntegerField(default=0)
    staff = models.PositiveSmallIntegerField(default=0)
    peak_queue = models.PositiveSmallIntegerField(default=0)
    peak_wait_s = models.PositiveIntegerField(default=0)
    ending = models.CharField(max_length=8, choices=Ending.choices, blank=True)
    photo = models.FileField(
        storage=private_storage, upload_to=private_upload_to("vision/photos"), blank=True
    )
    # Set when it was announced in Telegram (not during another one's cooldown).
    announced_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["agent", "incident_id"],
                condition=Q(incident_id__isnull=False),
                name="vision_one_alert_per_incident",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "state", "kind"], name="vision_alert_state"),
            models.Index(fields=["company", "started_at"], name="vision_alert_started"),
            models.Index(fields=["camera", "kind", "announced_at"], name="vision_alert_announced"),
        ]

    def __str__(self):
        return f"{self.kind} #{self.pk}"

    @property
    def duration_s(self) -> int | None:
        if self.resolved_at is None:
            return None
        return max(int((self.resolved_at - self.started_at).total_seconds()), 0)


class AlertEvent(models.Model):
    """One call a box made to events/ (§5.8), kept so the same `event_id` again changes nothing
    and answers what it answered the first time."""

    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="+")
    alert = models.ForeignKey(
        Alert, on_delete=models.CASCADE, null=True, blank=True, related_name="events"
    )
    event_id = models.UUIDField()
    phase = models.CharField(max_length=6)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["agent", "event_id"], name="vision_one_row_per_event"),
        ]

    def __str__(self):
        return f"{self.phase} {self.event_id}"


class AlertMessage(models.Model):
    """A copy of an alert in someone's Telegram chat (§7): when it is acknowledged or ends,
    every copy is edited. One per person and alert: nobody hears twice. `message_id` is None
    when nothing was delivered (a dry run, a blocked bot)."""

    alert = models.ForeignKey(Alert, on_delete=models.CASCADE, related_name="messages")
    member = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name="+")
    # "on_shift" (checked in at the branch) or "manager" (sees the branch's Ko‘z).
    reason = models.CharField(max_length=8)
    bot = models.CharField(max_length=8, blank=True)
    chat_id = models.BigIntegerField(null=True, blank=True)
    message_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["alert", "member"], name="vision_one_copy_a_person"),
        ]

    def __str__(self):
        return f"{self.alert_id} to {self.member_id}"


class Clip(TenantModel):
    """A video receipt (§5.9, §6.6): a short clip of one camera the box cuts from its own
    recorder or the NVR, asked for a sale, an alert or a moment. Offered to the box by jobs/;
    without video 5 minutes after an offer it is offered again, at most three offers in all."""

    class State(models.TextChoices):
        PENDING = "pending", _("Waiting for the box")
        FETCHING = "fetching", _("The box is cutting it")
        READY = "ready", _("Ready")
        FAILED = "failed", _("Failed")

    class Reason(models.TextChoices):
        SALE = "sale", _("A sale")
        ALERT = "alert", _("An alert")
        MANUAL = "manual", _("A moment someone picked")

    class Failure(models.TextChoices):
        NOT_RECORDED = "not_recorded", _("This moment wasn't recorded.")
        CAMERA_OFFLINE = "camera_offline", _("The camera was offline then.")
        NVR_ERROR = "nvr_error", _("The recorder didn't give the video.")
        TOO_OLD = "too_old", _("The recording of that moment is already gone.")
        AGENT_TIMEOUT = "agent_timeout", _("The Ko‘z box didn't send the video.")

    class Source(models.TextChoices):
        RECORDER = "recorder", _("The box's own recorder")
        NVR = "nvr", _("The recorder (NVR)")

    MAX_OFFERS = 3

    camera = models.ForeignKey(Camera, on_delete=models.PROTECT, related_name="clips")
    state = models.CharField(max_length=8, choices=State.choices, default=State.PENDING)
    reason = models.CharField(max_length=6, choices=Reason.choices)
    start = models.DateTimeField()
    end = models.DateTimeField()
    sale = models.ForeignKey(
        "sales.Sale", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    alert = models.ForeignKey(
        Alert, on_delete=models.SET_NULL, null=True, blank=True, related_name="clips"
    )
    requested_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    offers = models.PositiveSmallIntegerField(default=0)
    offered_at = models.DateTimeField(null=True, blank=True)
    video = models.FileField(
        storage=private_storage, upload_to=private_upload_to("vision/clips"), blank=True
    )
    poster = models.FileField(
        storage=private_storage, upload_to=private_upload_to("vision/posters"), blank=True
    )
    duration_s = models.FloatField(null=True, blank=True)
    source = models.CharField(max_length=8, choices=Source.choices, blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    failure = models.CharField(max_length=16, choices=Failure.choices, blank=True)
    failure_detail = models.CharField(max_length=300, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(fields=["camera", "state"], name="vision_clip_state"),
            models.Index(fields=["camera", "start"], name="vision_clip_start"),
        ]

    def __str__(self):
        return f"Clip #{self.pk}"
