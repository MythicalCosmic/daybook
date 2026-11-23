"""Every write of Ko‘z (docs/KOZ.md): boxes and their pairing, cameras, what the boxes send
(live reports, frames, minute stats, alert events, snapshots and clips), the alerts' lifecycle,
clip requests and the scheduled jobs.

Owner changes take `by` (a Membership) and are audited (§8). What a box sends is checked by the
device API's serializers first; here it is stored. Telegram goes out after commit, through
`apps.vision.tasks` (which never imports this module): announcing an alert, and editing every
copy when it is acknowledged or ends.
"""

from __future__ import annotations

import io
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.db.models import Exists, F, OuterRef
from django.utils import timezone
from django.utils.translation import gettext as _
from PIL import Image, UnidentifiedImageError

from apps.audit import services as audit
from apps.core import uploads
from apps.vision import conf, live, pairing, queries, tasks, zones
from apps.vision.audit_actions import VisionAction
from apps.vision.errors import BadCode, NoCamera, NotFound, TooLarge, UnknownCamera, VisionError
from apps.vision.models import (
    Agent,
    Alert,
    AlertEvent,
    AlertMessage,
    Camera,
    Clip,
    MinuteStat,
    VisionSettings,
)

logger = logging.getLogger(__name__)

PAIRING_FOR = timedelta(minutes=15)
JPEG_MAX = 1536 * 1024  # 1.5 MB
FRAME_MAX = 400 * 1024
FRAME_MAX_WIDTH = 960
CLIP_MAX = 40 * 1024 * 1024
CLIP_MAX_SECONDS = 60
STATS_KEEP = timedelta(days=7)
OFFER_TIMEOUT = timedelta(minutes=5)
STALE_AFTER = timedelta(hours=2)
OFFLINE_AFTER = timedelta(minutes=5)
# How far a box's clock may be off before its times are taken as now.
CLOCK_SLACK = timedelta(minutes=2)
SALE_BEFORE, SALE_AFTER = timedelta(seconds=10), timedelta(seconds=5)
ALERT_BEFORE = timedelta(seconds=10)
CLIP_LONGEST = timedelta(seconds=CLIP_MAX_SECONDS)


def _audit(action: str, target, by, **details) -> None:
    audit.record(
        action,
        company_id=target.company_id,
        actor=by.user if by is not None else None,
        target=target,
        **details,
    )


def _after_commit(function, *args) -> None:
    transaction.on_commit(lambda: function(*args))


# Settings ----------------------------------------------------------------------------------


def update_settings(company, *, by, changes: dict) -> VisionSettings:
    """Change any of §6.7's settings (the serializer checked the ranges)."""
    with transaction.atomic():
        settings = VisionSettings.objects.select_for_update().get(pk=conf.get_settings(company).pk)
        diff = {}
        for field, value in changes.items():
            before = getattr(settings, field)
            if before != value:
                diff[field] = [before, value]
                setattr(settings, field, value)
        if diff:
            settings.save()
            _audit(VisionAction.SETTINGS_CHANGED, settings, by, changes=diff)
    return settings


# Boxes and pairing -------------------------------------------------------------------------


@dataclass(frozen=True)
class Pairing:
    code: str
    expires_at: datetime


def create_agent(company, *, by, name: str, branch) -> tuple[Agent, Pairing]:
    """A new box at `branch`, with its first pairing code (shown once)."""
    name = (name or "").strip()
    if not name:
        raise VisionError(_("Give the box a name."), code="name")
    with transaction.atomic():
        agent = Agent.objects.create(company=company, branch=branch, name=name[:80], created_by=by)
        conf.get_settings(company)
        _audit(VisionAction.BOX_ADDED, agent, by, branch=branch.name)
        code = _new_code(agent, by=by, audited=False)
    return agent, code


def new_pairing(agent: Agent, *, by) -> Pairing:
    """A fresh code for the box, replacing any earlier one. The box's current token keeps
    working until the new code is used."""
    if agent.removed_at is not None:
        raise NotFound(_("This box was removed."))
    with transaction.atomic():
        return _new_code(agent, by=by, audited=True)


def _new_code(agent: Agent, *, by, audited: bool) -> Pairing:
    now = timezone.now()
    for _attempt in range(5):
        code = pairing.new_code()
        try:
            with transaction.atomic():
                Agent.objects.filter(pk=agent.pk).update(
                    pairing_hash=pairing.code_hash(code),
                    pairing_expires_at=now + PAIRING_FOR,
                    updated_at=now,
                )
        except IntegrityError:  # another box's live code happens to be the same
            continue
        agent.refresh_from_db(fields=["pairing_hash", "pairing_expires_at", "updated_at"])
        if audited:
            _audit(VisionAction.PAIRING_CODE, agent, by)
        return Pairing(code=code, expires_at=agent.pairing_expires_at)
    raise VisionError(_("Couldn't make a code. Try again."), code="retry", status=409)


