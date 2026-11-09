"""Face ID: every scan a terminal sends, kept and shown, and what it sets off.

The terminal (`FaceDevice`) recognises people against its own list and posts each event
(`device_api`, parsed by `hikvision`). We never match faces. Every scan is stored with its
snapshot, whether the number is a Daybook person or not.

    services.receive(device, parsed, received_at=now)   # once per request, from device_api
    services.simulate(device, by=member)                # a test scan, as the terminal posts it
    services.cleanup_photos(now)                        # nightly: snapshots past photo_days

Rules:

* **Who.** The number's `FaceLink` ("00000002" and "2" are one number). Without one, the name on
  the terminal is matched against approved members' first names and full names (Uzbek Cyrillic or
  Latin, case, spaces and apostrophes ignored): exactly one match who has no number yet is linked
  automatically and the scan counts for them; otherwise the scan is `not_linked` (shown with its
  snapshot and suggestions).
* **Attendance.** When the company runs attendance and `FaceIdSettings.attendance` is on, a linked
  person's scan checks them in or out (`apps.attendance.services.scan`, which applies the
  terminal's direction, repeats, late deliveries and every check-in rule); otherwise the scan is
  `seen`. A scan within `repeat_minutes` of the person's last scan is a `repeat`.
* **When.** The terminal's date and clock read in the company's timezone (its own offset is often
  a factory one and means nothing); a past time always stands (a delivery after an outage keeps
  its scans' times), only a time more than 10 minutes ahead of ours takes the arrival time
  (`clock_off`). Events arriving more than 30 minutes after the scan change attendance quietly:
  no messages.
* **History.** A terminal pointed at us uploads everything it ever stored, oldest first (tens of
  thousands of scans, years back). A scan dated before the terminal was added (less 10 minutes),
  or more than a day before it arrived, is history: nothing is kept or sent, no picture is
  decoded; it is only counted on the terminal (`history_skipped`, `history_until`).
* **Telegram.** `telegram`: each person's first scan of the day (or every scan) goes with its
  snapshot to the holders of `attendance.view` who see the branch; unknown faces alert the
  managers when `alert_strangers` is on; a linked person hears about their own check-in or
  check-out when `notify_employee` is on.
* **Privacy.** Snapshots are private files (`faceid.photo`), re-encoded, kept `photo_days`;
  `raw` keeps the event without pictures or the terminal's picture links; a company without the
  module keeps nothing personal.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, time, timedelta
from urllib.parse import urlsplit

from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from django.utils.translation import gettext

from apps.attendance import clock
from apps.audit import services as audit
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.core.uploads import InvalidUpload, sanitize_image
from apps.faceid import conf, hikvision, notify
from apps.faceid.audit_actions import FaceIdAction
from apps.faceid.models import FaceDevice, FaceEvent, FaceIdSettings, FaceLink, new_device_token
from apps.members.models import Membership

logger = logging.getLogger(__name__)

PULSE_FEED = "faceid.feed"
PULSE_UNLINKED = "faceid.unlinked"

# The terminal's clock is trusted within this much of ours.
CLOCK_TOLERANCE = timedelta(minutes=10)
# How long the clock offset learned from live events is remembered.
CLOCK_MEMORY = timedelta(days=7)
# Events delivered this long after the scan send no messages.
QUIET_AFTER = timedelta(minutes=30)
# Events older than this when they arrive are the terminal's stored history: skipped.
HISTORY_AFTER = timedelta(hours=24)
# A terminal is still sending its history while some came this recently.
HISTORY_ACTIVE = timedelta(minutes=10)
# At most one unknown-face alert per terminal this often.
STRANGER_ALERT_EVERY = timedelta(minutes=10)
# An unreadable body is kept at most this often per terminal (a firmware that always sends one).
UNREADABLE_EVERY = timedelta(minutes=10)
# Snapshots are scaled down to this.
PHOTO_SIDE = 960
# Minutes between heartbeats to set on the terminal (it offers 1 to 30).
HEARTBEAT_MINUTES = 5

Action, Kind, Flag = FaceEvent.Action, FaceEvent.Kind, FaceEvent.Flag
Telegram = FaceIdSettings.Telegram


# Receiving ----------------------------------------------------------------------------------


def is_history(device: FaceDevice, item: hikvision.DeviceEvent, received_at: datetime) -> bool:
    """A scan from the terminal's stored history, not a live one: dated before the terminal was
    added (a terminal pointed at us uploads everything it ever stored, oldest first), or more
    than a day before it arrived. Kept nowhere and acted on never: only counted."""
    moment = _wall_time(device, item)
    if moment is None or item.kind == hikvision.HEARTBEAT:
        return False
    return moment < device.created_at - CLOCK_TOLERANCE or received_at - moment > HISTORY_AFTER


def history_active(device: FaceDevice, now: datetime | None = None) -> bool:
    """The terminal is still sending its old history (some came in the last 10 minutes)."""
    seen = device.history_seen_at
    return seen is not None and (now or timezone.now()) - seen < HISTORY_ACTIVE


def clock_hides_scans(device: FaceDevice, now: datetime | None = None) -> bool:
    """The terminal's clock (learned from its heartbeats and live events) is so far behind that
    a scan made now would look like history, and be skipped: its date and time need setting."""
    if device.clock_offset_s is None:
        return False
    behind = -timedelta(seconds=device.clock_offset_s)
    shown = (now or timezone.now()) - behind
    return behind > HISTORY_AFTER or shown < device.created_at - CLOCK_TOLERANCE


def receive(
    device: FaceDevice, parsed: hikvision.ParsedBody, *, received_at: datetime | None = None
) -> list[FaceEvent]:
    """Store and act on what one request carried. Returns the events stored (none for a
    heartbeat, history, a retry of an event already stored, or a disabled terminal).

    History is decided from the event's JSON alone, before any picture is decoded, so a
    terminal replaying tens of thousands of old scans costs next to nothing."""
    received_at = received_at or timezone.now()
    history, current = [], []
    for item in parsed.events:
        (history if is_history(device, item, received_at) else current).append(item)
    if history and not history_active(device, received_at):
        # The terminals page shows the history coming in; its count refreshes on its own.
        transaction.on_commit(lambda: pulse.bump(device.company_id, PULSE_FEED))
    _learn(device, current, received_at, history=history)
    if not device.enabled:
        return []
    stored = []
    readable = parsed.events or parsed.problem in ("", "empty", "no event")
    if not readable and (unreadable := _unreadable(device, parsed, received_at)) is not None:
        stored.append(unreadable)
    for item in current:
        if item.kind == hikvision.HEARTBEAT:
            continue
        event = _receive_one(device, item, parsed.pictures, received_at)
        if event is not None:
            stored.append(event)
    if stored:
        FaceDevice.objects.filter(pk=device.pk).update(last_event_at=received_at)
        device.last_event_at = received_at
        keys = [PULSE_FEED]
        if any(event.action == Action.NOT_LINKED for event in stored):
            keys.append(PULSE_UNLINKED)
        transaction.on_commit(lambda: pulse.bump(device.company_id, *keys))
    return stored


def _learn(device: FaceDevice, items: list, received_at: datetime, *, history: list = ()) -> None:
    """The terminal's status and what it says about itself; its clock from what it says now
    (live events and heartbeats only); how much old history it has sent."""
    changes = {"last_seen_at": received_at}
    if any(item.kind == hikvision.HEARTBEAT for item in items):
        changes["last_heartbeat_at"] = received_at
    for item in [*items, *history]:
        for field, value in (
            ("mac", item.mac),
            ("ip", item.ip),
            ("serial", item.device_id),
            ("model", item.model),
        ):
            if value and getattr(device, field) != value and field not in changes:
                changes[field] = value
    for item in items:
        moment = _wall_time(device, item)
        if moment is not None:
            _observe_clock(device, int((moment - received_at).total_seconds()), received_at)
    changes["clock_offset_s"] = device.clock_offset_s
    changes["clock_checked_at"] = device.clock_checked_at
    for field, value in changes.items():
        setattr(device, field, value)
    if history:
        newest = max(_wall_time(device, item) for item in history)
        until = max(device.history_until or newest, newest)
        changes |= {
            "history_skipped": F("history_skipped") + len(history),
            "history_until": until,
            "history_seen_at": received_at,
        }
        device.history_skipped += len(history)
        device.history_until, device.history_seen_at = until, received_at
    FaceDevice.objects.filter(pk=device.pk).update(**changes)


def _observe_clock(device: FaceDevice, skew_s: int, at: datetime) -> None:
    """Keep the largest offset seen lately: every event is the clock's offset minus how late it
    came (never negative), so the freshest events tell the clock itself."""
    current = device.clock_offset_s
    stale = device.clock_checked_at is None or at - device.clock_checked_at > CLOCK_MEMORY
    if current is None or stale or skew_s > current:
        device.clock_offset_s, device.clock_checked_at = skew_s, at
    elif skew_s >= current - 60:
        device.clock_checked_at = at


def _wall_time(device: FaceDevice, item: hikvision.DeviceEvent) -> datetime | None:
    """The terminal's date and clock, read in the company's timezone. Terminals are set by hand
    to local wall time and often left on their factory zone (CST-8, "+08:00"): the offset they
    send says nothing, so it is ignored (it stays in `raw`)."""
    moment = item.device_time
    if moment is None:
        return None
    return moment.replace(tzinfo=None).replace(tzinfo=clock.zone(device.company))


def _event_time(device, item, received_at) -> tuple[datetime, datetime | None, list[str]]:
    """(when it happened, what the terminal said, flags). The terminal's time stands, however
    late the event came (a past time is never replaced: a delivery after an outage keeps its
    scans' times); only a time ahead of ours by more than 10 minutes can't be right, and takes
    the arrival time (flag `clock_off`)."""
    moment = _wall_time(device, item)
    if moment is None:
        return received_at, None, [Flag.CLOCK_OFF]
    if moment - received_at > CLOCK_TOLERANCE:
        return received_at, moment, [Flag.CLOCK_OFF]
    return moment, moment, []


def _unreadable(device, parsed, received_at) -> FaceEvent | None:
    logger.warning(
        "Face ID terminal %s sent a body we can't read (%s): %r",
        device.pk,
        parsed.problem,
        parsed.excerpt[:200],
    )
    recent = FaceEvent.objects.filter(
        device=device,
        flags__contains=[Flag.UNREADABLE],
        received_at__gte=received_at - UNREADABLE_EVERY,
    )
    if recent.exists():
        return None
    return FaceEvent.objects.create(
        company_id=device.company_id,
        device=device,
        received_at=received_at,
        event_at=received_at,
        kind=Kind.OTHER,
        action=Action.IGNORED,
        raw={"problem": parsed.problem, "excerpt": parsed.excerpt[:2048]},
        flags=[Flag.UNREADABLE],
    )


def _receive_one(device, item, pictures, received_at, *, simulated=False) -> FaceEvent | None:
    company = device.company
    if (
        item.serial_no is not None
        and FaceEvent.objects.filter(device=device, serial_no=item.serial_no).exists()
    ):
        return None  # the terminal retried what we already have
    event_at, device_time, flags = _event_time(device, item, received_at)
    late = received_at - event_at > QUIET_AFTER
    quiet = simulated or late
    if late:
        flags.append(Flag.DELIVERED_LATE)
    if simulated:
        flags.append(Flag.SIMULATED)
    kind = item.kind if item.kind != hikvision.HEARTBEAT else Kind.OTHER
    event = FaceEvent(
        company=company,
        device=device,
        received_at=received_at,
        event_at=event_at,
        device_time=device_time,
        serial_no=item.serial_no,
        kind=kind,
        method=item.method,
        verify_mode=item.verify_mode,
        minor=item.minor,
        attendance_status=item.attendance_status,
        flags=flags,
    )
    if not conf.is_on(company):
        # Nothing personal for a company without the module: no number, name, photo or event.
        event.action = Action.MODULE_OFF
        event.raw = {"eventType": item.event_type, "minor": item.minor}
        try:
            return _save(event, None)
        except IntegrityError:
            return None
    event.employee_no = item.employee_no
    event.number_key = hikvision.number_key(item.employee_no)
    event.name_on_device = item.name
    event.raw = item.raw
    settings = conf.get_settings(company)
    photo = _snapshot(pictures, settings)
    try:
        with transaction.atomic():
            if kind == Kind.PERSON:
                _person(
                    event, device, item, settings, quiet=quiet, simulated=simulated, photo=photo
                )
            elif kind == Kind.STRANGER:
                event.action = Action.STRANGER
                if settings.alert_strangers and not quiet:
                    _maybe_alert(event, device, received_at)
            else:
                event.action = Action.IGNORED
            saved = _save(event, photo)
            if not quiet and kind == Kind.PERSON:
                _tell(saved, settings)
    except IntegrityError:
        return None  # the same event, stored by a request that ran at the same time
    return saved


def _save(event: FaceEvent, photo) -> FaceEvent:
    with transaction.atomic():
        event.save()
    if photo is not None:
        event.photo.save(photo.name, ContentFile(photo.file.getvalue()), save=False)
        FaceEvent.objects.filter(pk=event.pk).update(photo=event.photo.name)
    return event


def _snapshot(pictures: list[bytes], settings):
    """The first picture, re-encoded (nothing of the original kept), when snapshots are kept."""
    if not pictures or settings.photo_days == 0:
        return None
    for data in pictures:
        try:
            return sanitize_image(data, max_side=PHOTO_SIDE)
        except InvalidUpload:
            continue
    return None


# One person's scan --------------------------------------------------------------------------


def _person(event, device, item, settings, *, quiet: bool, simulated: bool, photo=None) -> None:
    company = device.company
    link = (
        FaceLink.objects.filter(company=company, number_key=event.number_key)
        .select_related("membership")
        .first()
        if event.number_key
        else None
    )
    if simulated:
        # A test scan only shows how a scan looks: no link is made, nothing is recorded.
        event.action = Action.IGNORED
        event.membership = link.membership if link is not None else None
        return
    if link is not None and link.ignored:
        event.action = Action.IGNORED
        event.flags.append(Flag.IGNORED_NUMBER)
        return
    member = link.membership if link is not None else None
    if member is None and event.number_key:
        member = _link_by_name(company, item.employee_no, item.name)
        if member is not None:
            event.flags.append(Flag.AUTO_LINKED)
    if member is None:
        event.action = Action.NOT_LINKED
        return
    event.membership = member
    if member.status != Membership.Status.APPROVED:
        event.action = Action.IGNORED
        event.flags.append(Flag.NOT_APPROVED)
        return
    window = timedelta(minutes=settings.repeat_minutes)
    if _scanned_recently(member, event.event_at, window):
        event.action = Action.REPEAT
        return
    if not conf.counts_attendance(company, settings):
        event.action = Action.SEEN
        return
    wants = _direction(device, item)
    if wants == "break":
        event.action = Action.IGNORED
        event.flags.append(Flag.BREAK)
        return
    from apps.attendance import services as attendance

    try:
        result = attendance.scan(
            member,
            at=event.event_at,
            wants=wants,
            branch=device.branch,
            photo=ContentFile(photo.file.getvalue()) if photo is not None else None,
            quiet=quiet,
            repeat_window=window,
            notify_person=settings.notify_employee,
        )
    except DomainError as exc:
        event.action = Action.SEEN
        event.flags.append(Flag.REFUSED)
        event.raw = {**event.raw, "refused": str(exc)[:200]}
        return
    event.action = {
        "checked_in": Action.CHECKED_IN,
        "checked_out": Action.CHECKED_OUT,
        "repeat": Action.REPEAT,
    }.get(result.action, Action.IGNORED)
    event.record_id = result.record.pk if result.record is not None else None
    event.flags += [flag for flag in result.flags if flag in Flag.values]
    if result.message:
        event.raw = {**event.raw, "refused": result.message}


def _direction(device: FaceDevice, item: hikvision.DeviceEvent) -> str:
    """in · out · toggle · break."""
    if item.wants == "break":
        return "break"
    if device.direction == FaceDevice.Direction.IN:
        return "in"
    if device.direction == FaceDevice.Direction.OUT:
        return "out"
    return item.wants or "toggle"


def _scanned_recently(member, at, window) -> bool:
    return FaceEvent.objects.filter(
        membership=member,
        action__in=(Action.CHECKED_IN, Action.CHECKED_OUT, Action.REPEAT, Action.SEEN),
        event_at__gt=at - window,
        event_at__lt=at + window,
    ).exists()


def _first_today(event: FaceEvent) -> bool:
    """The person's (or, unlinked, the number's) first scan of the day."""
    start = clock.at(event.company, clock.local(event.company, event.event_at).date(), time(0, 0))
    same = FaceEvent.objects.filter(
        company_id=event.company_id,
        kind=Kind.PERSON,
        event_at__gte=start,
        event_at__lt=event.event_at,
    ).exclude(pk=event.pk)
    same = same.exclude(flags__contains=[Flag.SIMULATED])
    if event.membership_id:
        same = same.filter(membership_id=event.membership_id)
    else:
        same = same.filter(number_key=event.number_key)
    return not same.exists()


def _tell(event: FaceEvent, settings: FaceIdSettings) -> None:
    """Telegram "who came", with the snapshot, once the scan is stored."""
    if event.action in (Action.IGNORED, Action.MODULE_OFF) or not event.number_key:
        return
    if settings.telegram == Telegram.OFF:
        if event.action == Action.NOT_LINKED:
            _tell_unlinked(event)
        return
    if event.action == Action.REPEAT:
        return
    arrival = _first_today(event)
    if settings.telegram == Telegram.ARRIVALS and not arrival:
        return
    if arrival:
        event.flags.append(Flag.ARRIVAL)
        FaceEvent.objects.filter(pk=event.pk).update(flags=event.flags)
    transaction.on_commit(lambda: notify.scan(event.pk, arrival=arrival))


# Links ------------------------------------------------------------------------------------


APOSTROPHES = re.compile(r"[‘’ʻʼ`´']")
# Uzbek Cyrillic in the Latin alphabet (names on a terminal come in either).
CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "ғ": "g'", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "қ": "q", "л": "l", "м": "m",
    "н": "n", "о": "o", "ў": "o'", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ҳ": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "'",
    "ь": "", "ы": "i", "э": "e", "ю": "yu", "я": "ya",
}  # fmt: skip
# Sounds spelled differently in Uzbek Latin and in Russian-style Cyrillic ("Шахзодбек" is
# "Shahzodbek", "Кодир" is "Qodir"): folded together for comparing, never for showing.
FOLDS = (("kh", "h"), ("x", "h"), ("q", "k"))


def latin(name: str) -> str:
    """`name` in lower-case Uzbek Latin ("Шахзодбек" is "shaxzodbek")."""
    return "".join(CYRILLIC.get(char, char) for char in (name or "").casefold())


def name_key(name: str) -> str:
    """A name compared without case, script, spaces or apostrophes ("Ғулом" = "G‘ulom" =
    "gulom", "Шахзодбек" = "Shahzodbek")."""
    key = re.sub(r"[\s.\-]+", "", APOSTROPHES.sub("", latin(name)))
    for spelled, folded in FOLDS:
        key = key.replace(spelled, folded)
    return key


def member_keys(member: Membership) -> set[str]:
    """The keys a terminal's name may match: the first name, the full name either way round."""
    first, last = member.first_name, member.last_name
    keys = {name_key(first), name_key(f"{first}{last}"), name_key(f"{last}{first}")}
    return {key for key in keys if key}


