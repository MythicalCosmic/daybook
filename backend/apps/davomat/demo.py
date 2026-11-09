"""The Davomat demo (`manage.py davomat_demo`): "Namuna MChJ", an invented trading company with
a head office and a branch, fifteen employees on the terminals, a manager, and the last week
of scans, posted the way a Hikvision terminal posts them and handled by Face ID's own services,
so attendance, the live feed and the reports all have data. This morning a newcomer the
terminal knows but nobody added (number 00000016, "Ravshan") becomes an employee by himself
(`auto_create_employees`), and an unknown face tries the door.

`live=True` (`davomat_demo --live`) keeps today's scans still to come, and `run_live` posts each
one when its moment comes, with a heartbeat from both terminals every minute: a demo built before
work starts fills in as the morning goes, the way real terminals would make it.

No `seed` here: Daybook's `seed_demo` leaves this module alone.
"""

from __future__ import annotations

import random
import time as clock_time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from django.db import close_old_connections, connection
from django.utils import timezone

from apps.attendance import clock
from apps.attendance import services as attendance
from apps.companies import services as companies
from apps.companies.models import BranchKind, Company
from apps.core import demo_time
from apps.davomat import services
from apps.faceid import hikvision, hikvision_sample
from apps.faceid import services as faceid
from apps.faceid.models import FaceDevice
from apps.members import departments
from apps.members import services as members
from apps.members.models import Membership
from apps.timeoff import services as timeoff

NAME = "Namuna MChJ"
PASSWORD = "Namuna-2026"
DAYS_BACK = 6
OFFICE, BRANCH = "Bosh ofis", "Chilonzor filiali"
DEPARTMENTS = ("Ma’muriyat", "Savdo", "Buxgalteriya", "Ombor")
POSITIONS = (
    "Direktor o‘rinbosari",
    "Sotuv menejeri",
    "Hisobchi",
    "Kassir",
    "Omborchi",
    "Haydovchi",
    "Qorovul",
    "Direktor",
    "Filial rahbari",
)
# (first, last, name on the terminal, position, department, branch, phone, hired days ago)
PEOPLE = (
    ("Madina", "Xolmatova", "Madina", 0, 0, OFFICE, "901112201", 900),
    ("Aziza", "Karimova", "Азиза", 1, 1, OFFICE, "901112202", 620),
    ("Jamshid", "Nazarov", "Jamshid", 1, 1, OFFICE, "901112203", 410),
    ("Gulnora", "Saidova", "Gulnora", 2, 2, OFFICE, "901112204", 1300),
    ("Oydin", "Mirzayeva", "Oydin", 2, 2, OFFICE, "901112205", 95),
    ("Kamola", "Yusupova", "Камола", 3, 1, OFFICE, "901112206", 240),
    ("Bobur", "Toshmatov", "Bobur", 4, 3, OFFICE, "901112207", 700),
    ("Laziz", "Ergashev", "Laziz", 4, 3, OFFICE, "901112208", 60),
    ("Dilshod", "Rahimov", "Dilshod", 5, 3, OFFICE, "901112209", 330),
    ("Nodir", "Qodirov", "Нодир", 6, 0, OFFICE, "901112210", 1500),
    ("Sherzod", "Aliyev", "Sherzod", 1, 1, BRANCH, "901112211", 480),
    ("Shahnoza", "Islomova", "Шахноза", 3, 1, BRANCH, "901112212", 150),
    ("Temur", "Abdullayev", "Temur", 5, 3, BRANCH, "901112213", 820),
    ("Umida", "G‘aniyeva", "Umida", 1, 1, BRANCH, "901112214", 210),
    ("Zafar", "Sobirov", "Zafar", 4, 3, BRANCH, "901112215", 45),
)
NEWCOMER = ("00000016", "Ravshan")
# The director and the branch's manager sign in to the web app and scan at the door too.
USERS_WHO_SCAN = (("00000020", "Sardor", OFFICE, 7), ("00000021", "Nodira", BRANCH, 8))
SERIAL = "DS-K1T341AMF-NAMUNA-"