def pair(code: str, *, host: dict, now: datetime | None = None) -> tuple[Agent, str]:
    """POST pair/ (§5.1): the box's code becomes its token (returned once). Pairing again
    replaces the token: the old one stops working."""
    now = now or timezone.now()
    digest = pairing.code_hash(code)
    if digest is None:
        raise BadCode(_("This code is wrong or no longer valid. Make a new one in Daybook."))
    with transaction.atomic():
        agent = (
            Agent.objects.select_for_update(of=("self",))
            .select_related("company", "branch")
            .filter(
                pairing_hash=digest,
                pairing_expires_at__gt=now,
                removed_at__isnull=True,
                company__is_active=True,
            )
            .first()
        )
        if agent is None:
            raise BadCode(_("This code is wrong or no longer valid. Make a new one in Daybook."))
        token = pairing.new_token()
        agent.token_hash = pairing.token_hash(token)
        agent.paired_at = now
        agent.pairing_hash = ""
        agent.pairing_expires_at = None
        agent.hostname = str(host.get("hostname") or "")[:100]
        agent.os = str(host.get("os") or "")[:100]
        agent.version = str(host.get("version") or "")[:32]
        agent.save()
        _audit(
            VisionAction.BOX_PAIRED,
            agent,
            None,
            hostname=agent.hostname,
            os=agent.os,
            version=agent.version,
        )
    live.forget_seen(agent.pk)
    return agent, token


def authenticate(token: str) -> Agent | None:
    """The box a bearer token belongs to (paired, not removed, its company active)."""
    digest = pairing.token_hash(token)
    if digest is None:
        return None
    return (
        Agent.objects.select_related("company", "branch")
        .filter(token_hash=digest, removed_at__isnull=True, company__is_active=True)
        .first()
    )


def remove_agent(agent: Agent, *, by) -> None:
    """DELETE agents/<id>/ (§6.8): the token stops working; the cameras stay, offline, with
    their history. Its open alerts close."""
    now = timezone.now()
    with transaction.atomic():
        agent = Agent.objects.select_for_update().get(pk=agent.pk)
        if agent.removed_at is not None:
            return
        agent.token_hash = ""
        agent.pairing_hash = ""
        agent.pairing_expires_at = None
        agent.removed_at = now
        agent.save()
        agent.cameras.update(online=False, updated_at=now)
        for alert in Alert.objects.filter(agent=agent, state=Alert.State.OPEN):
            _resolve(alert, at=now, ending=Alert.Ending.REMOVED)
        _audit(VisionAction.BOX_REMOVED, agent, by, branch=agent.branch.name)


def mark_seen(agent: Agent, *, version: str = "", cameras: dict | None = None, now=None) -> bool:
    """At most once a minute (§5.5): write when the box was last seen, the cameras' online
    flags, and close the box's "offline" alert when it is back. True when it wrote."""
    if not live.seen_due(agent.pk):
        return False
    now = now or timezone.now()
    changes = {"last_seen_at": now, "updated_at": now}
    if version and version != agent.version:
        changes["version"] = version[:32]
    Agent.objects.filter(pk=agent.pk).update(**changes)
    for field, value in changes.items():
        setattr(agent, field, value)
    for camera_id, is_online in (cameras or {}).items():
        values = {"online": is_online, "updated_at": now}
        if is_online:
            values["last_seen_at"] = now
        Camera.objects.filter(pk=camera_id, agent=agent).update(**values)
    with transaction.atomic():
        for alert in Alert.objects.select_for_update().filter(
            agent=agent, kind=Alert.Kind.AGENT_OFFLINE, state=Alert.State.OPEN
        ):
            _resolve(alert, at=now, ending=Alert.Ending.BACK)
    return True


# Cameras ---------------------------------------------------------------------------------


