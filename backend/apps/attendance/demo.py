"""Demo data of attendance: schedules, five weeks of shifts and check-ins, today's board,
open shifts, roster drafts and a few requests waiting for the manager.

Deterministic for a given company and day (its own random generator), so screenshots and
reviews see the same story: Alisher is usually on time, Jasur often a little late, Nigora
once checked in from home, Bekzod stayed late yesterday.
"""

import random
from datetime import date, time, timedelta
from decimal import Decimal

from apps.attendance import clock, conf, rules, services
from apps.attendance.models import (
    AttendanceCorrection,
    AttendanceRecord,
    MemberSchedule,
    ShiftSwap,
    ShiftTemplate,
    WorkSchedule,
    WorkScheduleDay,
    WorkShift,
)
from apps.companies.models import Branch
from apps.members.models import Position

HISTORY_DAYS = 35
Flag = AttendanceRecord.Flag
Source = AttendanceRecord.Source


def seed(company, people, now) -> None:
    """Add demo rows to `company`. `people` maps owner, manager, worker, madina, jasur
    and nigora to their memberships."""
    rng = random.Random(f"attendance:{company.pk}")
    settings = conf.get_settings(company)
    settings.pre_shift_reminder_minutes = 15
    settings.save(update_fields=["pre_shift_reminder_minutes", "updated_at"])
    today = clock.today(company, now)
    branches = list(Branch.objects.filter(company=company).order_by("order", "pk"))
    chilonzor = branches[0]
    yunusobod = branches[1] if len(branches) > 1 else branches[0]

    _rename_templates(company)
    schedules = _schedules(company, today)
    plan = {
        "manager": ("lead", chilonzor),
        "worker": ("floor", chilonzor),
        "madina": ("till", chilonzor),
        "jasur": ("stock", yunusobod),
        "nigora": ("delivery", yunusobod),
    }
    for key, (schedule_key, branch) in plan.items():
        member = people[key]
        if member.home_branch_id is None:
            member.home_branch = branch
            member.save(update_fields=["home_branch", "updated_at"])
        MemberSchedule.objects.update_or_create(
            membership=member,
            defaults={
                "company": company,
                "schedule": schedules[schedule_key],
                "effective_from": today - timedelta(days=HISTORY_DAYS),
            },
        )
    # The owner works flexible office hours: no shifts are expected of her.
    MemberSchedule.objects.update_or_create(
        membership=people["owner"],
        defaults={
            "company": company,
            "schedule": schedules["office"],
            "effective_from": today - timedelta(days=HISTORY_DAYS),
        },
    )

    published = now - timedelta(days=HISTORY_DAYS + 2)
    services.generate_shifts(
        company,
        start=today - timedelta(days=HISTORY_DAYS),
        days=HISTORY_DAYS + services.GENERATE_DAYS,
        now=published,
    )
    _history(company, people, today, now, rng, settings)
    _today(company, people, today, now, settings)
    _roster_extras(company, people, today, now, chilonzor, yunusobod)
    _requests(company, people, today, now)


def _rename_templates(company) -> None:
    """The default templates, in the shop's own words."""
    names = {
        time(9, 0): "Ertalabki",
        time(14, 0): "Kechki",
        time(22, 0): "Tungi",
    }
    for template in ShiftTemplate.objects.filter(company=company):
        if template.ends_at == time(21, 0):
            template.name = "To‘liq kun"
        elif template.starts_at in names:
            template.name = names[template.starts_at]
        template.save(update_fields=["name", "updated_at"])


def _weekly(company, name, color, days, starts, ends, pause=60) -> WorkSchedule:
    schedule = WorkSchedule.objects.create(company=company, name=name, color=color)
    WorkScheduleDay.objects.bulk_create(
        WorkScheduleDay(
            schedule=schedule, weekday=day, starts_at=starts, ends_at=ends, break_minutes=pause
        )
        for day in days
    )
    return schedule


def _schedules(company, today: date) -> dict[str, WorkSchedule]:
    monday_to_saturday = range(6)
    return {
        "lead": _weekly(
            company, "Smena boshlig‘i 6/1", 1, monday_to_saturday, time(8, 30), time(17, 30)
        ),
        "floor": _weekly(company, "Savdo zali 6/1", 3, monday_to_saturday, time(9, 0), time(18, 0)),
        "stock": _weekly(company, "Ombor 6/1", 6, monday_to_saturday, time(10, 0), time(19, 0)),
        "delivery": _weekly(company, "Yetkazib berish", 5, range(1, 7), time(11, 0), time(20, 0)),
        "till": WorkSchedule.objects.create(
            company=company,
            name="Kassa 2/2",
            kind=WorkSchedule.Kind.ROTATING,
            rotation="WWOO",
            rotation_start=today - timedelta(days=HISTORY_DAYS + 1),
            rotation_starts_at=time(9, 0),
            rotation_ends_at=time(21, 0),
            rotation_break_minutes=90,
            color=4,
        ),
        "office": WorkSchedule.objects.create(
            company=company, name="Erkin grafik (ofis)", kind=WorkSchedule.Kind.FLEXIBLE, color=8
        ),
        "night": _weekly(company, "Tungi navbat", 7, range(5, 7), time(22, 0), time(7, 0)),
    }


