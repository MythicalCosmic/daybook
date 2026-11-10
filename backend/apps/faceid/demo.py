"""Demo data of Face ID (apps/core/demo_plan.py): Demo Dorixona's "Chilonzor kirish" terminal at
the Chilonzor staff door, its people's numbers as the terminal shows them ("00000002"), and this
morning's scans: every check-in and check-out at Chilonzor came from the terminal, someone
scanned twice, a delivery driver who isn't in Daybook (number 00000037, "Ravshan") came by
twice, and an unknown face tried the door. Snapshots are drawn silhouettes, never photos.
"""

from datetime import time, timedelta

from django.core.files.base import ContentFile

from apps.attendance.models import AttendanceRecord
from apps.core import demo_plan
from apps.faceid import conf, hikvision, hikvision_sample
from apps.faceid.models import FaceDevice, FaceEvent, FaceIdSettings, FaceLink

Action, Flag, Kind = FaceEvent.Action, FaceEvent.Flag, FaceEvent.Kind
FACE = AttendanceRecord.Source.FACE
LOCATION_FLAGS = {"outside_geofence", "low_accuracy", "no_location"}


def seed(company, people, now) -> None:
    story = demo_plan.Plan(company, people, now)
    branch = story.branches["C"]
    # Chilonzor's people scan when they come and when they leave: the morning's check-outs came
    # from the terminal (the default is "arrival": people scan only when they come).
    row = conf.get_settings(company)
    row.scan_mode = FaceIdSettings.ScanMode.BOTH
    row.save(update_fields=["scan_mode", "updated_at"])
    device = FaceDevice.objects.create(
        company=company,
        branch=branch,
        name="Chilonzor kirish",
        direction=FaceDevice.Direction.TOGGLE,
        model="DS-K1T341AMF",
        ip="192.168.1.250",
        mac="e8:a0:ed:4c:21:7b",
        serial="DS-K1T341AMF-DEMO-0001",
        last_seen_at=now - timedelta(seconds=40),
        last_heartbeat_at=now - timedelta(minutes=3),
        clock_offset_s=0,
        clock_checked_at=now - timedelta(minutes=3),
    )
    FaceDevice.objects.filter(pk=device.pk).update(created_at=now - timedelta(days=24))
    numbers = _numbers(company, story, branch)
    serials = iter(range(40585, 41585))
    events: list[tuple[FaceEvent, str]] = []

    # Today's check-ins and check-outs at Chilonzor came from the terminal.
    records = (
        AttendanceRecord.objects.filter(
            company=company, date=story.today, branch=branch, check_in_at__isnull=False
        )
        .select_related("membership")
        .order_by("check_in_at")
    )
    for record in records:
        number = numbers.get(record.membership_id)
        if number is None:
            continue
        _from_terminal(record)
        member = record.membership
        events.append(
            (
                _event(device, number, member.first_name, record.check_in_at, next(serials))
                | {"membership": member, "record_id": record.pk, "action": Action.CHECKED_IN},
                f"demo:{member.pk}",
            )
        )
        if record.check_out_at is not None:
            events.append(
                (
                    _event(device, number, member.first_name, record.check_out_at, next(serials))
                    | {"membership": member, "record_id": record.pk, "action": Action.CHECKED_OUT},
                    f"demo:{member.pk}",
                )
            )
    # Someone held their face to the terminal twice.
    first = next((row for row in events if row[0]["action"] == Action.CHECKED_IN), None)
    if first is not None:
        row = first[0]
        again = row["event_at"] + timedelta(seconds=35)
        events.append(
            (
                _event(device, row["employee_no"], row["name_on_device"], again, next(serials))
                | {
                    "membership": row["membership"],
                    "record_id": row["record_id"],
                    "action": Action.REPEAT,
                },
                first[1],
            )
        )
    # A delivery driver who isn't in Daybook, twice; an unknown face at the door.
    for clock in (time(8, 41), time(13, 5)):
        at = story.at(story.today, clock)
        if at < now:
            events.append(
                (
                    _event(device, "00000037", "Ravshan", at, next(serials))
                    | {"action": Action.NOT_LINKED},
                    "demo:ravshan",
                )
            )
    stranger_at = story.at(story.today, time(8, 52))
    if stranger_at < now:
        events.append(
            (
                _event(device, "", "", stranger_at, next(serials), minor=76)
                | {"action": Action.STRANGER, "kind": Kind.STRANGER},
                "demo:stranger",
            )
        )

    events.sort(key=lambda row: row[0]["event_at"])
    seen: set[str] = set()
    last = None
    for fields, seed_key in events:
        key = fields.get("number_key") or seed_key
        flags = []
        if fields["kind"] == Kind.PERSON and key not in seen and fields["action"] != Action.REPEAT:
            flags.append(Flag.ARRIVAL)
            seen.add(key)
        event = FaceEvent(company=company, device=device, flags=flags, **fields)
        event.photo.save("demo.jpg", ContentFile(hikvision_sample.silhouette(seed_key)), save=False)
        event.save()
        last = event
    if last is not None:
        FaceDevice.objects.filter(pk=device.pk).update(last_event_at=last.received_at)


def _numbers(company, story, branch) -> dict[int, str]:
    """Everyone working at Chilonzor gets a number, zero-padded as the terminal shows it; the
    owner's comes first (she enrolled herself to try it)."""
    found = {}
    people = [
        member
        for member in story.members().values()
        if member.status == member.Status.APPROVED
        and (member.home_branch_id == branch.pk or branch.pk in _branch_ids(member))
    ]
    owner = story.member("owner")
    people.sort(key=lambda member: (member != owner, member.pk))
    for index, member in enumerate(people, start=2):
        number = f"{index:08d}"
        FaceLink.objects.create(company=company, employee_no=number, membership=member)
        found[member.pk] = number
    return found


def _branch_ids(member) -> set[int]:
    return set(member.branches.values_list("pk", flat=True))


def _from_terminal(record: AttendanceRecord) -> None:
    """The record as the terminal made it: no location, the face as its source."""
    record.in_source = FACE
    record.in_lat = record.in_lng = record.in_accuracy_m = record.in_distance_m = None
    if record.check_out_at is not None and record.out_source:
        record.out_source = FACE
        record.out_lat = record.out_lng = record.out_accuracy_m = record.out_distance_m = None
    record.flags = [flag for flag in record.flags if flag not in LOCATION_FLAGS]
    record.save()


def _event(device, number: str, name: str, at, serial: int, *, minor: int = 75) -> dict:
    data = hikvision_sample.event_json(device, number=number, name=name, serial=serial, at=at)
    data["AccessControllerEvent"]["subEventType"] = minor
    if not number:
        data["AccessControllerEvent"].pop("employeeNoString")
    return {
        "received_at": at + timedelta(seconds=1),
        "event_at": at,
        "device_time": at,
        "serial_no": serial,
        "employee_no": number,
        "number_key": hikvision.number_key(number),
        "name_on_device": name,
        "kind": Kind.PERSON if number else Kind.STRANGER,
        "method": FaceEvent.Method.FACE,
        "verify_mode": "cardOrFaceOrFp",
        "minor": minor,
        "raw": hikvision.cap(data),
    }