def inventory(agent: Agent, rows: list[dict], now: datetime | None = None) -> list[dict]:
    """POST cameras/ (§5.3): upsert by key. New cameras start as `other`, off, with the box's
    name for them; later calls update the source, size and `online`, and the name only while
    the owner hasn't renamed it. Cameras missing from the list go offline, never away."""
    now = now or timezone.now()
    with transaction.atomic():
        existing = {camera.key: camera for camera in agent.cameras.select_for_update()}
        listed = []
        for row in rows:
            key = row["key"]
            camera = existing.get(key)
            if camera is None:
                camera = Camera(
                    company_id=agent.company_id,
                    agent=agent,
                    branch_id=agent.branch_id,
                    key=key,
                    name=(row.get("name") or key)[:80],
                )
                existing[key] = camera
            elif row.get("name") and not camera.renamed:
                camera.name = row["name"][:80]
            camera.source = row.get("source") or ""
            camera.channel = row.get("channel")
            camera.width = row.get("w")
            camera.height = row.get("h")
            camera.online = bool(row.get("online", True))
            if camera.online:
                camera.last_seen_at = now
            camera.save()
            listed.append(camera)
        agent.cameras.exclude(key__in=[camera.key for camera in listed]).update(
            online=False, updated_at=now
        )
    return [{"key": camera.key, "id": camera.pk} for camera in listed]


def update_camera(camera: Camera, *, by, changes: dict) -> Camera:
    """PATCH cameras/<id>/ (§6.4): name, role, enabled, zones (checked as §4 says) and the till
    a counter camera films."""
    with transaction.atomic():
        camera = (
            Camera.objects.select_for_update(of=("self",))
            .select_related("register")
            .get(pk=camera.pk)
        )
        diff = {}
        if "name" in changes:
            name = (changes["name"] or "").strip()[:80]
            if not name:
                raise VisionError(_("Give the camera a name."), code="name")
            if name != camera.name:
                diff["name"] = [camera.name, name]
                camera.name = name
                camera.renamed = True
        if "role" in changes and changes["role"] != camera.role:
            diff["role"] = [camera.role, changes["role"]]
            camera.role = changes["role"]
        if "enabled" in changes and changes["enabled"] != camera.enabled:
            diff["enabled"] = [camera.enabled, changes["enabled"]]
            camera.enabled = changes["enabled"]
        if "register_id" in changes:
            register = _register(camera, changes["register_id"])
            if (register.pk if register else None) != camera.register_id:
                diff["register"] = [
                    camera.register.name if camera.register else None,
                    register.name if register else None,
                ]
                camera.register = register
        zones_changed = False
        if "zones" in changes:
            cleaned = zones.clean(changes["zones"])
            if cleaned != (camera.zones or []):
                zones_changed = True
                before = camera.zones or []
                camera.zones = cleaned
        if not diff and not zones_changed:
            return camera
        camera.save()
        if diff:
            _audit(VisionAction.CAMERA_CHANGED, camera, by, changes=diff)
        if zones_changed:
            _audit(
                VisionAction.ZONES_CHANGED,
                camera,
                by,
                before=[zone["id"] for zone in before],
                after=[zone["id"] for zone in camera.zones],
                zones=camera.zones,
            )
    return camera


def _register(camera: Camera, register_id):
    if register_id is None:
        return None
    from apps.sales.models import Register

    register = Register.objects.filter(
        company_id=camera.company_id, branch_id=camera.branch_id, pk=register_id
    ).first()
    if register is None:
        raise VisionError(_("Pick a till of this camera's branch."), code="register")
    return register


def request_snapshot(camera: Camera, *, by) -> None:
    """POST cameras/<id>/snapshot/ (§6.4): the box sends a fresh one soon (it reads
    `snapshot_requested` in its config and `snapshots` in its jobs)."""
    now = timezone.now()
    Camera.objects.filter(pk=camera.pk).update(snapshot_requested_at=now, updated_at=now)
    camera.snapshot_requested_at = now


def store_snapshot(agent: Agent, key: str, image) -> Camera:
    """POST cameras/<key>/snapshot/ (§5.4): the latest full frame, masked by the box."""
    camera = agent.cameras.filter(key=key).first()
    if camera is None:
        raise UnknownCamera(_("This box has no camera %(key)s.") % {"key": key})
    picture = _picture(image, max_bytes=JPEG_MAX)
    now = timezone.now()
    old = camera.snapshot.name if camera.snapshot else ""
    with transaction.atomic():
        camera.snapshot.save(picture.name, picture, save=False)
        camera.snapshot_at = now
        camera.save(update_fields=["snapshot", "snapshot_at", "updated_at"])
    if old:
        storage = camera.snapshot.storage
        transaction.on_commit(lambda: storage.delete(old))
    return camera