def _point(branch: Branch, rng: random.Random, *, far: bool = False):
    if branch.latitude is None or branch.longitude is None:
        return None, None
    spread = Decimal("0.0006")
    lat = branch.latitude + Decimal(str(round(rng.uniform(-1, 1), 4))) * spread
    lng = branch.longitude + Decimal(str(round(rng.uniform(-1, 1), 4))) * spread
    if far:
        lat += Decimal("0.0105")
        lng += Decimal("0.0041")
    return lat.quantize(Decimal("0.000001")), lng.quantize(Decimal("0.000001"))


def _record(
    company,
    shift,
    settings,
    rng,
    *,
    check_in,
    check_out,
    far=False,
    accuracy=None,
    source=Source.APP,
):
    branch = shift.branch
    lat, lng = _point(branch, rng, far=far)
    accuracy = accuracy if accuracy is not None else rng.randint(8, 35)
    record = AttendanceRecord(
        company=company,
        membership=shift.membership,
        shift=shift,
        date=shift.date,
        status=AttendanceRecord.Status.CLOSED if check_out else AttendanceRecord.Status.OPEN,
        check_in_at=check_in,
        check_out_at=check_out,
        branch=branch,
        in_lat=lat,
        in_lng=lng,
        in_accuracy_m=accuracy,
        in_source=source,
        out_source=source if check_out else "",
    )
    distance, _outside, flags = services._locate(branch, lat, lng, accuracy, settings)
    record.in_distance_m = distance
    record.flags = [str(flag) for flag in flags]
    if check_out:
        out_lat, out_lng = _point(branch, rng)
        record.out_lat, record.out_lng = out_lat, out_lng
        record.out_accuracy_m = rng.randint(8, 30)
        record.out_distance_m = services._locate(
            branch, out_lat, out_lng, record.out_accuracy_m, settings
        )[0]
    rules.compute(record, settings)
    return record


# Five weeks of what happened ----------------------------------------------------------------

# Per person: chance of being late, of being absent, of overtime.
HABITS = {
    "manager": (0.04, 0.0, 0.12),
    "worker": (0.06, 0.02, 0.05),
    "madina": (0.08, 0.03, 0.04),
    "jasur": (0.28, 0.06, 0.08),
    "nigora": (0.12, 0.04, 0.03),
}


