"""Demo data of Ko‘z (docs/KOZ.md §9, apps/core/demo_plan.py): each of Demo Dorixona's pharmacies
has a paired Ko‘z box and four cameras with their zones (`Kirish` the entrance, `Kassa 1` the
counter mapped to its till, `Zal` the sales floor, `Ombor` the storeroom), snapshots and alert
photos drawn with Pillow (apps/vision/demo_art.py), never photos of people.

Fourteen days of minute stats, from the entrance and the counter, agree with the demo's
receipts: each hour's visitors are its receipts over a conversion of about two in three
(55 to 80 % a day), lower in the evening peak, when the queue grows, the waits get long and people
leave without buying. Today runs up to the moment of the build (its receipts come in tomorrow,
imported). One to three alerts a day come from those numbers: queues and a counter left alone
for a minute or two, most answered by the pharmacist on shift. The live page of a demo box moves
with the clock (apps/vision/demo_live.py). Written in bulk: the stats are about 70 000 rows.
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, time, timedelta
from itertools import pairwise

from django.core.files.base import ContentFile
from django.db.models import Count
from django.db.models.functions import ExtractHour, TruncDate

from apps.attendance.models import AttendanceRecord
from apps.core import demo_plan
from apps.vision import conf, demo_art, pairing
from apps.vision.models import Agent, Alert, Camera, MinuteStat

DAYS = 14
CAMERAS = [
    ("nvr:1", "Kirish", Camera.Role.ENTRANCE, 1),
    ("nvr:2", "Kassa 1", Camera.Role.COUNTER, 2),
    ("nvr:3", "Zal", Camera.Role.FLOOR, 3),
    ("nvr:4", "Ombor", Camera.Role.STOREROOM, 4),
]
QUEUE_PEOPLE, QUEUE_WAIT = 3, 120


def seed(company, people, now) -> None:
    """The boxes and their cameras (the stats wait for `finish`: the receipts come then)."""
    if not conf.is_on(company) or company.business_kind == "distributor":
        return
    from apps.sales.models import Register

    story = demo_plan.Plan(company, people, now)
    conf.get_settings(company)
    for index, branch in enumerate(dict.fromkeys(story.branches.values())):
        agent = Agent.objects.create(
            company=company,
            branch=branch,
            name=f"{branch.name} qutisi",
            token_hash=pairing.token_hash(pairing.new_token()),
            paired_at=now - timedelta(days=DAYS + 6, hours=3),
            hostname=f"KASSA-{branch.code or index + 1}",
            os="Windows 11 Pro",
            version="0.1.0",
            last_seen_at=now,
            demo=True,
            created_by=people.get("owner"),
        )
        Agent.objects.filter(pk=agent.pk).update(created_at=agent.paired_at - timedelta(minutes=9))
        register = Register.objects.filter(branch=branch).order_by("order", "pk").first()
        for key, name, role, channel in CAMERAS:
            camera = Camera.objects.create(
                company=company,
                agent=agent,
                branch=branch,
                key=key,
                name=name,
                renamed=True,
                role=role,
                enabled=True,
                source=Camera.Source.NVR,
                channel=channel,
                width=1920,
                height=1080,
                online=True,
                last_seen_at=now,
                zones=demo_art.ZONES[demo_art.scene_of(role)],
                register=register if role == Camera.Role.COUNTER else None,
                snapshot_at=now - timedelta(minutes=7),
            )
            picture = demo_art.snapshot(role, seed=camera.pk, zones=camera.zones)
            camera.snapshot.save(f"{uuid.uuid4().hex}.jpg", ContentFile(picture), save=True)


def finish(company, people, now) -> None:
    """Minute stats and alerts, once the sales demo has made its receipts."""
    boxes = Agent.objects.filter(company=company, demo=True).select_related("branch")
    if not boxes:
        return
    story = demo_plan.Plan(company, people, now)
    for agent in boxes:
        _numbers(company, story, agent, now)


# The numbers -------------------------------------------------------------------------------


def _hours(branch) -> range:
    if branch.open_24h:
        return range(24)
    opens = (branch.opens_at or time(8, 0)).hour
    closes = (branch.closes_at or time(22, 0)).hour
    return range(opens, closes)


def _receipts(company, branch, start: datetime, end: datetime, zone) -> dict:
    """{(local day, hour): receipts} at the branch (what the overview counts)."""
    from apps.sales.models import Sale

    rows = (
        Sale.objects.filter(
            company=company,
            branch=branch,
            kind=Sale.Kind.SALE,
            voided_at__isnull=True,
            sold_at__gte=start,
            sold_at__lt=end,
        )
        .annotate(day=TruncDate("sold_at", tzinfo=zone), hour=ExtractHour("sold_at", tzinfo=zone))
        .values("day", "hour")
        .annotate(count=Count("pk"))
    )
    return {(row["day"], row["hour"]): row["count"] for row in rows}


def _conversion(rng, hour: int, base: float) -> float:
    """The share of visitors who buy in `hour`: lower in the evening peak."""
    if 17 <= hour < 20:
        return base - rng.uniform(0.12, 0.2)
    if 8 <= hour < 11:
        return min(base + 0.06, 0.9)
    if hour >= 22 or hour < 8:
        return min(base + 0.08, 0.92)
    return base


def _numbers(company, story, agent: Agent, now: datetime) -> None:
    branch = agent.branch
    door = agent.cameras.get(role=Camera.Role.ENTRANCE)
    counter = agent.cameras.get(role=Camera.Role.COUNTER)
    zone = story.zone
    first = story.today - timedelta(days=DAYS)
    start = story.at(first, time(0, 0))
    receipts = _receipts(company, branch, start, now, zone)
    known = [count for (day, _hour), count in receipts.items() if day < story.today]
    typical = max(sum(known) / max(len(known), 1), 6.0)  # receipts an open hour
    rng = random.Random(f"koz:{company.slug}:{branch.pk}")
    rows: list[MinuteStat] = []
    incidents = []
    for back in range(DAYS, -1, -1):
        day = story.today - timedelta(days=back)
        base = rng.uniform(0.64, 0.74)
        lone = rng.random() < 0.45  # a counter left alone for a moment today
        lone_hour = rng.choice([11, 13, 15])
        day_rows: list[MinuteStat] = []
        for hour in _hours(branch):
            begins = story.at(day, time(hour))
            if begins >= now:
                break
            sold = receipts.get((day, hour))
            if day == story.today or sold is None:
                level = max(demo_from_curve(hour), 0.05)
                sold = round(typical * level * 1.6 * rng.uniform(0.8, 1.2))
            rate = max(_conversion(rng, hour, base), 0.35)
            visitors = max(round(sold / rate), sold) if sold else rng.randint(0, 2)
            minutes = min(60, int((now - begins).total_seconds() // 60))
            peak = 17 <= hour < 20
            hour_rows = _hour_rows(
                rng,
                company,
                door,
                counter,
                begins,
                minutes,
                visitors=visitors,
                staff=2 if 14 <= hour < 17 or (peak and branch.open_24h) else 1,
                peak=peak and rng.random() < 0.8,
                lone=lone and hour == lone_hour,
            )
            day_rows.extend(hour_rows)
        rows.extend(day_rows)
        incidents.extend(_incidents([row for row in day_rows if row.camera is counter], counter))
    MinuteStat.objects.bulk_create(rows, batch_size=5000)
    _alerts(company, story, agent, counter, incidents, now)


def demo_from_curve(hour: int) -> float:
    from apps.vision.demo_live import CURVE

    for (start, low), (end, high) in pairwise(CURVE):
        if start <= hour + 0.5 <= end:
            return low + (high - low) * (hour + 0.5 - start) / (end - start)
    return 0.1


def _hour_rows(rng, company, door, counter, begins, minutes, *, visitors, staff, peak, lone):
    """One hour's minutes of the entrance and the counter."""
    arrivals = [0] * 60
    for _person in range(visitors):
        arrivals[rng.randrange(60)] += 1
    load = visitors / 7.0
    away = set()
    if lone:
        first = rng.randint(10, 45)
        away = {first, first + 1, first + 2}
    rows = []
    for minute in range(minutes):
        at = begins + timedelta(minutes=minute)
        came = arrivals[minute]
        rows.append(
            MinuteStat(
                company=company,
                camera=door,
                minute=at,
                frames=120,
                people_avg=round(came * 0.4 + rng.random() * 0.3, 2),
                people_max=came + (1 if rng.random() < 0.2 else 0),
                entered=came,
                exited=arrivals[minute - 5] if minute >= 5 else 0,
            )
        )
        swell = 1.0
        if peak and 20 <= minute < 50:
            swell = 1.8 + 0.8 * rng.random()
        queue_avg = max(load * swell * (0.35 + 0.65 * rng.random()) - 0.3, 0.0)
        queue_max = round(queue_avg + rng.random() * 1.4) if queue_avg > 0.15 else 0
        if minute in away and queue_max == 0:
            queue_max, queue_avg = 1, 0.8
        wait = queue_max * (32 + int(rng.random() * 18)) + (
            int(rng.random() * 25) if queue_max else 0
        )
        alone = minute in away
        rows.append(
            MinuteStat(
                company=company,
                camera=counter,
                minute=at,
                frames=120,
                people_avg=round(queue_avg + (0 if alone else staff), 2),
                people_max=queue_max + (0 if alone else staff),
                queue_avg=round(queue_avg, 2),
                queue_max=queue_max,
                wait_max_s=wait,
                staff_seconds=0 if alone else 60,
            )
        )
    return rows