def match_by_name(company, name: str) -> Membership | None:
    """The one approved member whose first name or full name is `name`, if exactly one."""
    key = name_key(name)
    if len(key) < 3:
        return None
    people = Membership.objects.filter(company=company, status=Membership.Status.APPROVED).only(
        "pk", "first_name", "last_name", "company_id", "status"
    )
    found = [member for member in people if key in member_keys(member)]
    return found[0] if len(found) == 1 else None


def _link_by_name(company, employee_no: str, name: str) -> Membership | None:
    member = match_by_name(company, name)
    if member is None or FaceLink.objects.filter(company=company, membership=member).exists():
        return None
    try:
        with transaction.atomic():
            FaceLink.objects.create(
                company=company, employee_no=employee_no, membership=member, auto=True
            )
    except IntegrityError:
        return None
    audit.record(
        FaceIdAction.LINKED,
        company_id=company.pk,
        actor=None,
        target=member,
        number=employee_no,
        auto=True,
    )
    transaction.on_commit(lambda: pulse.bump(company.pk, PULSE_UNLINKED))
    return Membership.objects.select_related("company", "user").get(pk=member.pk)


def _tell_unlinked(event: FaceEvent) -> None:
    """Without "who came" messages, managers still hear about a new number, once a day (the
    notification's dedupe key is the number and the day)."""
    transaction.on_commit(lambda: notify.unlinked(event.pk))


