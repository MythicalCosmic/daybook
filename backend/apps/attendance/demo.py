"""Demo data of attendance (apps/core/demo_plan.py): Demo Dorixona's rotas as schedules, five
weeks of shifts and check-ins, today's board, open shifts, roster drafts and requests waiting
for the heads.

Chilonzor (08:00 to 22:00) has two pairs of pharmacists, two days on and two off, one opening
and one closing; Yunusobod is open around the clock with 12-hour day (08:00 to 20:00) and night
(20:00 to 08:00) shifts, two on and two off; heads, receiving, the courier and the office work
by the week. Time off becomes leave shifts, colleagues cover each other's leave, and nobody
away has a shift or a check-in. Deterministic for a company and day (its own random generator):
Alisher is usually on time, the courier Jasur often a little late, Nigora once checked in from
home, Bekzod stayed late on his last working day.
"""

import random
from datetime import time, timedelta
from decimal import Decimal

from apps.attendance import conf, rules, services
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
from apps.core import demo_plan
from apps.members.models import Position

HISTORY_DAYS = demo_plan.ROSTER_DAYS
Flag = AttendanceRecord.Flag
Source = AttendanceRecord.Source
# Per person: chance of coming late, of staying on for overtime.
HABITS = {
    "manager": (0.04, 0.12),
    "worker": (0.06, 0.05),
    "madina": (0.08, 0.04),
    "jasur": (0.28, 0.08),
    "nigora": (0.12, 0.03),
    "sardor": (0.05, 0.06),
    "kamola": (0.1, 0.02),
}
USUAL = (0.07, 0.04)
# The roster builder's ready-made shifts, in the pharmacies' own words.
TEMPLATES = (
    ("Kunduzgi smena", time(8, 0), time(20, 0), 60, 3),
    ("Tungi navbat", time(20, 0), time(8, 0), 60, 7),
    ("Kechki smena", time(10, 0), time(22, 0), 60, 4),
    ("Ofis", time(9, 0), time(18, 0), 60, 1),
)


def seed(company, people, now) -> None:
    """Add demo rows to `company`. `people` maps owner, manager, worker, madina, jasur
    and nigora to their memberships."""
    story = demo_plan.Plan(company, people, now)
    rng = random.Random(f"attendance:{company.pk}")
    settings = _settings(company)
    _templates(company)
    _roster(company, story, now)
    _history(company, story, now, rng, settings)
    _stories(company, story, now, settings)
    _today(company, story, now, settings)
    _roster_extras(company, story, now)
    _requests(company, story, now)


def _settings(company):
    settings = conf.get_settings(company)
    settings.pre_shift_reminder_minutes = 15
    # Daily tasks follow the roster: nobody gets a routine on a day off.
    settings.tasks_follow_shifts = True
    settings.save(update_fields=["pre_shift_reminder_minutes", "tasks_follow_shifts", "updated_at"])
    return settings


def _templates(company) -> None:
    rows = list(ShiftTemplate.objects.filter(company=company).order_by("order", "pk"))
    for index, (name, starts, ends, pause, color) in enumerate(TEMPLATES):
        row = rows[index] if index < len(rows) else ShiftTemplate(company=company, order=index)
        row.name, row.starts_at, row.ends_at = name, starts, ends
        row.break_minutes, row.color = pause, color
        row.save()


# The roster ------------------------------------------------------------------------------