def _picture(image, *, max_bytes: int):
    """An uploaded JPEG, decoded and saved again without its metadata (apps.core.uploads)."""
    if image is None:
        raise VisionError(_("Send the picture as a JPEG."), code="no_image")
    if getattr(image, "size", 0) > max_bytes:
        raise TooLarge(_("The picture is too big (%(kb)d KB at most).") % {"kb": max_bytes // 1024})
    try:
        return uploads.sanitize_image(image, max_bytes=max_bytes)
    except uploads.InvalidUpload as exc:
        raise VisionError(str(exc), code="bad_image") from exc


# Live reports and frames (§5.5, §5.6) ------------------------------------------------------


def receive_live(agent: Agent, report: dict, now: datetime | None = None) -> dict:
    """POST live/ every 5 s: the numbers go to the cache for 30 s; `last_seen_at` is written at
    most once a minute. Answers what the box should do next."""
    now = now or timezone.now()
    cameras = {camera.key: camera for camera in agent.cameras.all()}
    reports = {}
    for row in report.get("cameras") or []:
        camera = cameras.get(row["key"])
        if camera is None:
            continue
        reports[camera.pk] = {
            "online": bool(row.get("online")),
            "fps": row.get("fps"),
            "people": row.get("people"),
            "queue": row.get("queue"),
            "staff": row.get("staff"),
            "wait_s": row.get("wait_s"),
            "error": row.get("error"),
            "at": queries.iso(now),
        }
    box = report.get("agent") or {}
    live.put_reports(
        agent.pk,
        {"version": box.get("version"), "fps": box.get("fps"), "cpu": box.get("cpu")},
        reports,
    )
    mark_seen(
        agent,
        version=box.get("version") or "",
        cameras={camera_id: values["online"] for camera_id, values in reports.items()},
        now=now,
    )
    watched = live.watched(camera.pk for camera in cameras.values())
    body = queries.config(agent, now)
    return {
        "config_version": body["config_version"],
        "watch": sorted(camera.key for camera in cameras.values() if camera.pk in watched),
        "jobs": queries.pending_jobs(agent, now, snapshots=body["snapshot_requested"]),
        "server_time": queries.iso(now),
    }


def receive_frame(agent: Agent, key: str, image, meta: dict) -> bool:
    """POST frames/<key>/ while someone watches (§5.6): the latest frame stays 10 s in the
    cache, never longer and never on disk. Frames of a camera nobody watches are dropped."""
    camera = agent.cameras.filter(key=key).first()
    if camera is None:
        raise UnknownCamera(_("This box has no camera %(key)s.") % {"key": key})
    if image is None:
        raise VisionError(_("Send the picture as a JPEG."), code="no_image")
    if image.size > FRAME_MAX:
        raise TooLarge(_("A live frame is at most %(kb)d KB.") % {"kb": FRAME_MAX // 1024})
    data = image.read(FRAME_MAX + 1)
    _check_frame(data)
    if camera.pk not in live.watched([camera.pk]):
        return False
    live.put_frame(
        camera.pk,
        {
            "at": meta.get("at"),
            "w": meta.get("w"),
            "h": meta.get("h"),
            "people": meta.get("people") or [],
            "jpeg": data,
        },
    )
    return True


def _check_frame(data: bytes) -> None:
    """A JPEG at most 960 px wide, judged from its header (the dashboard shows it as is)."""
    if not data.startswith(b"\xff\xd8\xff"):
        raise VisionError(_("Send the picture as a JPEG."), code="bad_image")
    try:
        with Image.open(io.BytesIO(data), formats=("JPEG",)) as picture:
            width = picture.width
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise VisionError(_("Send the picture as a JPEG."), code="bad_image") from exc
    if width > FRAME_MAX_WIDTH:
        raise VisionError(
            _("A live frame is at most %(px)d pixels wide.") % {"px": FRAME_MAX_WIDTH},
            code="bad_image",
        )


# Minute stats (§5.7) -----------------------------------------------------------------------

STAT_FIELDS = (
    "frames",
    "people_avg",
    "people_max",
    "entered",
    "exited",
    "queue_avg",
    "queue_max",
    "wait_max_s",
    "staff_seconds",
)


def store_stats(agent: Agent, rows: list[dict], now: datetime | None = None) -> dict:
    """Upsert by (camera, minute), so sending a minute again changes nothing. Unknown keys and
    minutes older than 7 days (or ahead of the server's clock) come back in `skipped`."""
    now = now or timezone.now()
    cameras = {camera.key: camera for camera in agent.cameras.all()}
    found: dict[tuple[int, datetime], MinuteStat] = {}
    skipped = []
    for row in rows:
        camera = cameras.get(row["key"])
        minute = row["minute"].replace(second=0, microsecond=0)
        reason = None
        if camera is None:
            reason = "unknown_camera"
        elif minute < now - STATS_KEEP:
            reason = "too_old"
        elif minute > now + CLOCK_SLACK:
            reason = "in_future"
        if reason:
            skipped.append({"key": row["key"], "minute": queries.iso(minute), "reason": reason})
            continue
        found[(camera.pk, minute)] = MinuteStat(
            company_id=agent.company_id,
            camera=camera,
            minute=minute,
            **{field: row.get(field, 0) for field in STAT_FIELDS},
        )
    if found:
        MinuteStat.objects.bulk_create(
            list(found.values()),
            update_conflicts=True,
            unique_fields=["camera", "minute"],
            update_fields=[*STAT_FIELDS, "updated_at"],
        )
    return {"stored": len(found), "skipped": skipped}


# Alerts (§5.8, §7) -------------------------------------------------------------------------


def receive_event(agent: Agent, event: dict, image=None, now: datetime | None = None) -> dict:
    """POST events/: an incident's start, updates and end. Idempotent by `event_id`; an update
    or end of an incident nobody started answers `{"alert_id": None}` and does nothing."""
    now = now or timezone.now()
    with transaction.atomic():
        try:
            with transaction.atomic():
                record = AlertEvent.objects.create(
                    agent=agent, event_id=event["event_id"], phase=event["phase"]
                )
        except IntegrityError:
            seen = (
                AlertEvent.objects.select_related("alert")
                .filter(agent=agent, event_id=event["event_id"])
                .first()
            )
            return _event_answer(seen.alert if seen else None)
        alert = _apply_event(agent, event, image, now)
        if alert is not None:
            record.alert = alert
            record.save(update_fields=["alert"])
    return _event_answer(alert)


def _event_answer(alert: Alert | None) -> dict:
    if alert is None:
        return {"alert_id": None}
    return {"alert_id": alert.pk, "state": alert.state}


def _moment(value: datetime | None, now: datetime) -> datetime:
    """A time from a box, within a day before now and no later than now."""
    if value is None or value > now + CLOCK_SLACK:
        return now
    return max(min(value, now), now - timedelta(days=1))


def _apply_event(agent: Agent, event: dict, image, now: datetime) -> Alert | None:
    camera = agent.cameras.filter(key=event["key"]).first()
    if camera is None:
        raise UnknownCamera(_("This box has no camera %(key)s.") % {"key": event["key"]})
    alert = (
        Alert.objects.select_for_update()
        .filter(agent=agent, incident_id=event["incident_id"])
        .first()
    )
    phase = event["phase"]
    if alert is None:
        if phase != "start" or not _raises(camera, event["kind"]):
            return None
        return _start(agent, camera, event, image, now)
    if alert.state != Alert.State.OPEN:
        return alert
    _take_numbers(alert, event)
    alert.last_event_at = now
    if phase == "end":
        _resolve(alert, at=_moment(event.get("at"), now), ending=Alert.Ending.ENDED)
    else:
        alert.save()
    return alert


def _raises(camera: Camera, kind: str) -> bool:
    """Only enabled counter cameras with the zones a rule needs raise alerts (§5.8)."""
    if not camera.enabled or camera.role != Camera.Role.COUNTER:
        return False
    if not zones.has(camera.zones, "queue"):
        return False
    return kind != Alert.Kind.UNATTENDED or zones.has(camera.zones, "staff")


def _take_numbers(alert: Alert, event: dict) -> None:
    for field in ("queue", "wait_s", "staff"):
        if event.get(field) is not None:
            setattr(alert, field, event[field])
    alert.peak_queue = max(alert.peak_queue, event.get("peak_queue") or 0, alert.queue)
    alert.peak_wait_s = max(alert.peak_wait_s, event.get("peak_wait_s") or 0, alert.wait_s)


def _start(agent: Agent, camera: Camera, event: dict, image, now: datetime) -> Alert:
    settings = conf.get_settings(agent.company)
    alert = Alert(
        company_id=agent.company_id,
        kind=event["kind"],
        branch_id=camera.branch_id,
        agent=agent,
        camera=camera,
        incident_id=event["incident_id"],
        started_at=_moment(event.get("started_at") or event.get("at"), now),
        last_event_at=now,
    )
    _take_numbers(alert, event)
    if image is not None and settings.alert_photo:
        try:
            picture = _picture(image, max_bytes=JPEG_MAX)
        except VisionError:
            logger.info("Ko‘z box %s sent an alert photo we can't read", agent.pk)
        else:
            alert.photo.save(picture.name, picture, save=False)
    if not _cooling_down(camera, alert.kind, settings, now):
        alert.announced_at = now
    try:
        with transaction.atomic():
            alert.save()
    except IntegrityError:
        # The same incident's start, sent twice at once under two event ids: the first wins.
        _delete_file(alert.photo)
        return Alert.objects.select_for_update().get(agent=agent, incident_id=event["incident_id"])
    if alert.announced_at is not None:
        _after_commit(tasks.announce_alert.delay, alert.pk)
    return alert


def _cooling_down(camera: Camera, kind: str, settings: VisionSettings, now: datetime) -> bool:
    """An alert still opens every time, but its kind on that camera is announced again only
    `cooldown_s` after the last announcement (§7)."""
    if not settings.cooldown_s:
        return False
    return Alert.objects.filter(
        camera=camera,
        kind=kind,
        announced_at__gt=now - timedelta(seconds=settings.cooldown_s),
    ).exists()


def _resolve(alert: Alert, *, at: datetime, ending: str) -> None:
    alert.state = Alert.State.RESOLVED
    alert.resolved_at = max(at, alert.started_at)
    alert.ending = ending
    alert.save()
    if alert.announced_at is not None:
        _after_commit(tasks.refresh_alert.delay, alert.pk)


def acknowledge(alert: Alert, member, now: datetime | None = None) -> Alert:
    """ "Men boraman": the first person who presses it goes; every copy says so (§7)."""
    now = now or timezone.now()
    with transaction.atomic():
        alert = Alert.objects.select_for_update().get(pk=alert.pk)
        if alert.kind not in Alert.CAMERA_KINDS:
            raise VisionError(_("There's nothing to go to here."), code="not_counter")
        if alert.state != Alert.State.OPEN:
            raise VisionError(_("It's over already: nobody needs to go."), code="over")
        if alert.acknowledged_by_id is not None:
            going = alert.acknowledged_by
            raise VisionError(
                _("%(name)s is already going.") % {"name": going.first_name or str(going)},
                code="taken",
            )
        alert.acknowledged_by = member
        alert.acknowledged_at = now
        alert.save(update_fields=["acknowledged_by", "acknowledged_at", "updated_at"])
        _after_commit(tasks.refresh_alert.delay, alert.pk)
    return alert


@dataclass(frozen=True)
class BotAnswer:
    ok: bool
    message: str


def acknowledge_from_bot(alert_id: int, *, user) -> BotAnswer:
    """The button pressed in either bot by `user`, who must have had a copy of the alert."""
    copy = (
        AlertMessage.objects.select_related("member__user", "member__company", "alert")
        .filter(alert_id=alert_id, member__user=user)
        .first()
    )
    if copy is None or not copy.member.company.is_active:
        return BotAnswer(False, _("You don't have access to this."))
    try:
        acknowledge(copy.alert, copy.member)
    except VisionError as exc:
        return BotAnswer(False, str(exc))
    return BotAnswer(True, _("Thank you: everyone sees you're going."))


# Scheduled jobs ----------------------------------------------------------------------------


def resolve_stale(now: datetime | None = None) -> int:
    """Open queue and counter alerts with no news for 2 hours close (§7)."""
    now = now or timezone.now()
    closed = 0
    with transaction.atomic():
        for alert in Alert.objects.select_for_update(skip_locked=True).filter(
            state=Alert.State.OPEN,
            kind__in=Alert.CAMERA_KINDS,
            last_event_at__lt=now - STALE_AFTER,
        ):
            _resolve(alert, at=alert.last_event_at, ending=Alert.Ending.STALE)
            closed += 1
    return closed


def check_offline(now: datetime | None = None) -> int:
    """A paired box with no live report for 5 minutes: its cameras go offline and the
    managers hear about it once (§7); `mark_seen` closes it when the box is back."""
    now = now or timezone.now()
    opened = 0
    silent = (
        Agent.objects.filter(
            removed_at__isnull=True,
            demo=False,
            last_seen_at__lt=now - OFFLINE_AFTER,
            company__is_active=True,
        )
        .exclude(token_hash="")
        .exclude(
            Exists(
                Alert.objects.filter(
                    agent=OuterRef("pk"), kind=Alert.Kind.AGENT_OFFLINE, state=Alert.State.OPEN
                )
            )
        )
        .select_related("company", "branch")
    )
    for agent in silent:
        if not conf.is_on(agent.company):
            continue
        with transaction.atomic():
            agent.cameras.update(online=False, updated_at=now)
            alert = Alert.objects.create(
                company_id=agent.company_id,
                kind=Alert.Kind.AGENT_OFFLINE,
                branch_id=agent.branch_id,
                agent=agent,
                started_at=agent.last_seen_at,
                last_event_at=now,
                announced_at=now,
            )
            _after_commit(tasks.announce_alert.delay, alert.pk)
        opened += 1
    return opened


def expire_offers(now: datetime | None = None, *, agent: Agent | None = None) -> int:
    """Clips offered more than 5 minutes ago without a video are offered again, until the
    third offer; after that they fail with `agent_timeout` (§5.9)."""
    now = now or timezone.now()
    late = Clip.objects.filter(state=Clip.State.FETCHING, offered_at__lt=now - OFFER_TIMEOUT)
    if agent is not None:
        late = late.filter(camera__agent=agent)
    again = late.filter(offers__lt=Clip.MAX_OFFERS).update(state=Clip.State.PENDING, updated_at=now)
    failed = late.filter(offers__gte=Clip.MAX_OFFERS).update(
        state=Clip.State.FAILED, failure=Clip.Failure.AGENT_TIMEOUT, updated_at=now
    )
    return again + failed


def prune(now: datetime | None = None) -> dict:
    """Retention (§6.7, §8): minute stats and alerts after `stats_keep_days`, alert photos
    after `photos_keep_days`, clips (video and poster) after `clips_keep_days`."""
    from apps.companies.models import Company

    now = now or timezone.now()
    counts = {"stats": 0, "alerts": 0, "photos": 0, "clips": 0}
    companies = Company.objects.filter(vision_settings__isnull=False).select_related(
        "vision_settings"
    )
    for company in companies:
        settings = company.vision_settings
        stats_before = now - timedelta(days=settings.stats_keep_days)
        counts["stats"] += MinuteStat.objects.filter(
            company=company, minute__lt=stats_before
        ).delete()[0]
        photos_before = now - timedelta(days=settings.photos_keep_days)
        for alert in Alert.objects.filter(company=company, started_at__lt=photos_before).exclude(
            photo=""
        ):
            _delete_file(alert.photo)
            Alert.objects.filter(pk=alert.pk).update(photo="", updated_at=now)
            counts["photos"] += 1
        clips_before = now - timedelta(days=settings.clips_keep_days)
        for clip in Clip.objects.filter(camera__company=company, created_at__lt=clips_before):
            _delete_file(clip.video)
            _delete_file(clip.poster)
            clip.delete()
            counts["clips"] += 1
        old = Alert.objects.filter(company=company, started_at__lt=stats_before)
        for alert in old.exclude(photo=""):
            _delete_file(alert.photo)
        Clip.objects.filter(alert__in=old).update(alert=None)
        counts["alerts"] += old.count()
        old.delete()
    AlertEvent.objects.filter(received_at__lt=now - STATS_KEEP).delete()
    return counts


def _delete_file(field) -> None:
    if field and field.name:
        try:
            field.storage.delete(field.name)
        except OSError:
            logger.warning("Couldn't delete %s", field.name)


# Clips (§5.9, §5.10, §6.5, §6.6) -----------------------------------------------------------


def request_clip(
    camera: Camera, *, by, start: datetime, end: datetime, reason: str, sale=None, alert=None
) -> Clip:
    """A clip of `camera` from `start` to `end` (at most 60 s); the same camera and window
    (±2 s) answers the clip that is already there. Every request is audited (§8)."""
    if end <= start:
        raise VisionError(_("The clip must end after it starts."), code="window")
    if end - start > CLIP_LONGEST:
        raise VisionError(_("A clip is at most 60 seconds."), code="window")
    if start > timezone.now():
        raise VisionError(_("That moment hasn't happened yet."), code="window")
    with transaction.atomic():
        clip = queries.clip_like(camera, start, end)
        if clip is None:
            clip = Clip.objects.create(
                company_id=camera.company_id,
                camera=camera,
                reason=reason,
                start=start,
                end=end,
                sale=sale,
                alert=alert,
                requested_by=by,
            )
        _audit(
            VisionAction.CLIP_REQUESTED,
            clip,
            by,
            camera=camera.name,
            reason=reason,
            start=queries.iso(start),
            end=queries.iso(end),
            sale_id=sale.pk if sale else None,
            alert_id=alert.pk if alert else None,
        )
    return clip


def request_sale_clip(sale, *, by) -> Clip:
    """From 10 s before the sale to 5 s after, on the camera of its till (§6.6)."""
    camera = queries.counter_camera(sale)
    if camera is None:
        raise NoCamera(_("No camera films this till. Map a counter camera to it in Ko‘z."))
    return request_clip(
        camera,
        by=by,
        start=sale.sold_at - SALE_BEFORE,
        end=sale.sold_at + SALE_AFTER,
        reason=Clip.Reason.SALE,
        sale=sale,
    )


def request_alert_clip(alert: Alert, *, by) -> Clip:
    """From 10 s before the alert started to its end (or now), at most 60 s (§6.5)."""
    if alert.camera_id is None:
        raise NoCamera(_("This alert has no camera."))
    start = alert.started_at - ALERT_BEFORE
    end = min(alert.resolved_at or timezone.now(), start + CLIP_LONGEST)
    if end <= start:
        end = start + timedelta(seconds=15)
    return request_clip(
        alert.camera, by=by, start=start, end=end, reason=Clip.Reason.ALERT, alert=alert
    )


def take_jobs(agent: Agent, now: datetime | None = None) -> dict:
    """GET jobs/ (§5.9): the clips to cut, which become `fetching`, and the snapshots asked
    for."""
    now = now or timezone.now()
    expire_offers(now, agent=agent)
    with transaction.atomic():
        clips = list(
            Clip.objects.select_for_update(skip_locked=True, of=("self",))
            .filter(camera__agent=agent, state=Clip.State.PENDING)
            .select_related("camera")
            .order_by("created_at", "pk")[:10]
        )
        for clip in clips:
            clip.state = Clip.State.FETCHING
            clip.offers = F("offers") + 1
            clip.offered_at = now
            clip.save(update_fields=["state", "offers", "offered_at", "updated_at"])
    return {
        "clips": [
            {
                "id": clip.pk,
                "key": clip.camera.key,
                "start": queries.iso(clip.start),
                "end": queries.iso(clip.end),
            }
            for clip in clips
        ],
        "snapshots": queries.snapshot_keys(agent, now),
    }


def _agent_clip(agent: Agent, clip_id: int) -> Clip:
    clip = Clip.objects.select_for_update().filter(pk=clip_id, camera__agent=agent).first()
    if clip is None:
        raise NotFound(_("This box has no such clip."))
    return clip


def store_clip(agent: Agent, clip_id: int, *, video, poster, meta: dict) -> Clip:
    """POST clips/<id>/ with the video (MP4, at most 40 MB) and its poster. A clip that is
    already ready stays as it is (a box sending it again)."""
    if video is None:
        raise VisionError(_("Send the video as an MP4 file."), code="no_video")
    if video.size > CLIP_MAX:
        raise TooLarge(_("A clip is at most %(mb)d MB.") % {"mb": CLIP_MAX // (1024 * 1024)})
    video.seek(0)
    head = video.read(12)
    video.seek(0)
    if len(head) < 12 or head[4:8] != b"ftyp":
        raise VisionError(_("Send the video as an MP4 file."), code="bad_video")
    picture = _picture(poster, max_bytes=JPEG_MAX) if poster is not None else None
    now = timezone.now()
    with transaction.atomic():
        clip = _agent_clip(agent, clip_id)
        if clip.state == Clip.State.READY:
            return clip
        clip.video.save(f"{uuid.uuid4().hex}.mp4", video, save=False)
        if picture is not None:
            clip.poster.save(picture.name, picture, save=False)
        duration = meta.get("duration_s")
        clip.duration_s = min(float(duration), CLIP_MAX_SECONDS) if duration is not None else None
        clip.source = meta.get("source") or ""
        clip.width = meta.get("w")
        clip.height = meta.get("h")
        clip.state = Clip.State.READY
        clip.ready_at = now
        clip.failure = ""
        clip.failure_detail = ""
        clip.save()
    return clip


def fail_clip(agent: Agent, clip_id: int, *, failure: str, detail: str = "") -> Clip:
    """POST clips/<id>/ with `{"failed": …}`: the box couldn't cut it."""
    with transaction.atomic():
        clip = _agent_clip(agent, clip_id)
        if clip.state == Clip.State.READY:
            return clip
        clip.state = Clip.State.FAILED
        clip.failure = failure
        clip.failure_detail = (detail or "")[:300]
        clip.save(update_fields=["state", "failure", "failure_detail", "updated_at"])
    return clip