def _maybe_alert(event: FaceEvent, device: FaceDevice, received_at: datetime) -> None:
    FaceDevice.objects.select_for_update().filter(pk=device.pk).first()
    recent = FaceEvent.objects.filter(
        device=device,
        kind=Kind.STRANGER,
        flags__contains=[Flag.ALERTED],
        received_at__gt=received_at - STRANGER_ALERT_EVERY,
    )
    if recent.exists():
        return
    event.flags.append(Flag.ALERTED)
    transaction.on_commit(lambda: event.pk and notify.stranger(event.pk))


def unlinked_numbers(company, *, device_ids=None):
    """Scans of the last 30 days whose number nobody is linked to (and nobody set aside)."""
    since = timezone.now() - timedelta(days=30)
    rows = FaceEvent.objects.filter(
        company=company, action=Action.NOT_LINKED, received_at__gte=since
    ).exclude(number_key__in=FaceLink.objects.filter(company=company).values("number_key"))
    if device_ids is not None:
        rows = rows.filter(device_id__in=device_ids)
    return rows


# Terminals and numbers: the owner API's writes (audited) ------------------------------------

DEVICE_FIELDS = ("name", "branch", "direction", "enabled")
SETTINGS_FIELDS = (
    "attendance",
    "telegram",
    "group_posts",
    "group_photos",
    "notify_employee",
    "alert_strangers",
    "repeat_minutes",
    "photo_days",
)