def _roster(company, story, now, *, days: int = HISTORY_DAYS) -> None:
    """Schedules from the story's rotas, shifts generated from them through the real service
    (time off becomes leave), then the shifts colleagues cover."""
    start = story.day(-days)
    schedules = {}
    for key, member in story.members().items():
        person = story.cast[key]
        if person.rota is None:
            continue
        schedule = schedules.get(person.rota) or _schedule(company, story, person.rota)
        schedules[person.rota] = schedule
        MemberSchedule.objects.update_or_create(
            membership=member,
            defaults={
                "company": company,
                "schedule": schedule,
                "effective_from": max(start, story.joined(key)),
            },
        )
        if member.home_branch_id is None:
            member.home_branch = story.branch(key)
            member.save(update_fields=["home_branch", "updated_at"])
    # The owner keeps flexible hours: no shifts are expected of her.
    flexible = WorkSchedule.objects.create(
        company=company, name="Erkin grafik", kind=WorkSchedule.Kind.FLEXIBLE, color=8
    )
    MemberSchedule.objects.update_or_create(
        membership=story.member("owner"),
        defaults={"company": company, "schedule": flexible, "effective_from": start},
    )

    published = now - timedelta(days=days + 2)
    services.generate_shifts(
        company, start=start, days=days + services.GENERATE_DAYS, now=published
    )
    # A suspended person gets no shifts at all: Bobur's weeks before the suspension, by hand.
    _before_suspension(company, story, start, published)
    # A shift a colleague took over with the manager's approval is theirs (see _requests).
    for swap in story.swaps:
        cover = story.member(swap.cover)
        if cover is not None and story.member(swap.who) is not None:
            WorkShift.objects.filter(
                membership=story.member(swap.who), date=story.day(swap.day)
            ).update(membership=cover, source=WorkShift.Source.SWAP)
    # Leave someone else works: Kamola does Madina's days, Alisher Gulnora's.
    taken = set(
        WorkShift.objects.filter(company=company, date__gte=start).values_list(
            "membership_id", "date"
        )
    )
    covers = []
    for key, member in story.members().items():
        for offset in range(-days, services.GENERATE_DAYS + 1):
            day = story.day(offset)
            shift = story.shift(key, day)
            if shift is None or shift.cover_for is None or (member.pk, day) in taken:
                continue
            absent = story.member(shift.cover_for)
            swapped = story.swap(day)
            if swapped is not None and swapped.cover == key:
                continue  # the swap moves the absent person's own shift (see _requests)
            covers.append(
                WorkShift(
                    company=company,
                    membership=member,
                    date=day,
                    starts_at=shift.starts,
                    ends_at=shift.ends,
                    break_minutes=shift.break_minutes,
                    branch=story.branches[shift.branch],
                    position=member.position,
                    source=WorkShift.Source.MANUAL,
                    note=f"{absent.first_name} o‘rniga" if absent else "",
                    published_at=min(now, shift.starts - timedelta(days=3)),
                )
            )
    WorkShift.objects.bulk_create(covers)


def _schedule(company, story, key: str) -> WorkSchedule:
    rota = demo_plan.ROTAS[key]
    if rota.pattern:
        return WorkSchedule.objects.create(
            company=company,
            name=rota.name,
            kind=WorkSchedule.Kind.ROTATING,
            rotation=rota.pattern,
            rotation_start=rota.anchor(story.today),
            rotation_starts_at=rota.starts,
            rotation_ends_at=rota.ends,
            rotation_break_minutes=rota.break_minutes,
            color=rota.color,
        )
    schedule = WorkSchedule.objects.create(company=company, name=rota.name, color=rota.color)
    WorkScheduleDay.objects.bulk_create(
        WorkScheduleDay(
            schedule=schedule,
            weekday=day,
            starts_at=rota.starts,
            ends_at=rota.ends,
            break_minutes=rota.break_minutes,
        )
        for day in rota.weekdays
    )
    return schedule


def _before_suspension(company, story, start, published) -> None:
    bobur = story.member(demo_plan.SUSPENDED.key)
    if bobur is None:
        return
    first = story.day(demo_plan.SUSPENSION[0])
    rows = []
    day = max(start, story.joined(demo_plan.SUSPENDED.key))
    while day < first:
        shift = story.shift(demo_plan.SUSPENDED.key, day)
        if shift is not None:
            rows.append(
                WorkShift(
                    company=company,
                    membership=bobur,
                    date=day,
                    starts_at=shift.starts,
                    ends_at=shift.ends,
                    break_minutes=shift.break_minutes,
                    branch=story.branches[shift.branch],
                    position=bobur.position,
                    source=WorkShift.Source.SCHEDULE,
                    published_at=published,
                )
            )
        day += timedelta(days=1)
    WorkShift.objects.bulk_create(rows)


# What happened --------------------------------------------------------------------------


def _point(branch, rng: random.Random, *, far: bool = False):
    if branch.latitude is None or branch.longitude is None:
        return None, None
    spread = Decimal("0.0006")
    lat = branch.latitude + Decimal(str(round(rng.uniform(-1, 1), 4))) * spread
    lng = branch.longitude + Decimal(str(round(rng.uniform(-1, 1), 4))) * spread
    if far:
        lat += Decimal("0.0105")
        lng += Decimal("0.0041")
    return lat.quantize(Decimal("0.000001")), lng.quantize(Decimal("0.000001"))


def _record(company, shift, settings, rng, *, check_in, check_out, far=False, accuracy=None):
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
        in_source=Source.APP,
        out_source=Source.APP if check_out else "",
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