@dataclass
class Built:
    company: Company
    owner: Membership
    manager: Membership
    employees: list[Membership]
    devices: dict[str, FaceDevice]
    # (membership, number, name on the terminal, branch) of everyone who scans.
    scanning: list[tuple] = field(default_factory=list)
    scans: int = 0
    notes: list[str] = field(default_factory=list)
    # live: today's scans still to come, (moment, branch name, number, name on the terminal),
    # in time order, and each terminal's next serial numbers.
    pending: list[tuple] = field(default_factory=list)
    serials: dict = field(default_factory=dict)


def build(
    now: datetime | None = None,
    *,
    username: str = "admin",
    password: str = PASSWORD,
    live: bool = False,
):
    """The whole demo, as of `now`; the organization must not exist yet. `live`: today's scans
    after `now` wait in `pending` for `run_live` (otherwise they never happen)."""
    now = now or timezone.now()
    with demo_time.moment(now - timedelta(days=40)):
        owner = services.setup_organization(
            name=NAME,
            timezone="Asia/Tashkent",
            language="uz",
            admin={
                "username": username,
                "password": password,
                "first_name": "Sardor",
                "last_name": "Yusupov",
            },
        )
    company = owner.company
    owner = Membership.objects.select_related("company", "user", "role").get(pk=owner.pk)
    today = clock.today(company, now)
    with demo_time.moment(now - timedelta(days=30)):
        branches = _branches(company, owner)
        positions = [members.save_position(company, by=owner, name=name) for name in POSITIONS]
        units = [departments.create_department(company, by=owner, name=n) for n in DEPARTMENTS]
        schedule = attendance.create_schedule(
            company,
            by=owner,
            name="Ish kuni 09:00–18:00",
            days=[
                {"weekday": day, "starts_at": time(9), "ends_at": time(18), "break_minutes": 60}
                for day in range(6)
            ],
        )
        manager = services.create_user(
            company,
            by=owner,
            username="nodira",
            password=password,
            role=_role(company, "manager"),
            first_name="Nodira",
            last_name="Usmonova",
            branches=[branches[BRANCH]],
        )
        people = []
        for first, last, _shown, title, unit, where, phone, hired in PEOPLE:
            people.append(
                services.create_employee(
                    company,
                    by=owner,
                    first_name=first,
                    last_name=last,
                    phone=phone,
                    position=positions[title],
                    department=units[unit],
                    branches=[branches[where]],
                    hire_date=today - timedelta(days=hired),
                    face_numbers=[f"{len(people) + 1:08d}"],
                )
            )
        scanning = [
            (person, f"{index + 1:08d}", PEOPLE[index][2], PEOPLE[index][5])
            for index, person in enumerate(people)
        ]
        for user, (number, shown, where, title) in zip(
            (owner, manager), USERS_WHO_SCAN, strict=True
        ):
            members.update_member(user, by=owner, position=positions[title], department=units[0])
            services.update_user(user, by=owner, is_employee=True)
            services.add_face_number(user, by=owner, number=number)
            scanning.append((user, number, shown, where))
        ids = [row[0].pk for row in scanning]
        start = today - timedelta(days=DAYS_BACK + 1)
        attendance.assign_schedule(company, schedule, ids, by=owner, effective_from=start)
        attendance.generate_shifts(company, start=start, days=DAYS_BACK + 1, member_ids=ids)
    devices = _terminals(company, branches, now)
    built = Built(company, owner, manager, people, devices, scanning)
    # Oydin is on leave from today (a family wedding); her shifts say so.
    with demo_time.moment(now - timedelta(days=2)):
        timeoff.record_time_off(
            people[4], by=owner, first_day=today, last_day=today + timedelta(days=2), reason="To‘y"
        )
    _scan_the_week(built, today, now, live=live)
    with demo_time.moment(now):
        attendance.auto_close(company, now)
        attendance.mark_absences(company, now)
        # The next two weeks of the roster, as the nightly job would have made them.
        attendance.generate_shifts(company, member_ids=[row[0].pk for row in built.scanning])
    _finish_terminals(devices, now)
    return built