def _audit(by: Membership | None, action: str, target, **details) -> None:
    audit.record(
        action,
        company_id=target.company_id,
        actor=by.user if by is not None else None,
        target=target,
        **details,
    )


def _bump(company_id: int, *keys: str) -> None:
    keys = keys or (PULSE_FEED,)
    transaction.on_commit(lambda: pulse.bump(company_id, *keys))


def _clean_name(name: str) -> str:
    name = " ".join((name or "").split())[:80]
    if not name:
        raise DomainError(gettext("Give the terminal a name."))
    return name


def update_settings(company, *, by: Membership | None, **changes) -> FaceIdSettings:
    unknown = set(changes) - set(SETTINGS_FIELDS)
    if unknown:
        raise DomainError(
            gettext("Unknown setting: %(name)s") % {"name": ", ".join(sorted(unknown))}
        )
    with transaction.atomic():
        row = FaceIdSettings.objects.select_for_update().get(pk=conf.get_settings(company).pk)
        before = {name: getattr(row, name) for name in changes}
        for name, value in changes.items():
            setattr(row, name, value)
        try:
            row.full_clean(exclude=["company"], validate_unique=False, validate_constraints=False)
        except Exception as exc:
            messages = getattr(exc, "message_dict", None)
            first = next(iter(messages.values()))[0] if messages else str(exc)
            raise DomainError(str(first)) from exc
        row.save()
        changed = {
            name: [before[name], value] for name, value in changes.items() if before[name] != value
        }
        if changed:
            _audit(by, FaceIdAction.SETTINGS_CHANGED, row, changes=changed)
    _bump(company.pk, "faceid.settings")
    return row