def _history(company, people, today, now, rng, settings) -> None:
    keys = {member.pk: key for key, member in people.items()}
    records = []
    shifts = (
        WorkShift.objects.working()
        .filter(company=company, date__lt=today, membership__in=list(people.values()))
        .select_related("branch", "membership")
        .order_by("date", "starts_at")
    )
    for shift in shifts:
        key = keys.get(shift.membership_id)
        if key not in HABITS:
            continue
        late_odds, absent_odds, overtime_odds = HABITS[key]
        roll = rng.random()
        if roll < absent_odds:
            records.append(
                AttendanceRecord(
                    company=company,
                    membership=shift.membership,
                    shift=shift,
                    date=shift.date,
                    status=AttendanceRecord.Status.ABSENT,
                    branch=shift.branch,
                )
            )
            continue
        if rng.random() < late_odds:
            arrive = shift.starts_at + timedelta(minutes=rng.randint(14, 42))
        else:
            arrive = shift.starts_at - timedelta(minutes=rng.randint(2, 18))
        if rng.random() < overtime_odds:
            leave = shift.ends_at + timedelta(minutes=rng.randint(45, 110))
        else:
            leave = shift.ends_at + timedelta(minutes=rng.randint(-6, 14))
        far = key == "nigora" and shift.date == today - timedelta(days=8)
        low = rng.random() < 0.04
        record = _record(
            company,
            shift,
            settings,
            rng,
            check_in=arrive,
            check_out=leave,
            far=far,
            accuracy=rng.randint(260, 900) if low else None,
        )
        if record.overtime_status == AttendanceRecord.Overtime.PENDING:
            record.overtime_status = (
                AttendanceRecord.Overtime.APPROVED
                if rng.random() < 0.8
                else AttendanceRecord.Overtime.REJECTED
            )
        records.append(record)
    AttendanceRecord.objects.bulk_create(records)

    # Bekzod stayed late yesterday: two hours of overtime wait for approval.
    yesterday = _last_shift(people["manager"], today)
    if yesterday is not None:
        record = AttendanceRecord.objects.filter(shift=yesterday).first()
        if record is not None:
            record.status = AttendanceRecord.Status.CLOSED
            record.check_in_at = yesterday.starts_at - timedelta(minutes=9)
            record.check_out_at = yesterday.ends_at + timedelta(minutes=128)
            record.overtime_status = AttendanceRecord.Overtime.NONE
            rules.compute(record, settings)
            record.save()

    # Alisher forgot to check out two working days ago: closed automatically.
    forgot = _last_shift(people["worker"], today, skip=1)
    if forgot is not None:
        record = AttendanceRecord.objects.filter(shift=forgot).first()
        if record is not None:
            record.status = AttendanceRecord.Status.AUTO_CLOSED
            record.check_in_at = forgot.starts_at - timedelta(minutes=4)
            record.check_out_at = forgot.ends_at
            record.out_source = Source.SYSTEM
            record.flags = [Flag.AUTO_CLOSED]
            record.overtime_status = AttendanceRecord.Overtime.NONE
            rules.compute(record, settings)
            record.save()
            AttendanceCorrection.objects.create(
                company=company,
                membership=people["worker"],
                record=record,
                date=record.date,
                check_out_at=forgot.ends_at + timedelta(minutes=22),
                reason="Telefonim o‘chib qolgan edi, 18:22 da chiqdim.",
            )

    # Jasur's Saturday without a check-in: he asks to fix it (the network was down).
    missed = _last_shift(people["jasur"], today, skip=2)
    if missed is not None:
        AttendanceRecord.objects.filter(shift=missed).delete()
        AttendanceRecord.objects.create(
            company=company,
            membership=people["jasur"],
            shift=missed,
            date=missed.date,
            status=AttendanceRecord.Status.ABSENT,
            branch=missed.branch,
        )
        AttendanceCorrection.objects.create(
            company=company,
            membership=people["jasur"],
            date=missed.date,
            check_in_at=missed.starts_at + timedelta(minutes=6),
            check_out_at=missed.ends_at + timedelta(minutes=3),
            reason="Omborda internet yo‘q edi, ilova ochilmadi.",
        )

    # One Sunday Jasur came in to count stock: an extra, unscheduled day.
    sunday = today - timedelta(days=today.weekday() + 1)
    if sunday < today:
        start, end = clock.window(company, sunday, time(10, 12), time(14, 40))
        extra = AttendanceRecord(
            company=company,
            membership=people["jasur"],
            date=sunday,
            status=AttendanceRecord.Status.CLOSED,
            check_in_at=start,
            check_out_at=end,
            branch=people["jasur"].home_branch,
            in_source=Source.BOT,
            out_source=Source.BOT,
            flags=[Flag.UNSCHEDULED],
            in_accuracy_m=18,
        )
        rules.compute(extra, settings)
        extra.save()


def _last_shift(member, today, *, skip: int = 0):
    shifts = (
        WorkShift.objects.working()
        .filter(membership=member, date__lt=today)
        .select_related("branch")
        .order_by("-date")
    )
    rows = list(shifts[: skip + 1])
    return rows[skip] if len(rows) > skip else None


# Today ------------------------------------------------------------------------------------


def _today(company, people, today, now, settings) -> None:
    """Today's story as far as the clock has got: Bekzod and Alisher on time, Jasur late,
    Nigora not here yet (her shift starts later), Madina on leave."""
    rng = random.Random(f"attendance:today:{company.pk}:{today.isoformat()}")
    plan = {
        "manager": timedelta(minutes=-14),
        "worker": timedelta(minutes=-3),
        "jasur": timedelta(minutes=23),
    }
    for key, offset in plan.items():
        shift = (
            WorkShift.objects.working()
            .filter(membership=people[key], date=today)
            .select_related("branch")
            .first()
        )
        if shift is None:
            continue
        arrive = shift.starts_at + offset
        if arrive > now:
            continue
        record = _record(company, shift, settings, rng, check_in=arrive, check_out=None)
        if shift.ends_at + timedelta(minutes=10) < now:
            record.check_out_at = shift.ends_at + timedelta(minutes=rng.randint(0, 9))
            record.status = AttendanceRecord.Status.CLOSED
            record.out_source = Source.APP
            rules.compute(record, settings)
        record.save()


# Roster: open shifts, drafts, a manual shift ---------------------------------------------------