def _history(company, story, now, rng, settings) -> None:
    """A check-in and out for every shift worked that's over (some late, some overtime)."""
    keys = {member.pk: key for key, member in story.members().items()}
    # Nigora once checked in from home, three shifts ago.
    far_day = story.today
    for _ in range(3):
        far_day = story.last_working_day("nigora", far_day) or far_day
    records = []
    shifts = (
        WorkShift.objects.working()
        .filter(company=company, date__lt=story.today, ends_at__lte=now - timedelta(minutes=15))
        .select_related("branch", "membership")
        .order_by("date", "starts_at")
    )
    for shift in shifts:
        key = keys.get(shift.membership_id)
        late_odds, overtime_odds = HABITS.get(key, USUAL)
        if rng.random() < late_odds:
            arrive = shift.starts_at + timedelta(minutes=rng.randint(14, 42))
        else:
            arrive = shift.starts_at - timedelta(minutes=rng.randint(2, 18))
        if rng.random() < overtime_odds:
            leave = shift.ends_at + timedelta(minutes=rng.randint(45, 110))
        else:
            leave = shift.ends_at + timedelta(minutes=rng.randint(-6, 14))
        low = rng.random() < 0.04
        record = _record(
            company,
            shift,
            settings,
            rng,
            check_in=arrive,
            check_out=min(leave, now - timedelta(minutes=5)),
            far=key == "nigora" and shift.date == far_day,
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


def _last_shift(company, member, story, *, skip: int = 0):
    shifts = (
        WorkShift.objects.working()
        .filter(company=company, membership=member, date__lt=story.today)
        .select_related("branch")
        .order_by("-date")
    )
    rows = list(shifts[: skip + 1])
    return rows[skip] if len(rows) > skip else None


def _stories(company, story, now, settings) -> None:
    manager, worker, jasur = (story.member(key) for key in ("manager", "worker", "jasur"))

    # Bekzod stayed late on his last working day: two hours of overtime wait for approval.
    last = _last_shift(company, manager, story)
    record = AttendanceRecord.objects.filter(shift=last).first() if last else None
    if record is not None:
        record.status = AttendanceRecord.Status.CLOSED
        record.check_in_at = last.starts_at - timedelta(minutes=9)
        record.check_out_at = last.ends_at + timedelta(minutes=128)
        record.overtime_status = AttendanceRecord.Overtime.NONE
        rules.compute(record, settings)
        record.save()

    # Alisher forgot to check out a few shifts ago: closed by the system, he asks to fix it.
    forgot = _last_shift(company, worker, story, skip=1)
    record = AttendanceRecord.objects.filter(shift=forgot).first() if forgot else None
    if record is not None:
        record.status = AttendanceRecord.Status.AUTO_CLOSED
        record.check_in_at = forgot.starts_at - timedelta(minutes=4)
        record.check_out_at = forgot.ends_at
        record.out_source = Source.SYSTEM
        record.flags = [Flag.AUTO_CLOSED]
        record.overtime_status = AttendanceRecord.Overtime.NONE
        rules.compute(record, settings)
        record.save()
        out = forgot.ends_at + timedelta(minutes=22)
        AttendanceCorrection.objects.create(
            company=company,
            membership=worker,
            record=record,
            date=record.date,
            check_out_at=out,
            reason=f"Telefonim o‘chib qolgan edi, {story.local(out):%H:%M} da chiqdim.",
        )

    # A shift of Jasur's without a check-in: his phone had died; he asks to fix it.
    missed = _last_shift(company, jasur, story, skip=2)
    if missed is not None:
        AttendanceRecord.objects.filter(shift=missed).delete()
        AttendanceRecord.objects.create(
            company=company,
            membership=jasur,
            shift=missed,
            date=missed.date,
            status=AttendanceRecord.Status.ABSENT,
            branch=missed.branch,
        )
        AttendanceCorrection.objects.create(
            company=company,
            membership=jasur,
            date=missed.date,
            check_in_at=missed.starts_at + timedelta(minutes=6),
            check_out_at=missed.ends_at + timedelta(minutes=3),
            reason="Telefonim zaryadsiz qolgan edi, ilova ochilmadi.",
        )

    # On a day off this week Jasur came in to help unload a delivery: an unscheduled day.
    extra_day = next(
        (
            story.day(-back)
            for back in range(1, 8)
            if story.shift("jasur", story.day(-back)) is None
            and story.away("jasur", story.day(-back)) is None
            and not WorkShift.objects.filter(membership=jasur, date=story.day(-back)).exists()
        ),
        None,
    )
    if extra_day is not None and jasur is not None:
        start, end = story.at(extra_day, time(10, 12)), story.at(extra_day, time(14, 40))
        extra = AttendanceRecord(
            company=company,
            membership=jasur,
            date=extra_day,
            status=AttendanceRecord.Status.CLOSED,
            check_in_at=start,
            check_out_at=end,
            branch=jasur.home_branch,
            in_source=Source.BOT,
            out_source=Source.BOT,
            flags=[Flag.UNSCHEDULED],
            in_accuracy_m=18,
        )
        rules.compute(extra, settings)
        extra.save()


# Today ------------------------------------------------------------------------------------


def _today(company, story, now, settings) -> None:
    """Check-ins of the shifts under way or finished today, as far as the clock has got:
    Bekzod and Alisher on time, Jasur late, the night shift handed over at 08:00."""
    rng = random.Random(f"attendance:today:{company.pk}:{story.today.isoformat()}")
    offsets = {"manager": -14, "worker": -3, "jasur": 23, "kamola": -6}
    keys = {member.pk: key for key, member in story.members().items()}
    done = set(
        AttendanceRecord.objects.filter(company=company, date__gte=story.day(-1)).values_list(
            "shift_id", flat=True
        )
    )
    shifts = (
        WorkShift.objects.working()
        .filter(company=company, date__gte=story.day(-1), starts_at__lte=now)
        .exclude(pk__in=done)
        .select_related("branch", "membership")
    )
    for shift in shifts:
        key = keys.get(shift.membership_id)
        offset = offsets.get(key, -rng.randint(2, 12))
        arrive = shift.starts_at + timedelta(minutes=offset)
        if arrive > now:
            continue
        left = None
        if shift.ends_at + timedelta(minutes=10) < now:
            left = shift.ends_at + timedelta(minutes=rng.randint(0, 9))
        _record(company, shift, settings, rng, check_in=arrive, check_out=left).save()


# Roster: open shifts, drafts -------------------------------------------------------------


def _roster_extras(company, story, now) -> None:
    pharmacist = Position.objects.filter(company=company, name=demo_plan.PHARMACIST).first()
    yunusobod = story.branches["Y"]
    published = now - timedelta(days=1)
    # Counter shifts nobody works in the coming days (someone's holiday with no cover) and an
    # extra pharmacist for Yunusobod's stock count wait for someone to take them.
    gaps = []
    for offset in range(1, services.GENERATE_DAYS):
        day = story.day(offset)
        covered = {shift.cover_for for shift in story.working(day) if shift.cover_for}
        for key, person in story.cast.items():
            if key not in story.members() or key in covered or person.rota is None:
                continue
            own = story.rostered(key, day)
            if own is None or not demo_plan.ROTAS[own.rota].counter:
                continue
            if story.leave(key, day) is None:
                continue
            gaps.append(
                (own.starts, own.ends, story.branches[own.branch], f"{person.first} ta’tilda")
            )
    inventory = story.inventory_day()
    extra = (
        story.at(inventory, time(9, 0)),
        story.at(inventory, time(18, 0)),
        yunusobod,
        "Inventarizatsiya: qo‘shimcha farmatsevt",
    )
    for starts, ends, branch, note in [*gaps[:2], extra]:
        WorkShift.objects.create(
            company=company,
            date=story.local(starts).date(),
            starts_at=starts,
            ends_at=ends,
            break_minutes=60,
            branch=branch,
            position=pharmacist,
            status=WorkShift.Status.OPEN,
            source=WorkShift.Source.MANUAL,
            note=note,
            published_at=published,
        )

    # Not published yet: Malika helps with the Saturday stock count, and an extra Sunday
    # afternoon for Alisher on a Sunday he is off.
    malika = story.member("malika")
    if (
        malika is not None
        and story.away("malika", inventory) is None
        and not WorkShift.objects.filter(membership=malika, date=inventory).exists()
    ):
        WorkShift.objects.create(
            company=company,
            membership=malika,
            date=inventory,
            starts_at=story.at(inventory, time(9, 0)),
            ends_at=story.at(inventory, time(15, 0)),
            break_minutes=30,
            branch=yunusobod,
            position=malika.position,
            source=WorkShift.Source.MANUAL,
            note="Inventarizatsiya",
        )
    worker = story.member("worker")
    first = story.day(7) + timedelta(days=(6 - story.day(7).weekday()) % 7)
    sunday = next(
        (
            first + timedelta(weeks=week)
            for week in range(4)
            if story.shift("worker", first + timedelta(weeks=week)) is None
            and story.away("worker", first + timedelta(weeks=week)) is None
        ),
        None,
    )
    if (
        worker is not None
        and sunday is not None
        and not WorkShift.objects.filter(membership=worker, date=sunday).exists()
    ):
        WorkShift.objects.create(
            company=company,
            membership=worker,
            date=sunday,
            starts_at=story.at(sunday, time(12, 0)),
            ends_at=story.at(sunday, time(18, 0)),
            break_minutes=30,
            branch=story.branches["C"],
            position=worker.position,
            source=WorkShift.Source.MANUAL,
            note="Yakshanba kuni xaridorlar ko‘p",
        )


# Requests waiting for someone ----------------------------------------------------------


def _free(story, key: str, day) -> bool:
    return (
        story.member(key) is not None
        and story.shift(key, day) is None
        and story.away(key, day) is None
    )


def _requests(company, story, now) -> None:
    worker, manager, nigora = (
        story.member("worker"),
        story.member("manager"),
        story.member("nigora"),
    )

    def own_shift(member, day):
        return WorkShift.objects.working().filter(membership=member, date=day).first()

    # Alisher's first shift after the next three days: Gulnora agreed to work it, the head
    # still has to approve.
    day = story.next_working_day("worker", story.day(3))
    shift = own_shift(worker, day) if day else None
    if shift is not None and _free(story, "gulnora", day):
        ShiftSwap.objects.create(
            company=company,
            shift=shift,
            requested_by=worker,
            kind=ShiftSwap.Kind.COVER,
            target=story.member("gulnora"),
            accepted_by=story.member("gulnora"),
            status=ShiftSwap.Status.ACCEPTED,
            note="Ukamni aeroportdan kutib olishim kerak.",
            expires_at=shift.starts_at,
        )
    # A pharmacist off that day wants the first open counter shift.
    open_shift = (
        WorkShift.objects.live()
        .filter(company=company, status=WorkShift.Status.OPEN, date__gt=story.today)
        .exclude(note__startswith="Inventarizatsiya")
        .select_related("branch")
        .order_by("starts_at")
        .first()
    )
    if open_shift is not None:
        code = next(code for code, branch in story.branches.items() if branch == open_shift.branch)
        taker = next(
            (
                key
                for key, person in story.cast.items()
                if person.position in demo_plan.QUALIFIED
                and person.branches[0] == code
                and person.rota
                and demo_plan.ROTAS[person.rota].counter
                and _free(story, key, open_shift.date)
            ),
            None,
        )
        if taker is not None:
            ShiftSwap.objects.create(
                company=company,
                shift=open_shift,
                requested_by=story.member(taker),
                kind=ShiftSwap.Kind.CLAIM,
                accepted_by=story.member(taker),
                status=ShiftSwap.Status.ACCEPTED,
                note="Bu smenani men olaman.",
                expires_at=open_shift.starts_at,
            )
    # Nigora asks Dilshod to cover one of her nights; he hasn't answered yet.
    for offset in range(2, 15):
        day = story.day(offset)
        hers = own_shift(nigora, day) if story.shift("nigora", day) else None
        if hers is not None and _free(story, "dilshod", day):
            ShiftSwap.objects.create(
                company=company,
                shift=hers,
                requested_by=nigora,
                kind=ShiftSwap.Kind.COVER,
                target=story.member("dilshod"),
                note="Shifokor qabuliga yozilganman.",
                expires_at=hers.starts_at,
            )
            break
    # A night Dilshod worked for Nigora: the head approved it beforehand.
    for swap in story.swaps:
        cover = story.member(swap.cover)
        shift = own_shift(cover, story.day(swap.day)) if cover else None
        if shift is None or shift.source != WorkShift.Source.SWAP:
            continue
        ShiftSwap.objects.create(
            company=company,
            shift=shift,
            requested_by=story.member(swap.who),
            kind=ShiftSwap.Kind.COVER,
            target=cover,
            accepted_by=cover,
            status=ShiftSwap.Status.APPROVED,
            decided_by=(story.member("farrux") or manager).user,
            decided_at=shift.starts_at - timedelta(days=2),
            expires_at=shift.starts_at,
            note=swap.note,
        )
