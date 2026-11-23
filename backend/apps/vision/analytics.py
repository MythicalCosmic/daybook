"""The numbers of a day (docs/KOZ.md §6.1) and the live page's "today" (§6.2).

What the cameras saw comes from the minute stats, summed per hour of the company's day in SQL;
what was sold from `apps.sales` (receipts: sales that weren't voided, returns are not receipts);
who was checked in from `apps.attendance`. The rules:

- `visitors`: the sum of `entered` on entrance cameras; null without an entrance camera.
- `receipts`: null while the sales module is off, and on a day without a single receipt when the
  company records shift totals rather than receipts (its receipts come in later, imported from
  the till's program: not known yet is not none).
- `conversion` = receipts / visitors when visitors > 0 and visitors ≥ receipts; otherwise null,
  with `conversion_note: "entrance_undercount"` when receipts exceed visitors.
- `left` = max(visitors - receipts, 0), or null.
- Waits and queues come from counter cameras: `wait_avg_s` is the average over the minutes with
  someone queueing of that minute's longest wait; an unattended minute is a counter camera's
  minute with someone in the queue and nobody in a staff zone the whole minute.
- `staff_avg`: the people in staff zones on average, estimated per minute from the counter
  cameras as the people outside the queue zones (`people_avg - queue_avg`), at least the share
  of the minute someone stood there (`staff_seconds / 60`), and 0 when nobody did.
- `staff_checked_in`: the people checked in at those branches during the hour.
- `compare`: the same weekday a week before; for today, up to the same time of day.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from django.db.models import Case, Count, F, FloatField, Max, Q, Sum, Value, When
from django.db.models.functions import ExtractHour, Greatest
from django.utils import timezone

from apps.attendance import clock
from apps.attendance.models import AttendanceRecord
from apps.companies.models import Branch
from apps.members import scope
from apps.vision import conf, demo_live, insights, queries
from apps.vision.models import Agent, Alert, Camera, MinuteStat

HOURS = range(24)
STAFF_ESTIMATE = Case(
    When(staff_seconds=0, then=Value(0.0)),
    default=Greatest(
        F("people_avg") - F("queue_avg"),
        F("staff_seconds") * Value(1.0) / Value(60.0),
        output_field=FloatField(),
    ),
    output_field=FloatField(),
)


def bounds(company, day: date) -> tuple[datetime, datetime]:
    start = clock.at(company, day, time(0, 0))
    return start, clock.at(company, day + timedelta(days=1), time(0, 0))


def _branches(branch_ids, branch) -> list[int] | None:
    if branch is not None:
        return [branch.pk]
    return branch_ids


def _cameras(company, branch_ids) -> list[Camera]:
    return list(scope.restrict(Camera.objects.filter(company=company), branch_ids))


def _stats(cameras: list[Camera], start: datetime, end: datetime, zone) -> dict:
    """{(hour, role): sums} of the cameras' minutes in [start, end)."""
    if not cameras:
        return {}
    rows = (
        MinuteStat.objects.filter(
            camera_id__in=[camera.pk for camera in cameras], minute__gte=start, minute__lt=end
        )
        .annotate(hour=ExtractHour("minute", tzinfo=zone), role=F("camera__role"))
        .values("hour", "role")
        .annotate(
            entered=Sum("entered"),
            queue_max=Max("queue_max"),
            wait_max=Max("wait_max_s"),
            wait_sum=Sum("wait_max_s", filter=Q(queue_max__gt=0)),
            waits=Count("pk", filter=Q(queue_max__gt=0)),
            unattended=Count("pk", filter=Q(queue_max__gt=0, staff_seconds=0)),
            staff_sum=Sum(STAFF_ESTIMATE),
            minutes=Count("minute", distinct=True),
        )
    )
    return {(row["hour"], row["role"]): row for row in rows}


def receipts_by_hour(
    company, branch_ids, start: datetime, end: datetime, zone
) -> dict[int, int] | None:
    """Receipts per local hour, or None when they can't be known (see the module's rules)."""
    if not conf.sells(company):
        return None
    from apps.sales import conf as sales_conf
    from apps.sales.models import Sale, SalesSettings

    rows = scope.restrict(
        Sale.objects.filter(
            company=company,
            kind=Sale.Kind.SALE,
            voided_at__isnull=True,
            sold_at__gte=start,
            sold_at__lt=end,
        ),
        branch_ids,
    )
    found = dict(
        rows.annotate(hour=ExtractHour("sold_at", tzinfo=zone))
        .values("hour")
        .annotate(count=Count("pk"))
        .values_list("hour", "count")
    )
    if not found and sales_conf.get_settings(company).mode != SalesSettings.Mode.RECEIPTS:
        return None
    return found


def checked_in_by_hour(
    company, branch_ids, start: datetime, end: datetime, now: datetime
) -> dict[int, int] | None:
    """How many people were checked in at the branches during each hour, or None while the
    attendance module is off."""
    if not conf.tracks_attendance(company):
        return None
    records = scope.restrict(
        AttendanceRecord.objects.filter(
            company=company,
            status__in=AttendanceRecord.ATTENDED,
            check_in_at__isnull=False,
            check_in_at__lt=end,
        ).filter(Q(check_out_at__isnull=True) | Q(check_out_at__gt=start)),
        branch_ids,
    ).values_list("membership_id", "check_in_at", "check_out_at")
    people: dict[int, set] = defaultdict(set)
    for member_id, came, left in records:
        left = left or now
        for hour in HOURS:
            hour_start = start + timedelta(hours=hour)
            if came < hour_start + timedelta(hours=1) and left > hour_start:
                people[hour].add(member_id)
    return {hour: len(people[hour]) for hour in HOURS}