def create_device(company, *, by: Membership | None, name: str, branch, direction: str):
    """A new terminal at `branch`, with a fresh code."""
    if branch.company_id != company.pk:
        raise DomainError(gettext("That doesn't belong to this company."))
    if direction not in FaceDevice.Direction.values:
        raise DomainError(gettext("Pick how the terminal counts scans."))
    with transaction.atomic():
        device = FaceDevice.objects.create(
            company=company,
            branch=branch,
            name=_clean_name(name),
            direction=direction,
            created_by=by.user if by is not None else None,
        )
        _audit(
            by,
            FaceIdAction.DEVICE_ADDED,
            device,
            name=device.name,
            branch=branch.name,
            direction=direction,
        )
    _bump(company.pk)
    return device


def update_device(device: FaceDevice, *, by: Membership | None, **changes) -> FaceDevice:
    unknown = set(changes) - set(DEVICE_FIELDS)
    if unknown:
        raise ValueError(f"Unknown terminal fields: {sorted(unknown)}")
    if "name" in changes:
        changes["name"] = _clean_name(changes["name"])
    if "direction" in changes and changes["direction"] not in FaceDevice.Direction.values:
        raise DomainError(gettext("Pick how the terminal counts scans."))
    branch = changes.get("branch")
    if branch is not None and branch.company_id != device.company_id:
        raise DomainError(gettext("That doesn't belong to this company."))
    with transaction.atomic():
        device = FaceDevice.objects.select_for_update().get(pk=device.pk)
        before = {name: getattr(device, name) for name in changes}
        for name, value in changes.items():
            setattr(device, name, value)
        device.save()
        changed = {
            name: [str(before[name]), str(value)]
            for name, value in changes.items()
            if before[name] != value
        }
        if changed:
            _audit(by, FaceIdAction.DEVICE_CHANGED, device, changes=changed)
    _bump(device.company_id)
    return device