def is_demo(company: Company) -> bool:
    """The demo's own organization: its name, and its terminals' made-up serial numbers."""
    return (
        company.name == NAME
        and FaceDevice.objects.filter(company=company, serial__startswith=SERIAL).exists()
    )


def _role(company: Company, kind: str):
    from apps.davomat import queries

    return next(role for role in queries.web_roles(company) if queries.role_kind(role) == kind)


def _branches(company: Company, owner: Membership) -> dict:
    main = company.branches.order_by("order", "pk").first()
    companies.update_branch(
        main,
        by=owner,
        name=OFFICE,
        code="BO",
        address="Toshkent, Mirzo Ulug‘bek tumani, Buyuk Ipak Yo‘li ko‘chasi, 12",
        opens_at=time(8, 30),
        closes_at=time(18, 30),
    )
    branch = companies.create_branch(
        company,
        by=owner,
        name=BRANCH,
        code="CHL",
        address="Toshkent, Chilonzor tumani, Bunyodkor shoh ko‘chasi, 5",
        kind=BranchKind.OFFICE,
        opens_at=time(8, 30),
        closes_at=time(18, 30),
    )
    main.refresh_from_db()
    return {OFFICE: main, BRANCH: branch}


def _terminals(company: Company, branches: dict, now: datetime) -> dict[str, FaceDevice]:
    found = {}
    for index, (where, label) in enumerate(
        ((OFFICE, "Bosh ofis kirish"), (BRANCH, "Filial kirish"))
    ):
        device = FaceDevice.objects.create(
            company=company,
            branch=branches[where],
            name=label,
            direction=FaceDevice.Direction.TOGGLE,
            model="DS-K1T341AMF",
            ip=f"192.168.1.{250 + index}",
            mac=f"e8:a0:ed:4c:21:{0x7B + index:02x}",
            serial=f"{SERIAL}{index + 1:04d}",
        )
        FaceDevice.objects.filter(pk=device.pk).update(created_at=now - timedelta(days=30))
        device.refresh_from_db()
        found[where] = device
    return found


def _finish_terminals(devices: dict[str, FaceDevice], now: datetime) -> None:
    FaceDevice.objects.filter(pk__in=[device.pk for device in devices.values()]).update(
        last_seen_at=now - timedelta(seconds=40),
        last_heartbeat_at=now - timedelta(minutes=2),
        clock_offset_s=0,
        clock_checked_at=now - timedelta(minutes=2),
    )


def _post(
    built: Built,
    device: FaceDevice,
    number: str,
    name: str,
    at: datetime,
    serial: int,
    *,
    live: bool = False,
):
    """One scan, as the terminal posts it, handled by Face ID as it arrives a second later
    (`live`: now, on the real clock, with everything a scan sets off)."""
    data = hikvision_sample.event_json(device, number=number, name=name, serial=serial, at=at)
    if not number:
        data["AccessControllerEvent"].pop("employeeNoString")
        data["AccessControllerEvent"]["subEventType"] = 76  # an unknown face
    picture = hikvision_sample.silhouette(f"namuna:{number or 'stranger'}")
    content_type, body = hikvision_sample.multipart(data, picture)
    if live:
        device.refresh_from_db()
        faceid.receive(device, hikvision.parse(content_type, body))
    else:
        arrived = at + timedelta(seconds=1)
        with demo_time.moment(arrived):
            faceid.receive(device, hikvision.parse(content_type, body), received_at=arrived)
    built.scans += 1


