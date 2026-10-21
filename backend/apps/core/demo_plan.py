"""The demo's one story (development only, docs/PLAN-OWNER.md §14.3): a two-pharmacy business
in Tashkent and a small distributor with the same owner; who works there, which shifts they
work, who is away when, and the days every app's demo agrees on.

- **Demo Dorixona** (`PHARMACY`): Chilonzor, open 08:00 to 22:00 every day, and Yunusobod,
  open around the clock with 12-hour day (08:00 to 20:00) and night (20:00 to 08:00) shifts.
- **Demo Distribyutor** (`DISTRIBUTOR`): one warehouse in Sergeli, Monday to Saturday, selling
  by invoice to invented pharmacies and clinics.

seed_demo makes the companies and their people from the tables below; each app's `demo.py`
reads `Plan` instead of inventing its own calendar, so the apps tell one story: nobody on time
off, suspended or gone has a shift, a till, a task or project time that day, nothing happens
before someone joined, and a till is run by the people rostered at its counter (§2.3 rule 22).
Days are offsets from the seed's company-local day, so the story reads the same whatever day the
demo is built. Every company, brand and person here is invented; medicines go by their generic
name.

Positions and roles are made with English names and renamed to Uzbek (`IN_UZBEK_*`) once every
demo has run, because the module demos look them up by the English names.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

PHARMACY = "demo-pharmacy"
DISTRIBUTOR = "demo-distributor"
# What earlier demos were called: --reset removes them too.
OLD_SLUGS = ("demo-shop", "demo-cafe", "shifo-dorixonalari", "salomat-dorixona")

LEDGER_DAYS = 62  # the finance ledger: two months, so a month compares with the one before
SALES_DAYS = 21  # tills through the real sales services (before: imported, from the ledger)
ROSTER_DAYS = LEDGER_DAYS  # attendance: every day a till ran has its shifts and check-ins
SMALL_DAYS = 21  # the distributor's routines and books

# Positions in roster order (English as made, Uzbek once every demo has run).
HEAD = "Head of pharmacy"
SENIOR = "Senior pharmacist"
PHARMACIST = "Pharmacist"
STOCK = "Stock & receiving"
COURIER = "Courier"
OFFICE = "Office"
POSITIONS = [HEAD, SENIOR, PHARMACIST, STOCK, COURIER, OFFICE]
WAREHOUSE_HEAD = "Warehouse manager"
STOREKEEPER = "Storekeeper"
SALES_MANAGER = "Sales manager"
DRIVER = "Driver"
SMALL_POSITIONS = [WAREHOUSE_HEAD, STOREKEEPER, SALES_MANAGER, DRIVER, OFFICE]
QUALIFIED = (HEAD, SENIOR, PHARMACIST)  # pharmaceutical education: may sell medicines
# Pharmacists who run a till hold the Cashier role, the others Employee; the head of Yunusobod
# has the one role the demo adds, which sees only her pharmacy.
BRANCH_MANAGER = "Branch manager"
IN_UZBEK_POSITIONS = {
    HEAD: "Dorixona mudiri",
    SENIOR: "Provizor",
    PHARMACIST: "Farmatsevt",
    STOCK: "Omborchi",
    COURIER: "Kuryer",
    OFFICE: "Ofis",
    WAREHOUSE_HEAD: "Ombor mudiri",
    STOREKEEPER: "Omborchi",
    SALES_MANAGER: "Savdo menejeri",
    DRIVER: "Haydovchi",
}
IN_UZBEK_ROLES = {
    "Owner": "Egasi",
    "Manager": "Rahbar",
    "Accountant": "Hisobchi",
    "Cashier": "Kassir",
    "Employee": "Xodim",
    BRANCH_MANAGER: "Filial rahbari",
}


@dataclass(frozen=True)
class Rota:
    """A working pattern: `weekdays` (Monday is 0), or `pattern` of W(ork) and O(ff) days that
    repeats, at position `offset` on the seed day."""

    name: str  # the schedule's name in the attendance pages
    starts: time
    ends: time  # at or before `starts`: the shift ends the next morning
    break_minutes: int = 60
    weekdays: tuple[int, ...] = ()
    pattern: str = ""
    offset: int = 0
    color: int = 1
    counter: bool = False  # serves customers at the counter (and so may run its till)

    def works_on(self, day: date, today: date) -> bool:
        if self.pattern:
            return self.pattern[((day - today).days + self.offset) % len(self.pattern)] == "W"
        return day.weekday() in self.weekdays

    def anchor(self, today: date) -> date:
        """The day the pattern starts (attendance's `rotation_start`)."""
        return today - timedelta(days=self.offset)


H = time
TWO_TWO = "WWOO"  # two days on, two off
WEEKDAYS, SIX_DAYS = (0, 1, 2, 3, 4), (0, 1, 2, 3, 4, 5)
ROTAS = {
    # Chilonzor, 08:00 to 22:00: two pairs, two days on and two off. In each pair one opens at
    # 08:00 and one closes at 22:00, so there are two at the counter from 10:00 to 20:00.
    "chl_open_a": Rota("Chilonzor 2/2 ertalab (A)", H(8), H(20), 60, (), TWO_TWO, 0, 3, True),
    "chl_close_a": Rota("Chilonzor 2/2 kechqurun (A)", H(10), H(22), 60, (), TWO_TWO, 0, 4, True),
    "chl_open_b": Rota("Chilonzor 2/2 ertalab (B)", H(8), H(20), 60, (), TWO_TWO, 2, 3, True),
    "chl_close_b": Rota("Chilonzor 2/2 kechqurun (B)", H(10), H(22), 60, (), TWO_TWO, 2, 4, True),
    # Yunusobod, around the clock: 12-hour day and night shifts, two on and two off.
    "yns_day_a": Rota("Yunusobod kunduzgi 2/2 (A)", H(8), H(20), 60, (), TWO_TWO, 0, 5, True),
    "yns_day_b": Rota("Yunusobod kunduzgi 2/2 (B)", H(8), H(20), 60, (), TWO_TWO, 2, 5, True),
    "yns_night_a": Rota("Yunusobod tungi 2/2 (A)", H(20), H(8), 60, (), TWO_TWO, 0, 7, True),
    "yns_night_b": Rota("Yunusobod tungi 2/2 (B)", H(20), H(8), 60, (), TWO_TWO, 2, 8, True),
    "senior5": Rota("Provizor 5/2", H(9), H(18), 60, WEEKDAYS, color=6, counter=True),
    "head5": Rota("Mudir 5/2", H(9), H(18), 60, WEEKDAYS, color=1),
    "head6": Rota("Mudir 6/1", H(9), H(18), 60, SIX_DAYS, color=2),
    "office": Rota("Ofis 5/2", H(9), H(18), 60, WEEKDAYS, color=1),
    "stock": Rota("Omborchi 6/1", H(9), H(18), 60, SIX_DAYS, color=6),
    "courier": Rota("Kuryer (seshanbadan yakshanbagacha)", H(10), H(19), 60, (1, 2, 3, 4, 5, 6)),
    # The distributor's warehouse, Monday to Saturday.
    "warehouse": Rota("Ombor 6/1", H(9), H(18), 60, SIX_DAYS, color=2),
    "sales": Rota("Savdo bo‘limi 5/2", H(9), H(18), 60, WEEKDAYS, color=1),
    "driver": Rota("Haydovchi 6/1", H(8), H(17), 60, SIX_DAYS, color=5),
}


@dataclass(frozen=True)
class Person:
    key: str
    telegram_id: int
    first: str
    last: str
    position: str | None
    role: str
    branches: str  # branch codes, the first is home: C(hilonzor), Y(unusobod), S(ergeli)
    joined: int  # days before the seed day
    rota: str | None  # a key of ROTAS; None: no shifts (flexible hours)

    @property
    def phone(self) -> str:
        return PHONES.get(self.telegram_id, "")

    @property
    def username(self) -> str:
        return USERNAMES.get(self.telegram_id, "")

    @property
    def language(self) -> str:
        return "ru" if self.telegram_id in RUSSIAN else "uz"

    @property
    def name(self) -> str:
        return f"{self.first} {self.last}"


P = Person
TILL = "Cashier"  # runs a till: the Cashier role adds that to an employee's
# Demo Dorixona. The first six are the `people` every demo.py gets (rule 22).
PEOPLE = [
    P("owner", 1001, "Dilnoza", "Karimova", OFFICE, "Owner", "CY", 1100, None),
    P("manager", 1002, "Bekzod", "Mirzayev", HEAD, "Manager", "CY", 760, "head5"),
    P("worker", 4242, "Alisher", "Valiyev", PHARMACIST, TILL, "C", 380, "chl_open_a"),
    P("madina", 1004, "Madina", "Saidova", SENIOR, TILL, "C", 230, "chl_close_a"),
    P("jasur", 1005, "Jasur", "Tursunov", COURIER, "Employee", "CY", 140, "courier"),
    P("nigora", 1006, "Nigora", "Azimova", PHARMACIST, TILL, "Y", 160, "yns_night_a"),
    # Chilonzor's second pair.
    P("gulnora", 3002, "Gulnora", "Ismoilova", PHARMACIST, TILL, "C", 265, "chl_open_b"),
    P("sardor", 3001, "Sardor", "Rahimov", SENIOR, TILL, "C", 410, "chl_close_b"),
    # Yunusobod: its head, a senior pharmacist on weekdays, two day and two night pharmacists.
    P("farrux", 3007, "Farrux", "Aliyev", HEAD, BRANCH_MANAGER, "Y", 520, "head6"),
    P("malika", 3009, "Malika", "Tosheva", SENIOR, "Employee", "Y", 150, "senior5"),
    P("shahzoda", 3004, "Shahzoda", "Yusupova", PHARMACIST, TILL, "Y", 96, "yns_day_a"),
    P("kamola", 3006, "Kamola", "Ergasheva", PHARMACIST, TILL, "Y", 21, "yns_day_b"),
    P("dilshod", 3008, "Dilshod", "Karimov", PHARMACIST, TILL, "Y", 330, "yns_night_b"),
    # Receiving for both pharmacies, and the accountant in the Chilonzor office.
    P("otabek", 3003, "Otabek", "Nazarov", STOCK, "Employee", "CY", 190, "stock"),
    P("aziza", 3012, "Aziza", "Rasulova", OFFICE, "Accountant", "CY", 610, "office"),
]
CORE = ("owner", "manager", "worker", "madina", "jasur", "nigora")

# People the members demo adds with their own status: a suspension, people who left and join
# requests (one from a former storekeeper).
SUSPENDED = P("bobur", 3013, "Bobur", "Saidov", PHARMACIST, "Employee", "C", 300, "office")
LEFT = P("nodira", 3014, "Nodira", "Xolmatova", PHARMACIST, TILL, "Y", 420, "yns_day_b")
BLOCKED = P("rustam", 3015, "Rustam", "Nurmatov", COURIER, "Employee", "C", 200, None)
RETURNING = P("jahongir", 3018, "Jahongir", "Mirzaev", STOCK, "Employee", "C", 700, None)
REQUESTS = [
    # key, telegram id, first, last, position, hours ago
    ("akmal", 3016, "Akmal", "Jo‘rayev", PHARMACIST, 2),
    ("laylo", 3017, "Laylo", "Hamidova", COURIER, 26),
]
SUSPENSION = (-2, 5, "Retseptli dorilar hisobida kamomad chiqdi, tekshiruv o‘tkazilmoqda")
LEFT_DAYS_AGO = 19  # Nodira resigned; Kamola came two days before her last day
BLOCKED_DAYS_AGO = 64

# Demo Distribyutor, Sergeli. Its demo gets owner, manager, worker and cashier (the sales
# manager, who handles the money buyers pay).
SMALL_PEOPLE = [
    P("owner", 1001, "Dilnoza", "Karimova", OFFICE, "Owner", "S", 400, None),
    P("manager", 2001, "Sardor", "Qodirov", WAREHOUSE_HEAD, "Manager", "S", 400, "warehouse"),
    P("worker", 2002, "Kamola", "Yusupova", STOREKEEPER, "Employee", "S", 290, "warehouse"),
    P("cashier", 2003, "Otabek", "Rahimov", SALES_MANAGER, "Accountant", "S", 180, "sales"),
    P("driver", 2004, "Bahodir", "Islomov", DRIVER, "Employee", "S", 240, "driver"),
]
SMALL_CORE = ("owner", "manager", "worker", "cashier")

PHONES = {
    1001: "+998901110001",
    1002: "+998901110002",
    4242: "+998901234567",
    1004: "+998901110004",
    1005: "+998901110005",
    1006: "+998901110006",
    3001: "+998901112233",
    3002: "+998935557711",
    3003: "+998977001122",
    3004: "+998998887766",
    3006: "+998946662200",
    3007: "+998901234000",
    3008: "+998935550909",
    3009: "+998977773311",
    3012: "+998946543210",
    3013: "+998901118899",
    3014: "+998935554433",
    3015: "+998977008800",
    3016: "+998901239988",
    3017: "+998946001100",
    3018: "+998935001234",
    2001: "+998901120001",
    2002: "+998901120002",
    2003: "+998901120003",
    2004: "+998901120004",
}
USERNAMES = {
    3001: "sardor_r",
    3003: "otabek_n",
    3007: "farrux_aliyev",
    3009: "malika_t",
    3012: "aziza_buxgalter",
    3016: "akmal_j",
}
# Most of the team reads Uzbek; these four prefer Russian (their bot, app and messages follow).
RUSSIAN = {1004, 3004, 3012, 2003}


@dataclass(frozen=True)
class Away:
    """Time off: `first` to `last` are day offsets, asked `asked` days before the seed day."""

    who: str
    first: int
    last: int
    reason: str
    status: str = "approved"  # approved | pending | rejected
    decided_by: str | None = None
    recorded: bool = False  # sick leave the head wrote down afterwards
    asked: int = 3
    cover: str | None = None  # who works the absent person's shifts meanwhile
    revoked_from: int | None = None  # approved, then called off from this day on
    revoke_reason: str = ""


A = Away
MANAGER, OWNER, FARRUX = "manager", "owner", "farrux"
SICK, PENDING, REJECTED = True, "pending", "rejected"
TIME_OFF = [
    # Madina takes her mother to hospital; Sardor works her two evenings.
    A("madina", 0, 1, "Onamni shifoxonaga olib boraman", decided_by=MANAGER, cover="sardor"),
    # Dilshod's brother's wedding; Nigora works his two nights.
    A("dilshod", -3, 1, "Ukamning to‘yi, Samarqand", decided_by=FARRUX, asked=9, cover="nigora"),
    # Alisher opens Chilonzor on Gulnora's days while she is on holiday.
    A("gulnora", -12, -8, "Yillik ta’til", decided_by=MANAGER, asked=20, cover="worker"),
    A("otabek", -6, -4, "Kasallik varaqasi (shamollash)", decided_by=MANAGER, recorded=SICK),
    # Nigora is ill; Dilshod works her two nights.
    A("nigora", -16, -15, "Angina", decided_by=FARRUX, recorded=SICK, cover="dilshod"),
    A("shahzoda", 4, 6, "Ta’til", decided_by=FARRUX, asked=6),
    A("aziza", 10, 16, "Yillik ta’til", decided_by=OWNER, asked=12),
    A("worker", 7, 8, "Singlimning to‘yi", status=PENDING, asked=1),
    A("kamola", 3, 3, "Shifokor qabuli", status=PENDING, asked=0),
    A("malika", 18, 21, "Toshkentdan tashqariga safar", status=PENDING, asked=0),
    A("sardor", 2, 4, "Dam olish", status=REJECTED, decided_by=MANAGER, asked=5),
    A("jasur", 9, 10, "Do‘stimning to‘yi", status=REJECTED, decided_by=MANAGER, asked=3),
]
SMALL_TIME_OFF = [
    A("worker", -9, -8, "Oilaviy sabab", decided_by=MANAGER, asked=12),
    A("cashier", 9, 9, "Universitetda imtihon", status=PENDING, asked=1),
]
# Farrux's three days off end on Yunusobod's stock count: the owner calls the last one off.
REVOKE_REASON = "Shanba kuni Yunusobodda inventarizatsiya, Farrux kerak"


@dataclass(frozen=True)
class Swap:
    """`cover` worked `who`'s shift on day `day` (approved by the head beforehand)."""

    who: str
    cover: str
    day: int
    note: str


SWAPS = [Swap("nigora", "dilshod", -8, "Oilaviy sabab")]

# The distributor's warehouse closes on public holidays; the pharmacies never do.
PUBLIC_HOLIDAYS = {
    (1, 1): "Yangi yil",
    (3, 8): "Xalqaro xotin-qizlar kuni",
    (3, 21): "Navro‘z bayrami",
    (5, 9): "Xotira va qadrlash kuni",
    (9, 1): "Mustaqillik kuni",
    (10, 1): "O‘qituvchi va murabbiylar kuni",
    (12, 8): "Konstitutsiya kuni",
}
LUNAR_HOLIDAYS = {date(2026, 3, 20): "Ramazon hayiti", date(2026, 5, 27): "Qurbon hayiti"}

# Routines the core demo starts (so the bot has work without any app's demo) and the tasks
# demo then fills out with branches, checklists, proof and two months of history.
HANDOVER = "Smenani qabul qilish: tekshiruv ro‘yxati"
TELEGRAM_ORDERS = "Telegramdagi buyurtmalarga javob berish"
CASH_REPORT = "Kassa hisoboti va Z-hisobot"
DELIVERIES = "Buyurtmalarni yetkazish"
FRIDGE_MORNING = "Muzlatgich harorati: ertalabki ko‘rsatkich"
FRIDGE_EVENING = "Muzlatgich harorati: kechki ko‘rsatkich"
RECEIVING = "Kirim (nakladnoy): distribyutordan dori qabul qilish"


@dataclass(frozen=True)
class Shift:
    key: str
    day: date
    starts: datetime
    ends: datetime
    break_minutes: int
    branch: str  # code letter
    rota: str
    cover_for: str | None = None

    @property
    def night(self) -> bool:
        return self.ends.date() > self.day


class Plan:
    """The story as one company sees it: `Plan(company, people, now)`.

    `people` is what the demo got (the six of rule 22, or the distributor's four); everyone else
    in the tables is found in the company by Telegram id (they're missing in a module's own
    tests)."""

    def __init__(self, company, people: dict, now: datetime):
        self.company = company
        self.zone = ZoneInfo(company.timezone)
        self.now = now
        self.today = timezone.localtime(now, self.zone).date()
        self.small = company.slug == DISTRIBUTOR
        cast = SMALL_PEOPLE if self.small else [*PEOPLE, SUSPENDED, LEFT, BLOCKED, RETURNING]
        self.cast = {person.key: person for person in cast}
        self.time_off = list(SMALL_TIME_OFF if self.small else TIME_OFF)
        self.swaps = [] if self.small else list(SWAPS)
        if not self.small:
            last = (self.inventory_day() - self.today).days
            days = {"decided_by": OWNER, "asked": 8, "revoked_from": last}
            self.time_off.append(
                A("farrux", last - 2, last, "Ta’til", revoke_reason=REVOKE_REASON, **days)
            )
        self._people = dict(people)
        self._members: dict | None = None
        branches = list(company.branches.order_by("order", "pk"))
        codes = "S" if self.small else "CY"
        self.branches = {
            code: branches[min(index, len(branches) - 1)] for index, code in enumerate(codes)
        }

    # People ---------------------------------------------------------------------------------

    def members(self) -> dict:
        """Every person of the story who is in the company: key -> Membership."""
        if self._members is None:
            from apps.members.models import Membership

            found = dict(self._people)
            missing = {
                person.telegram_id: key for key, person in self.cast.items() if key not in found
            }
            for member in Membership.objects.filter(
                company=self.company, user__telegram_id__in=list(missing)
            ).select_related("user", "position", "role", "home_branch"):
                found[missing[member.user.telegram_id]] = member
            self._members = found
        return self._members

    def member(self, key: str):
        return self.members().get(key)

    def key_of(self, member) -> str | None:
        for key, found in self.members().items():
            if found.pk == member.pk:
                return key
        return None

    def joined(self, key: str) -> date:
        person = self.cast.get(key)
        return self.day(-person.joined) if person else self.day(-3650)

    def branch(self, key: str):
        person = self.cast.get(key)
        code = person.branches[0] if person else ("S" if self.small else "C")
        return self.branches[code]

    # Days -----------------------------------------------------------------------------------

    def day(self, offset: int) -> date:
        return self.today + timedelta(days=offset)

    def at(self, day: date, clock: time) -> datetime:
        return datetime.combine(day, clock, tzinfo=self.zone)

    def local(self, moment: datetime) -> datetime:
        return timezone.localtime(moment, self.zone)

    def inventory_day(self) -> date:
        """Yunusobod's stock count: the first Saturday at least three days ahead."""
        day = self.day(3)
        return day + timedelta(days=(5 - day.weekday()) % 7)

    def holiday(self, day: date) -> str | None:
        """The name of a day the company closes: the distributor's public holidays."""
        if not self.small:
            return None
        return PUBLIC_HOLIDAYS.get((day.month, day.day)) or LUNAR_HOLIDAYS.get(day)

    # Who works when -----------------------------------------------------------------------

    def leave(self, key: str, day: date) -> Away | None:
        """The approved time off `key` takes on `day` (a revoked day no longer counts)."""
        for row in self.time_off:
            if row.who != key or row.status != "approved":
                continue
            last = row.last if row.revoked_from is None else row.revoked_from - 1
            if self.day(row.first) <= day <= self.day(last):
                return row
        return None

    def away(self, key: str, day: date) -> str | None:
        """Why `key` can't work on `day`: not_joined, holiday, time_off, suspended, left or
        blocked."""
        if key in self.cast and day < self.joined(key):
            return "not_joined"
        if self.holiday(day):
            return "holiday"
        if self.leave(key, day) is not None:
            return "time_off"
        if key == SUSPENDED.key and not self.small:
            first, last, _reason = SUSPENSION
            if self.day(first) <= day <= self.day(last):
                return "suspended"
        if key == LEFT.key and day >= self.day(-LEFT_DAYS_AGO):
            return "left"
        if key == BLOCKED.key and day >= self.day(-BLOCKED_DAYS_AGO):
            return "blocked"
        return None

    def rostered(self, key: str, day: date) -> Shift | None:
        """The shift `key`'s own rota plans on `day`, whether or not they're there."""
        person = self.cast.get(key)
        if person is None or person.rota is None:
            return None
        rota = ROTAS[person.rota]
        if not rota.works_on(day, self.today):
            return None
        return self._shift(key, day, person.rota, person.branches[0])

    def swap(self, day: date) -> Swap | None:
        return next((row for row in self.swaps if self.day(row.day) == day), None)

    def shift(self, key: str, day: date) -> Shift | None:
        """The shift `key` really works on `day`: their own (unless away or given to a
        colleague) or one they cover."""
        if self.away(key, day) is not None:
            return None
        swapped = self.swap(day)
        if swapped is not None and swapped.who == key:
            return None
        own = self.rostered(key, day)
        if own is not None:
            return own
        covered = [
            row.who
            for row in self.time_off
            if row.cover == key and row.status == "approved" and self.leave(row.who, day) is row
        ]
        if swapped is not None and swapped.cover == key:
            covered.append(swapped.who)
        for absent_key in covered:
            absent = self.rostered(absent_key, day)
            if absent is not None:
                return Shift(
                    key,
                    day,
                    absent.starts,
                    absent.ends,
                    absent.break_minutes,
                    absent.branch,
                    absent.rota,
                    cover_for=absent_key,
                )
        return None

    def works(self, key: str, day: date) -> bool:
        """`key` is at work on `day`: they have a shift, or (no rota, like the owner) it's
        Monday to Saturday and they aren't away."""
        person = self.cast.get(key)
        if person is not None and person.rota is None:
            return day.weekday() < 6 and self.away(key, day) is None
        return self.shift(key, day) is not None

    def working(self, day: date, *, branch: str | None = None, counter: bool | None = None):
        """Shifts worked on `day` by people in the company, optionally of one branch or only
        the counter's shifts."""
        shifts = []
        for key in self.cast:
            if key not in self.members():
                continue
            found = self.shift(key, day)
            if found is None or (branch is not None and found.branch != branch):
                continue
            if counter is not None and ROTAS[found.rota].counter != counter:
                continue
            shifts.append(found)
        return shifts

    def till(self, branch: str, day: date, *, night: bool = False):
        """Who opens and who closes the till of `branch` for `day`'s day (or night) session:
        the first at the counter opens it and the last one there closes it. (None, None) when
        nobody works the counter then."""
        shifts = [s for s in self.working(day, branch=branch, counter=True) if s.night == night]
        if not shifts:
            return None, None
        opener = min(shifts, key=lambda s: (s.starts, -s.ends.timestamp(), s.key))
        closer = max(shifts, key=lambda s: (s.ends, -s.starts.timestamp(), s.key))
        return opener, closer

    def next_working_day(self, key: str, after: date, *, within: int = 21) -> date | None:
        for step in range(1, within + 1):
            day = after + timedelta(days=step)
            if self.works(key, day):
                return day
        return None

    def last_working_day(self, key: str, before: date, *, within: int = 21) -> date | None:
        for step in range(1, within + 1):
            day = before - timedelta(days=step)
            if self.works(key, day):
                return day
        return None

    def _shift(self, key, day, rota_key, branch) -> Shift:
        rota = ROTAS[rota_key]
        starts = self.at(day, rota.starts)
        ends = self.at(day, rota.ends)
        if ends <= starts:
            ends = self.at(day + timedelta(days=1), rota.ends)
        return Shift(key, day, starts, ends, rota.break_minutes, branch, rota_key)