def new_code(device: FaceDevice, *, by: Membership | None) -> FaceDevice:
    """A new code: the old address stops working at once (type the new one into the terminal)."""
    with transaction.atomic():
        device = FaceDevice.objects.select_for_update().get(pk=device.pk)
        device.token = new_device_token()
        device.save(update_fields=["token", "updated_at"])
        _audit(by, FaceIdAction.CODE_CHANGED, device)
    _bump(device.company_id)
    return device


def _number(value) -> str:
    """The number as the terminal shows it ("00000002"); refused when it is no number."""
    number = str(value or "").strip()[:32]
    if not hikvision.number_key(number):
        raise DomainError(gettext("Give the Employee No from the terminal."))
    return number


def link_number(company, *, by: Membership | None, employee_no, membership: Membership) -> FaceLink:
    """Link a terminal's Employee No to a person ("2" and "00000002" are one number); a number
    set aside, or linked automatically, is linked by hand instead."""
    number = _number(employee_no)
    if membership.company_id != company.pk:
        raise DomainError(gettext("That doesn't belong to this company."))
    with transaction.atomic():
        link = (
            FaceLink.objects.select_for_update()
            .filter(company=company, number_key=hikvision.number_key(number))
            .first()
        )
        if (
            link is not None
            and link.membership_id
            and link.membership_id != membership.pk
            and not link.auto
        ):
            raise DomainError(
                gettext("Number %(number)s is already linked to %(name)s.")
                % {"number": number, "name": link.membership}
            )
        if link is None:
            link = FaceLink(company=company, employee_no=number)
        link.membership, link.ignored, link.auto = membership, False, False
        link.linked_by = by.user if by is not None else None
        link.save()
        _audit(by, FaceIdAction.LINKED, membership, number=number)
        # Scans of the number that waited for a person are theirs from now on.
        FaceEvent.objects.filter(
            company=company,
            number_key=link.number_key,
            membership__isnull=True,
            kind=Kind.PERSON,
        ).update(membership=membership)
    _bump(company.pk, PULSE_FEED, PULSE_UNLINKED)
    return link