def run_live(
    built: Built,
    *,
    say: Callable[[str], None] = lambda text: None,
    sleep: Callable[[float], None] = clock_time.sleep,
) -> int:
    """Today's scans still to come (`build(live=True)`), each when its moment comes; both
    terminals send a heartbeat every minute meanwhile, so they show online. Returns the number
    posted. Outside any transaction: each scan reaches the board as it happens."""
    posted = 0
    for at, where, number, shown in built.pending:
        while (left := (at - timezone.now()).total_seconds()) > 0:
            _heartbeat(built.devices)
            sleep(min(left, 60))
        if not connection.in_atomic_block:  # hours apart: a fresh connection if it dropped
            close_old_connections()
        _heartbeat(built.devices)
        _post(built, built.devices[where], number, shown, at, next(built.serials[where]), live=True)
        posted += 1
        say(f"{clock.hhmm(built.company, at)} {where}: {shown or '(unknown face)'}")
    return posted


def _heartbeat(devices: dict[str, FaceDevice]) -> None:
    now = timezone.now()
    FaceDevice.objects.filter(pk__in=[device.pk for device in devices.values()]).update(
        last_seen_at=now, last_heartbeat_at=now, clock_checked_at=now
    )


def _newcomer_day(company: Company, today: date, now: datetime) -> date:
    """This morning, once it is past 08:52; before that, the last workday's."""
    if clock.at(company, today, time(8, 52)) < now:
        return today
    day = today - timedelta(days=1)
    return day - timedelta(days=1) if day.weekday() == 6 else day


def _scan_the_week(built: Built, today: date, now: datetime, *, live: bool = False) -> None:
    """Each workday this past week and this morning: everyone in between 08:35 and 09:15 (a
    few late), out after 18:00; someone off sick now and then, someone who forgot to scan out.
    Each morning starts the way the nightly jobs leave it: forgotten check-outs closed and
    missed shifts marked absent. `live`: today's moments after `now` go to `built.pending`, and
    the newcomer comes today whatever the time."""
    company = built.company
    luck = random.Random(2026)
    serials = {
        where: iter(range(41000 * (n + 1), 41000 * (n + 2)))
        for n, where in enumerate(built.devices)
    }
    for number, day in enumerate(today - timedelta(days=back) for back in range(DAYS_BACK, -1, -1)):
        morning = clock.at(company, day, time(6, 0))
        if morning >= now and not (live and day == today):
            break
        if morning < now:  # a live day still to start is left to the nightly jobs
            with demo_time.moment(morning):
                attendance.auto_close(company, morning)
                attendance.mark_absences(company, morning)
        if day.weekday() == 6:
            continue  # Sunday
        moments = []
        for index, (_person, terminal_number, shown, where) in enumerate(built.scanning):
            if index == 4 and day >= today:
                continue  # on leave
            if (index * 3 + number) % 13 == 0:
                continue  # off sick, no word: an absence
            came = clock.at(company, day, time(8, 35)) + timedelta(minutes=luck.randint(0, 40))
            if luck.random() < 0.12:
                came += timedelta(minutes=luck.randint(20, 50))  # late
            went = clock.at(company, day, time(18, 0)) + timedelta(minutes=luck.randint(0, 45))
            moments.append((came, where, terminal_number, shown))
            if not (day == today - timedelta(days=1) and index == 9):  # Nodir forgot
                moments.append((went, where, terminal_number, shown))
        if day == (today if live else _newcomer_day(company, today, now)):
            # The newcomer the terminal knows, twice; an unknown face at the branch.
            newcomer, name = NEWCOMER
            moments.append((clock.at(company, day, time(8, 47)), OFFICE, newcomer, name))
            moments.append((clock.at(company, day, time(8, 47, 40)), OFFICE, newcomer, name))
            moments.append((clock.at(company, day, time(8, 52)), BRANCH, "", ""))
        for at, where, terminal_number, shown in sorted(moments, key=lambda row: row[0]):
            if at < now:
                _post(built, built.devices[where], terminal_number, shown, at, next(serials[where]))
            elif live:
                built.pending.append((at, where, terminal_number, shown))
    built.serials = serials