def _incidents(minutes: list[MinuteStat], counter) -> list[dict]:
    """Queues (3 or more waiting, the longest 2 minutes or more, 2 minutes in a row) and the
    counter left alone with someone waiting, at most three a day: the biggest queues first."""
    found = []
    run: list[MinuteStat] = []

    def close(kind):
        if len(run) >= 2:
            found.append({"kind": kind, "minutes": list(run)})
        run.clear()

    for row in minutes:
        if row.queue_max >= QUEUE_PEOPLE and row.wait_max_s >= QUEUE_WAIT:
            run.append(row)
        else:
            close(Alert.Kind.QUEUE)
    close(Alert.Kind.QUEUE)
    for row in minutes:
        if row.staff_seconds == 0 and row.queue_max >= 1:
            run.append(row)
        else:
            close(Alert.Kind.UNATTENDED)
    close(Alert.Kind.UNATTENDED)
    queues = sorted(
        (item for item in found if item["kind"] == Alert.Kind.QUEUE),
        key=lambda item: -max(row.queue_max for row in item["minutes"]),
    )[:2]
    alone = [item for item in found if item["kind"] == Alert.Kind.UNATTENDED][:1]
    return queues + alone


def _alerts(company, story, agent, counter, incidents, now) -> None:
    records = list(
        AttendanceRecord.objects.filter(
            company=company,
            branch=agent.branch,
            check_in_at__isnull=False,
            status__in=AttendanceRecord.ATTENDED,
            date__gte=story.today - timedelta(days=DAYS + 1),
        ).select_related("membership")
    )
    rng = random.Random(f"koz-alerts:{agent.pk}")
    photos: dict[tuple, bytes] = {}
    for incident in incidents:
        minutes = incident["minutes"]
        kind = incident["kind"]
        started = minutes[0].minute + timedelta(seconds=rng.randint(5, 40))
        ended = minutes[-1].minute + timedelta(seconds=40 + rng.randint(0, 15))
        if ended >= now:
            continue
        peak_queue = max(row.queue_max for row in minutes)
        peak_wait = max(row.wait_max_s for row in minutes)
        staff = 0 if kind == Alert.Kind.UNATTENDED else 1
        alert = Alert.objects.create(
            company=company,
            kind=kind,
            state=Alert.State.RESOLVED,
            branch=agent.branch,
            agent=agent,
            camera=counter,
            incident_id=uuid.uuid4(),
            started_at=started,
            resolved_at=ended,
            last_event_at=ended,
            queue=minutes[-1].queue_max,
            wait_s=minutes[-1].wait_max_s,
            staff=1,
            peak_queue=peak_queue,
            peak_wait_s=peak_wait,
            ending=Alert.Ending.ENDED,
            announced_at=started + timedelta(seconds=3),
        )
        going = _on_shift(records, started)
        if going is not None and rng.random() < 0.7:
            alert.acknowledged_by = going
            alert.acknowledged_at = started + timedelta(seconds=rng.randint(20, 70))
        variant = (kind, min(peak_queue, 5), staff)
        if variant not in photos:
            photos[variant] = demo_art.alert_photo(
                queue=max(min(peak_queue, 5), 1),
                wait_s=peak_wait,
                staff=staff,
                title=counter.name.upper(),
                seed=counter.pk + len(photos),
                zones=counter.zones,
            )
        alert.photo.save(f"{uuid.uuid4().hex}.jpg", ContentFile(photos[variant]), save=False)
        alert.save()
        Alert.objects.filter(pk=alert.pk).update(created_at=started)


def _on_shift(records, moment: datetime):
    for record in records:
        left = record.check_out_at or moment + timedelta(hours=1)
        if record.check_in_at <= moment <= left and record.membership.status == "approved":
            return record.membership
    return None