def unlink(link: FaceLink, *, by: Membership | None) -> None:
    with transaction.atomic():
        target = link.membership or link
        _audit(by, FaceIdAction.UNLINKED, target, number=link.employee_no)
        link.delete()
    _bump(link.company_id, PULSE_FEED, PULSE_UNLINKED)


def ignore_number(company, *, by: Membership | None, employee_no) -> FaceLink:
    """Set a number aside (a guard, a visitor's card): its scans are logged only, and nobody
    is asked about it again."""
    number = _number(employee_no)
    with transaction.atomic():
        link, _created = FaceLink.objects.get_or_create(
            company=company,
            number_key=hikvision.number_key(number),
            defaults={
                "employee_no": number,
                "ignored": True,
                "linked_by": by.user if by is not None else None,
            },
        )
        if link.membership_id:
            raise DomainError(
                gettext("Number %(number)s is already linked to %(name)s.")
                % {"number": number, "name": link.membership}
            )
        _audit(by, FaceIdAction.IGNORED, link, number=number)
    _bump(company.pk, PULSE_UNLINKED)
    return link


# What the owner types into the terminal -----------------------------------------------------


def device_host() -> str:
    """`PUBLIC_DEVICE_HOST`, else the host of `DASHBOARD_URL`."""
    from django.conf import settings

    host = (settings.PUBLIC_DEVICE_HOST or "").strip()
    if host:
        return urlsplit(host if "//" in host else f"//{host}").hostname or host
    return urlsplit(settings.DASHBOARD_URL or "").hostname or ""