def conversion(visitors, receipts) -> tuple[float | None, str | None]:
    if visitors is None or receipts is None:
        return None, None
    if receipts > visitors:
        return None, "entrance_undercount"
    if visitors <= 0:
        return None, None
    return round(receipts / visitors, 3), None


def left(visitors, receipts) -> int | None:
    if visitors is None or receipts is None:
        return None
    return max(visitors - receipts, 0)


def day_numbers(company, *, branch_ids, day: date, now: datetime, until: datetime | None = None):
    """(hours, totals) of `day` in the branches (`until` cuts the day short, for comparing)."""
    zone = clock.zone(company)
    start, end = bounds(company, day)
    if until is not None:
        end = min(end, until)
    cameras = _cameras(company, branch_ids)
    has_entrance = any(camera.role == Camera.Role.ENTRANCE for camera in cameras)
    stats = _stats(cameras, start, end, zone)
    receipts = receipts_by_hour(company, branch_ids, start, end, zone)
    checked_in = checked_in_by_hour(company, branch_ids, start, end, now)
    hours = []
    wait_sum = waits = 0
    for hour in HOURS:
        door = stats.get((hour, Camera.Role.ENTRANCE)) or {}
        counter = stats.get((hour, Camera.Role.COUNTER)) or {}
        wait_sum += counter.get("wait_sum") or 0
        waits += counter.get("waits") or 0
        minutes = counter.get("minutes") or 0
        hours.append(
            {
                "hour": hour,
                "visitors": (door.get("entered") or 0) if has_entrance else None,
                "receipts": receipts.get(hour, 0) if receipts is not None else None,
                "queue_max": counter.get("queue_max") or 0,
                "wait_max_s": counter.get("wait_max") or 0,
                "staff_avg": round((counter.get("staff_sum") or 0) / minutes, 1)
                if minutes
                else None,
                "staff_checked_in": checked_in.get(hour, 0) if checked_in is not None else None,
                "unattended_minutes": counter.get("unattended") or 0,
            }
        )
    visitors = sum(row["visitors"] for row in hours) if has_entrance else None
    sold = sum(row["receipts"] for row in hours) if receipts is not None else None
    rate, note = conversion(visitors, sold)
    alerts = scope.restrict(
        Alert.objects.filter(
            company=company,
            kind__in=Alert.CAMERA_KINDS,
            started_at__gte=start,
            started_at__lt=end,
        ),
        branch_ids,
    ).count()
    totals = {
        "visitors": visitors,
        "receipts": sold,
        "conversion": rate,
        "conversion_note": note,
        "left": left(visitors, sold),
        "wait_avg_s": round(wait_sum / waits) if waits else None,
        "wait_max_s": max((row["wait_max_s"] for row in hours), default=0),
        "alerts": alerts,
        "unattended_minutes": sum(row["unattended_minutes"] for row in hours),
    }
    return hours, totals


def overview(company, *, branch_ids, branch=None, day: date, member, now=None) -> dict:
    """GET overview/ (§6.1)."""
    now = now or timezone.now()
    ids = _branches(branch_ids, branch)
    hours, totals = day_numbers(company, branch_ids=ids, day=day, now=now)
    before = day - timedelta(days=7)
    until = None
    if day == clock.today(company, now):
        until = now - timedelta(days=7)
    _hours, earlier = day_numbers(company, branch_ids=ids, day=before, now=now, until=until)
    totals["compare"] = {
        "visitors": earlier["visitors"],
        "receipts": earlier["receipts"],
        "conversion": earlier["conversion"],
        "label": "same_weekday_last_week",
    }
    boxes = list(queries.agents(company, branch_ids=ids))
    cameras = list(
        scope.restrict(
            Camera.objects.filter(company=company, agent__removed_at__isnull=True, enabled=True),
            ids,
        )
    )
    settings = conf.get_settings(company)
    return {
        "day": day.isoformat(),
        "branch": queries.ref(branch),
        "setup": {
            "agents": len(boxes),
            "cameras": len(cameras),
            "entrance": any(camera.role == Camera.Role.ENTRANCE for camera in cameras),
            "counter": any(camera.role == Camera.Role.COUNTER for camera in cameras),
        },
        "agents": [queries.agent_brief(agent) for agent in boxes],
        "totals": totals,
        "hours": hours,
        "insights": insights.build(hours, totals, settings),
        "open_alerts": queries.open_alerts(company, branch_ids=ids, user=member.user),
    }


def today_counts(company, *, branch_ids, now: datetime | None = None) -> dict:
    """`today` of the live page: visitors and receipts since midnight. A demo box's branch counts
    from the clock (`apps.vision.demo_live`), like its cameras."""
    now = now or timezone.now()
    demo = {
        agent.branch_id: agent.branch
        for agent in scope.restrict(
            Agent.objects.filter(company=company, demo=True, removed_at__isnull=True), branch_ids
        ).select_related("branch__company")
    }
    real_ids = branch_ids
    if demo:
        everywhere = scope.restrict(Branch.objects.filter(company=company), branch_ids, field="id")
        real_ids = [pk for pk in everywhere.values_list("pk", flat=True) if pk not in demo]
    visitors = receipts = None
    if real_ids is None or real_ids:
        _hours, totals = day_numbers(
            company, branch_ids=real_ids, day=clock.today(company, now), now=now
        )
        visitors, receipts = totals["visitors"], totals["receipts"]
    for branch in demo.values():
        came, bought = demo_live.branch_today(branch, now)
        visitors = (visitors or 0) + came
        receipts = (receipts or 0) + bought
    return {"visitors": visitors, "receipts": receipts}