def _roster_extras(company, people, today, now, chilonzor, yunusobod) -> None:
    floor = Position.objects.filter(company=company, name="Sales floor").first()
    till = Position.objects.filter(company=company, name="Cashier").first()
    saturday = today + timedelta(days=(5 - today.weekday()) % 7 or 7)
    sunday = saturday + timedelta(days=1)
    published = now - timedelta(days=1)
    for day, branch, position, starts, ends, note in (
        (
            saturday,
            yunusobod,
            till,
            time(12, 0),
            time(21, 0),
            "Dam olish kuni xaridor ko‘p bo‘ladi",
        ),
        (sunday, chilonzor, floor, time(10, 0), time(19, 0), "Yangi kolleksiya keladi"),
    ):
        start, end = clock.window(company, day, starts, ends)
        WorkShift.objects.create(
            company=company,
            date=day,
            starts_at=start,
            ends_at=end,
            break_minutes=60,
            branch=branch,
            position=position,
            status=WorkShift.Status.OPEN,
            source=WorkShift.Source.MANUAL,
            note=note,
            published_at=published,
        )

    # Next week's roster is being reworked: three drafts not published yet.
    next_monday = clock.week_start(today) + timedelta(days=7)
    drafts = (
        (people["worker"], next_monday + timedelta(days=6), time(10, 0), time(16, 0), chilonzor),
        (people["nigora"], next_monday, time(9, 0), time(15, 0), yunusobod),
    )
    for member, day, starts, ends, branch in drafts:
        if WorkShift.objects.filter(membership=member, date=day).exists():
            continue
        start, end = clock.window(company, day, starts, ends)
        WorkShift.objects.create(
            company=company,
            membership=member,
            date=day,
            starts_at=start,
            ends_at=end,
            break_minutes=30,
            branch=branch,
            position=member.position,
            source=WorkShift.Source.MANUAL,
            note="Inventarizatsiya",
        )
    start, end = clock.window(company, next_monday + timedelta(days=2), time(14, 0), time(23, 0))
    WorkShift.objects.create(
        company=company,
        date=next_monday + timedelta(days=2),
        starts_at=start,
        ends_at=end,
        branch=chilonzor,
        position=floor,
        status=WorkShift.Status.OPEN,
        source=WorkShift.Source.MANUAL,
    )


# Requests waiting for someone ----------------------------------------------------------


def _requests(company, people, today, now) -> None:
    worker, manager, jasur, nigora = (
        people["worker"],
        people["manager"],
        people["jasur"],
        people["nigora"],
    )
    # Alisher's Saturday: Bekzod agreed to cover, the swap waits for approval.
    saturday = today + timedelta(days=(5 - today.weekday()) % 7 or 7)
    shift = WorkShift.objects.working().filter(membership=worker, date=saturday).first()
    if shift is not None:
        ShiftSwap.objects.create(
            company=company,
            shift=shift,
            requested_by=worker,
            kind=ShiftSwap.Kind.COVER,
            target=manager,
            accepted_by=manager,
            status=ShiftSwap.Status.ACCEPTED,
            note="Singlimning to‘yi, iltimos.",
            expires_at=shift.starts_at,
        )
    # Alisher also wants Sunday's open shift at Chilonzor.
    open_shift = (
        WorkShift.objects.live()
        .filter(company=company, status=WorkShift.Status.OPEN, branch=worker.home_branch)
        .order_by("starts_at")
        .first()
    )
    if open_shift is not None:
        ShiftSwap.objects.create(
            company=company,
            shift=open_shift,
            requested_by=worker,
            kind=ShiftSwap.Kind.CLAIM,
            accepted_by=worker,
            status=ShiftSwap.Status.ACCEPTED,
            expires_at=open_shift.starts_at,
        )
    # Nigora asks Jasur to cover her Friday; he hasn't answered yet.
    friday = today + timedelta(days=(4 - today.weekday()) % 7 or 7)
    hers = WorkShift.objects.working().filter(membership=nigora, date=friday).first()
    if hers is not None:
        ShiftSwap.objects.create(
            company=company,
            shift=hers,
            requested_by=nigora,
            kind=ShiftSwap.Kind.COVER,
            target=jasur,
            note="Shifokor qabuliga yozilganman.",
            expires_at=hers.starts_at,
        )
    # Last week: a covered shift (approved) and a request nobody took (expired).
    past = (
        WorkShift.objects.working().filter(membership=jasur, date__lt=today).order_by("-date")[5:6]
    )
    for old in past:
        ShiftSwap.objects.create(
            company=company,
            shift=old,
            requested_by=nigora,
            kind=ShiftSwap.Kind.COVER,
            target=jasur,
            accepted_by=jasur,
            status=ShiftSwap.Status.APPROVED,
            decided_by=manager.user,
            decided_at=old.starts_at - timedelta(days=2),
            expires_at=old.starts_at,
            note="Oilaviy sabab",
        )