def device_path(device: FaceDevice) -> str:
    return f"/api/v1/devices/hik/{device.token}/"


def setup(device: FaceDevice) -> dict:
    """The values for the terminal's HTTP Listening page: the host (a name, or an address), the
    URL (well under the 128 characters the firmware allows), HTTPS on 443 and plain HTTP on 80
    as the fallback, and a heartbeat so its status stays fresh."""
    host = device_host()
    path = device_path(device)
    by_address = bool(re.fullmatch(r"[\d.]+|\[?[0-9a-fA-F:]+\]?", host))
    return {
        "host": host,
        "addressing": "ipaddress" if by_address else "hostname",
        "path": path,
        "recommended": "https",
        "heartbeat_minutes": HEARTBEAT_MINUTES,
        "http": {"port": 80, "url": f"http://{host}{path}"},
        "https": {"port": 443, "url": f"https://{host}{path}"},
    }


# Snapshots ------------------------------------------------------------------------------


def cleanup_photos(now: datetime | None = None) -> int:
    """Delete snapshots older than each company's `photo_days` (all of them at 0), on the events
    and on the check-ins made from them. Returns how many files went."""
    from apps.companies.models import Company

    now = now or timezone.now()
    removed = 0
    for company in Company.objects.filter(facedevices__isnull=False).distinct():
        cutoff = now - timedelta(days=conf.get_settings(company).photo_days)
        events = FaceEvent.objects.filter(company=company, received_at__lt=cutoff).exclude(photo="")
        for event in events.iterator():
            event.photo.delete(save=False)
            FaceEvent.objects.filter(pk=event.pk).update(photo="")
            removed += 1
        from apps.attendance import services as attendance

        removed += attendance.drop_face_photos(company, before=cutoff)
    return removed


# A test scan ------------------------------------------------------------------------------


def simulate(device: FaceDevice, *, by: Membership) -> FaceEvent | None:
    """A scan of `by` posted the way the terminal posts it (through the same parser): it shows
    in the feed as a test and never changes attendance or sends anything."""
    from apps.faceid import hikvision_sample

    content_type, body = hikvision_sample.body_for(device, by)
    parsed = hikvision.parse(content_type, body)
    now = timezone.now()
    event = None
    for item in parsed.events:
        event = _receive_one(device, item, parsed.pictures, now, simulated=True)
    if event is not None:
        if event.membership_id is None:
            FaceEvent.objects.filter(pk=event.pk).update(membership=by)
            event.membership = by
        _audit(by, FaceIdAction.SIMULATED, device)
        transaction.on_commit(lambda: pulse.bump(device.company_id, PULSE_FEED))
    return event
