"""Demo data of projects (docs/PLAN-OWNER.md §13.3, §14.3): Demo Dorixona's four projects
with boards, labels, milestones, cards, time on the days people work, updates, links, files, a
running timer and expenses on the ledger.

- "Sergeli dorixonasini ochish" (SRG): a third pharmacy; licence, fit-out and the fridge;
  active and at risk (opening in 6 days, about half done), budget 150 000 000 so‘m.
- "GPP tekshiruviga tayyorgarlik" (GPP): ready for the GPP surveillance visit in three weeks;
  active, on track.
- "IV chorak: to‘liq inventarizatsiya" (INV): both pharmacies counted before the year closes;
  active, getting ready for Yunusobod's count on the story's Saturday (the calendar's event),
  Chilonzor two weeks later.

Cards are started, finished and checked while their people are at work (`_at_work`), never on
a day off or on leave.
- "Diabet haftaligi" (DIA): a week of free blood sugar checks; completed last month.
"""

from __future__ import annotations

import io
import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.files.base import ContentFile
from django.utils import timezone

from apps.core import demo_plan
from apps.projects import queries
from apps.projects.models import (
    Card,
    Label,
    Milestone,
    Project,
    ProjectFile,
    ProjectLink,
    ProjectList,
    ProjectMember,
    ProjectUpdate,
    RunningTimer,
    TaskLabel,
    TimeEntry,
)
from apps.tasks.models import ChecklistItem, Proof, Task, TaskComment

TODO, DOING, REVIEW, DONE = "todo", "doing", "review", "done"
BACKLOG = "backlog"
URGENT = "Shoshilinch"
DOCS = "https://disk.demo-dorixona.example"

# (title, person, list, labels, due offset in days, extra)
SERGELI_CARDS = [
    ("Ijara shartnomasini imzolash", "owner", DONE, ["Hujjatlar"], -38, {}),
    ("Litsenziya uchun hujjatlar ro‘yxatini tuzish", "madina", DONE, ["Litsenziya"], -36, {}),
    ("Binoni o‘lchab, reja chizish", "manager", DONE, [], -35, {}),
    ("Ta’mir pudratchisini tanlash", "manager", DONE, ["Ta’mir"], -31, {}),
    ("Dori shkaflari va javonlarga buyurtma berish", "manager", DONE, ["Uskunalar"], -27, {}),
    ("Eski peshtaxtani olib tashlash", "jasur", DONE, ["Ta’mir"], -26, {}),
    ("Elektr simlarini yangilash", "manager", DONE, ["Ta’mir"], -21, {}),
    ("Kassa apparati va terminalga buyurtma", "madina", DONE, ["Uskunalar"], -19, {}),
    ("Provizor va farmatsevt vakansiyasini e’lon qilish", "owner", DONE, ["Xodimlar"], -24, {}),
    ("Nomzodlar bilan suhbat", "manager", DONE, ["Xodimlar"], -14, {}),
    ("Yashil xochli peshlavhaga buyurtma", "nigora", DONE, ["Reklama"], -16, {}),
    ("Bo‘yoq va qurilish mollarini obyektga yetkazish", "jasur", DONE, ["Ta’mir"], -13, {}),
    ("Devor va shiftni bo‘yash", "manager", DONE, ["Ta’mir"], -12, {}),
    ("Konditsioner o‘rnatish (xona 25 °C dan oshmasin)", "manager", DONE, ["Uskunalar"], -9, {}),
    ("Yong‘in xavfsizligi tekshiruvi", "manager", DONE, ["Hujjatlar", URGENT], -6, {}),
    ("Internet va kassa dasturini ulash", "madina", DONE, ["Uskunalar"], -5, {}),
    ("Ochilish e’lonini tayyorlash", "nigora", DONE, ["Reklama"], -3, {}),
    (
        "Pol plitkasi: ustaning ishini qabul qilish",
        "manager",
        REVIEW,
        ["Ta’mir"],
        1,
        {"proof": Proof.PHOTO, "needs_confirmation": True},
    ),
    (
        "Kuzatuv kameralarini o‘rnatish",
        "manager",
        REVIEW,
        ["Uskunalar"],
        2,
        {"needs_confirmation": True},
    ),
    (
        "Farmatsevtik muzlatgichni o‘rnatish va tekshirish",
        "madina",
        DOING,
        ["Uskunalar"],
        2,
        {
            "checklist": [
                ("Muzlatgich keldi", True),
                ("Termometr o‘rnatildi", True),
                ("24 soatlik sinov: +2…+8 °C", False),
            ]
        },
    ),
    ("Litsenziya arizasini topshirish", "owner", DOING, ["Litsenziya", URGENT], -1, {}),
    (
        "Yangi xodimlarni kassa dasturiga o‘rgatish",
        "madina",
        DOING,
        ["Xodimlar"],
        4,
        {"checklist": [("Gulnoza", True), ("Sardorbek", True), ("Shahnoza", False)]},
    ),
    ("Peshlavhani ustaxonadan olib kelish", "jasur", DOING, ["Reklama", URGENT], -1, {}),
    ("Elektr tarmog‘ini yakuniy tekshirish", "manager", DOING, ["Ta’mir"], 2, {}),
    ("Dori shkaflarini joylashtirish rejasi", "worker", DOING, ["Uskunalar"], 3, {}),
    ("Distribyutorlardan birinchi kirim", "manager", TODO, [], 4, {}),
    ("Narx yorliqlarini chop etish", "worker", TODO, [], 5, {}),
    ("Ustalardan keyin tozalash", "jasur", TODO, ["Ta’mir"], 4, {}),
    ("Ochilish kuni: bepul qon bosimi o‘lchash", "nigora", BACKLOG, ["Reklama"], 6, {}),
    ("Qo‘shni uylarga ochilish e’loni", "jasur", BACKLOG, ["Reklama"], 6, {}),
    ("Birinchi hafta smenalarini rejalash", "manager", BACKLOG, ["Xodimlar"], 5, {}),
]

GPP_CARDS = [
    ("Oxirgi tekshiruv dalolatnomasini ko‘rib chiqish", "owner", DONE, ["Hujjatlar"], -30, {}),
    ("GPP talablari bo‘yicha o‘z-o‘zini tekshirish", "madina", DONE, ["Audit"], -28, {}),
    ("Termometr va gigrometrlarni kalibrlash", "manager", DONE, ["Saqlash"], -26, {}),
    ("Harorat jurnallarini yig‘ish (3 oy)", "worker", DONE, ["Saqlash"], -22, {}),
    ("Muzlatgich termometri hisobotini chiqarish", "nigora", DONE, ["Saqlash"], -20, {}),
    ("Xodimlar diplom va sertifikatlari nusxalari", "owner", DONE, ["Hujjatlar"], -19, {}),
    ("Sanitariya jurnalini tartibga solish", "worker", DONE, ["Hujjatlar"], -16, {}),
    ("Retseptlar jurnalini tekshirish", "madina", DONE, ["Audit"], -13, {}),
    ("Hisobdan chiqarish dalolatnomalarini yig‘ish", "manager", DONE, ["Hujjatlar"], -11, {}),
    ("O‘t o‘chirgichlar muddatini tekshirish", "manager", DONE, [], -9, {}),
    ("Xodimlar uchun GPP treningi", "madina", DONE, ["Audit"], -7, {}),
    ("Dezinfeksiya shartnomasini yangilash", "owner", DONE, ["Hujjatlar"], -5, {}),
    ("Omborda qutilarni poldan ko‘tarish (taglik)", "worker", DONE, ["Saqlash"], -4, {}),
    ("SOP: dori qabul qilish tartibi", "madina", REVIEW, ["SOP"], 3, {"needs_confirmation": True}),
    ("SOP: sovuq zanjir", "nigora", REVIEW, ["SOP", "Saqlash"], 4, {"needs_confirmation": True}),
    ("SOP: muddati o‘tgan dorilarni hisobdan chiqarish", "madina", DOING, ["SOP"], 9, {}),
    ("Kamera yozuvlari 30 kun saqlanishini tekshirish", "manager", DOING, ["Audit"], 10, {}),
    ("Yunusobod: ikkinchi muzlatgichga termometr", "nigora", DOING, ["Saqlash", URGENT], 8, {}),
    ("Narx yorliqlarida mas’ul shaxs imzosi", "worker", DOING, [], 12, {}),
    ("Xodimlarning tibbiy daftarchalari", "owner", DOING, ["Hujjatlar"], 14, {}),
    ("Ichki audit: Chilonzor", "madina", TODO, ["Audit"], 15, {}),
    ("Ichki audit: Yunusobod", "nigora", TODO, ["Audit"], 16, {}),
    ("Tekshiruv uchun hujjatlar papkasi", "owner", TODO, ["Hujjatlar"], 18, {}),
    ("Majburiy assortiment ro‘yxatini tekshirish", "worker", TODO, ["Audit"], 17, {}),
    ("Nazoratdagi dorilar kitobini tekshirish", "madina", TODO, ["Audit"], 19, {}),
    ("Dorixona ichidagi yo‘l ko‘rsatkichlar", "manager", TODO, [], 20, {}),
    ("Tekshiruvdan keyingi kamchiliklar rejasi", "madina", BACKLOG, ["Audit"], 24, {}),
    ("Kalibrlash jadvalini kalendarga qo‘shish", "manager", BACKLOG, ["Saqlash"], 25, {}),
    ("Yangi xodimlar uchun GPP yo‘riqnomasi", "madina", BACKLOG, ["SOP"], 26, {}),
    ("Mijozlar fikri qutisi", "nigora", BACKLOG, [], 28, {}),
]

COUNT_AREAS = [
    "Chilonzor: antibiotiklar",
    "Chilonzor: og‘riq qoldiruvchi va isitma tushiruvchilar",
    "Chilonzor: yurak-qon tomir dorilari",
    "Chilonzor: vitaminlar",
    "Chilonzor: tibbiy buyumlar",
    "Chilonzor: muzlatgich",
    "Chilonzor: retseptli dorilar shkafi",
    "Yunusobod: antibiotiklar",
    "Yunusobod: og‘riq qoldiruvchilar",
    "Yunusobod: nazoratdagi dorilar seyfi",
    "Yunusobod: muzlatgichlar",
    "Yunusobod: gigiyena va chaqaloqlar uchun",
    "Yunusobod: ombor",
    "muddati o‘tgan va qaytariladigan dorilar",
]

DIABETES_CARDS = [
    ("Bepul qand o‘lchash uchun glyukometr tayyorlash", "madina", ["Tadbir"]),
    ("Test-chiziqlarga buyurtma", "manager", []),
    ("Plakat va varaqalar dizayni", "nigora", ["Dizayn"]),
    ("Plakatlarni chop etish", "nigora", ["Dizayn"]),
    ("Glyukometr va test-chiziq zaxirasini tekshirish", "worker", []),
    ("Farmatsevtlarga yo‘riqnoma: maslahat chegaralari", "madina", ["Tadbir"]),
    ("Ijtimoiy tarmoqlarda e’lon", "nigora", ["Dizayn"]),
    ("Haftalik o‘lchash jadvali", "manager", ["Tadbir"]),
    ("Endokrinolog bilan kelishuv (ma’ruza)", "owner", ["Tadbir"]),
    ("Natijalarni sanash", "worker", []),
    ("Hisobot: qatnashchilar soni", "owner", []),
    ("Qolgan test-chiziqlarni omborga qaytarish", "worker", []),
]

COMMENTS = [
    "Qalay ketyapti? Mendan biror narsa kerakmi?",
    "Distribyutor payshanbaga yetkazishni tasdiqladi.",
    "Tugagach, suratini yuboring.",
    "Yaxshi, ertaga ertalab tekshiraman.",
    "Usta yana ikki kun so‘radi.",
]


def seed(company, people, now) -> None:
    story = demo_plan.Plan(company, people, now)
    rng = random.Random(911)
    tz = ZoneInfo(company.timezone)
    today = story.today
    owner, manager = people["owner"], people["manager"]
    chilonzor = story.branches["C"]
    # The rule-22 people and, when the company has them, Yunusobod's head and senior pharmacist.
    crew = dict(people) | {
        key: story.member(key) for key in ("farrux", "malika") if story.member(key) is not None
    }

    sergeli = _project(
        company,
        people,
        name="Sergeli dorixonasini ochish",
        key="SRG",
        color="chart-1",
        icon="store",
        description=(
            "Uchinchi dorixonamiz: Sergeli, Yangi Sergeli ko‘chasi 18. Litsenziya, ta’mir, "
            "farmatsevtik muzlatgich, ikki farmatsevt va bitta provizor, ochilish kuni esa "
            "**bepul qon bosimi o‘lchash**.\n\n- Ta’mir: pudratchi bilan shartnoma\n"
            "- Shkaflar: mebel ustaxonasi\n- Peshlavha: yashil xoch, kechasi yonadi"
        ),
        status=Project.Status.ACTIVE,
        priority=Project.Priority.HIGH,
        lead=manager,
        branch=chilonzor,
        start_on=today - timedelta(days=40),
        due_on=today + timedelta(days=6),
        budget=Decimal("150000000"),
        visibility=Project.Visibility.MEMBERS,
        members=["owner", "worker", "madina", "jasur", "nigora"],
        labels=[
            ("Ta’mir", "chart-2"),
            ("Uskunalar", "chart-3"),
            ("Xodimlar", "chart-6"),
            ("Reklama", "chart-4"),
            ("Litsenziya", "chart-5"),
            ("Hujjatlar", "chart-5"),
            (URGENT, "chart-1"),
        ],
        milestones=[
            ("Ijara shartnomasi", -38, True),
            ("Ta’mir tugadi", 2, False),
            ("Litsenziya olindi", 4, False),
            ("Ochilish", 6, False),
        ],
        now=now,
    )
    _cards(
        sergeli, crew, SERGELI_CARDS, today=today, tz=tz, now=now, rng=rng, start=-42, story=story
    )
    gpp = _project(
        company,
        people,
        name="GPP tekshiruviga tayyorgarlik",
        key="GPP",
        color="chart-3",
        icon="shield-check",
        description=(
            "Uch haftadan keyin GPP sertifikati bo‘yicha kuzatuv tashrifi. Saqlash sharoitlari, "
            "jurnallar, SOPlar va xodimlar hujjatlari tayyor bo‘lishi kerak."
        ),
        status=Project.Status.ACTIVE,
        priority=Project.Priority.NORMAL,
        lead=people["madina"],
        branch=None,
        start_on=today - timedelta(days=32),
        due_on=today + timedelta(days=21),
        budget=Decimal("12000000"),
        visibility=Project.Visibility.COMPANY,
        members=["owner", "manager", "worker", "nigora"],
        labels=[
            ("Saqlash", "chart-2"),
            ("Hujjatlar", "chart-5"),
            ("SOP", "chart-3"),
            ("Audit", "chart-6"),
            (URGENT, "chart-1"),
        ],
        milestones=[
            ("O‘z-o‘zini tekshirish", -28, True),
            ("SOPlar tayyor", 10, False),
            ("Ichki audit", 16, False),
            ("Kuzatuv tashrifi", 21, False),
        ],
        now=now,
    )
    _cards(gpp, crew, GPP_CARDS, today=today, tz=tz, now=now, rng=rng, start=-32, story=story)
    # Yunusobod is counted on the story's stock-count Saturday (the calendar's event, the
    # extra shifts and the head's revoked day off), Chilonzor two weeks later.
    counted = (story.inventory_day() - today).days
    count = _project(
        company,
        crew,
        name="IV chorak: to‘liq inventarizatsiya",
        key="INV",
        color="chart-6",
        icon="clipboard-list",
        description=(
            "Yil yopilishidan oldin ikkala dorixonani to‘liq sanash, seriya va yaroqlilik "
            "muddatlari bilan: avval Yunusobod (dorixona ishlashda davom etadi, sanash "
            "ombordan boshlanadi), ikki haftadan keyin Chilonzor. Keyin hisob dasturi va "
            "buxgalteriya bilan solishtirish."
        ),
        status=Project.Status.ACTIVE,
        priority=Project.Priority.NORMAL,
        lead=manager,
        branch=None,
        start_on=today - timedelta(days=8),
        due_on=today + timedelta(days=45),
        budget=Decimal("6000000"),
        visibility=Project.Visibility.MEMBERS,
        members=[key for key in ("worker", "madina", "nigora", "farrux", "malika") if key in crew],
        labels=[("Sanash", "chart-2"), ("Ombor", "chart-3"), ("Solishtirish", "chart-4")],
        milestones=[
            ("Sanash rejasi kelishildi", -3, True),
            ("Yunusobod sanaldi", counted, False),
            ("Chilonzor sanaldi", counted + 14, False),
            ("Buxgalteriya bilan solishtirildi", 45, False),
        ],
        now=now,
    )
    _cards(
        count,
        crew,
        _count_cards(counted, crew),
        today=today,
        tz=tz,
        now=now,
        rng=rng,
        start=-8,
        story=story,
    )
    diabetes = _project(
        company,
        people,
        name="Diabet haftaligi",
        key="DIA",
        color="chart-4",
        icon="heart-pulse",
        description=(
            "Ikkala dorixonada bir hafta bepul qand o‘lchash va endokrinolog ma’ruzasi. "
            "Yakunlandi: 316 kishi qatnashdi."
        ),
        status=Project.Status.COMPLETED,
        priority=Project.Priority.NORMAL,
        lead=owner,
        branch=None,
        start_on=today - timedelta(days=50),
        due_on=today - timedelta(days=30),
        budget=Decimal("5000000"),
        visibility=Project.Visibility.COMPANY,
        members=["manager", "madina", "worker", "nigora"],
        labels=[("Tadbir", "chart-4"), ("Dizayn", "chart-5")],
        milestones=[("Tadbir boshlandi", -37, True), ("Hisobot", -30, True)],
        now=now,
    )
    diabetes_cards = [
        (title, who, DONE, labels, -48 + i * 2, {})
        for i, (title, who, labels) in enumerate(DIABETES_CARDS)
    ]
    _cards(
        diabetes,
        crew,
        diabetes_cards,
        today=today,
        tz=tz,
        now=now,
        rng=rng,
        start=-50,
        story=story,
    )
    Project.objects.filter(pk=diabetes.pk).update(completed_at=now - timedelta(days=30))

    _updates(sergeli, gpp, diabetes, people, now)
    _time(company, story, [sergeli, gpp], people, rng=rng)
    _links(sergeli, gpp, people)
    _files(sergeli, people, now)
    _expenses(company, sergeli, gpp, diabetes, owner, today=today)
    timer_card = Task.objects.filter(project=sergeli, assignee=people["worker"]).first()
    shift = story.shift("worker", today)
    if timer_card is not None and shift is not None and shift.starts + timedelta(hours=1) < now:
        # Alisher is at work and timing his card right now.
        RunningTimer.objects.create(
            company=company,
            membership=people["worker"],
            task=timer_card,
            project=sergeli,
            started_at=max(shift.starts + timedelta(minutes=30), now - timedelta(minutes=47)),
        )
    for project in (sergeli, gpp, count, diabetes):
        Project.objects.filter(pk=project.pk).update(
            health=queries.health_of(project, now=now) or ""
        )


def _project(company, people, *, members, labels, milestones, now, **fields) -> Project:
    project = Project.objects.create(
        company=company, created_by=people["owner"], budget_currency="UZS", **fields
    )
    Project.objects.filter(pk=project.pk).update(created_at=now - timedelta(days=45))
    names = ["Navbatda", "Bajarish kerak", "Jarayonda", "Tekshiruvda", "Tayyor"]
    wip = {"Jarayonda": 6, "Tekshiruvda": 3}
    for index, name in enumerate(names):
        ProjectList.objects.create(
            project=project,
            name=name,
            position=(index + 1) * 1024,
            is_done=name == "Tayyor",
            wip_limit=wip.get(name),
        )
    ProjectMember.objects.create(
        project=project, membership=project.lead, role=ProjectMember.Role.LEAD
    )
    for key in members:
        if people[key].pk != project.lead_id:
            ProjectMember.objects.create(
                project=project, membership=people[key], role=ProjectMember.Role.MEMBER
            )
    for index, (name, color) in enumerate(labels):
        Label.objects.create(project=project, name=name, color=color, position=(index + 1) * 1024)
    today = timezone.localtime(now, ZoneInfo(company.timezone)).date()
    for index, (name, offset, done) in enumerate(milestones):
        Milestone.objects.create(
            project=project,
            name=name,
            due_on=today + timedelta(days=offset),
            status=Milestone.Status.DONE if done else Milestone.Status.OPEN,
            completed_at=now + timedelta(days=offset) if done else None,
            position=(index + 1) * 1024,
        )
    return project


def _count_cards(counted: int, crew: dict) -> list[tuple]:
    """The stock count's cards: getting ready before Yunusobod's Saturday (`counted` days
    ahead), its areas that day, Chilonzor's two weeks later, then the reconciliation."""

    def who(key):
        return key if key in crew else "manager"

    cards = [
        ("Sanash sanalarini hisobchi bilan kelishish", "manager", DONE, ["Solishtirish"], -4, {}),
        (
            "Hisob dasturidan qoldiqlar ro‘yxatini chiqarish",
            "madina",
            DONE,
            ["Solishtirish"],
            -2,
            {},
        ),
        ("Sanash kunlarining smenalarini rejalash", who("farrux"), DOING, ["Sanash"], 1, {}),
        ("Distribyutordan ikkita skaner so‘rash", "manager", DOING, ["Ombor"], 1, {}),
        (
            "Shtrix-kodli sanash varaqalarini chop etish",
            "worker",
            DOING,
            ["Sanash"],
            counted - 1,
            {},
        ),
        ("Sanash kuni kirimni to‘xtatish", who("farrux"), TODO, ["Ombor"], counted - 1, {}),
        ("Sanash guruhlariga yo‘riqnoma", "madina", TODO, ["Sanash"], counted - 1, {}),
        ("Har bir javonga joy kodini yopishtirish", "worker", TODO, ["Ombor"], counted + 7, {}),
    ]
    yunusobod = [who(key) for key in ("nigora", "farrux", "malika", "manager")]
    chilonzor = ["worker", "madina", "manager"]
    for index, area in enumerate(area for area in COUNT_AREAS if area.startswith("Yunusobod")):
        cards.append((f"Sanash: {area}", yunusobod[index % 4], TODO, ["Sanash"], counted, {}))
    for index, area in enumerate(area for area in COUNT_AREAS if area.startswith("Chilonzor")):
        cards.append(
            (f"Sanash: {area}", chilonzor[index % 3], BACKLOG, ["Sanash"], counted + 14, {})
        )
    cards += [
        (
            "Sanash: muddati o‘tgan va qaytariladigan dorilar",
            "madina",
            BACKLOG,
            ["Sanash"],
            counted + 15,
            {},
        ),
        ("2 % dan ortiq farqli dorilarni qayta sanash", "madina", BACKLOG, ["Sanash"], 38, {}),
        (
            "Muddati o‘tgan dorilarni hisobdan chiqarish",
            "manager",
            BACKLOG,
            ["Solishtirish"],
            40,
            {},
        ),
        ("Farqlarni buxgalteriyaga topshirish", "madina", BACKLOG, ["Solishtirish"], 42, {}),
        ("Dilnoza uchun inventarizatsiya hisoboti", "manager", BACKLOG, ["Solishtirish"], 44, {}),
        ("Keyingi yil uchun xulosalar", "manager", BACKLOG, [], 45, {}),
        ("Sanash varaqalarini arxivlash", "worker", BACKLOG, [], 45, {}),
        ("Minimal qoldiqlarni yangilash", "madina", BACKLOG, ["Ombor"], 45, {}),
        ("Sanovchilarga rahmatnoma va mukofot", "manager", BACKLOG, [], 45, {}),
    ]
    return cards


def _due(today: date, offset: int, tz: ZoneInfo, rng: random.Random) -> datetime:
    hour = rng.choice((10, 12, 15, 17, 18))
    return datetime.combine(today + timedelta(days=offset), time(hour, 0), tzinfo=tz)


def _at_work(story, member, moment: datetime, now: datetime) -> datetime:
    """The latest time at or before `moment` (and before `now`) when `member` was at work: in
    one of their shifts (half an hour after it starts at the earliest), or in office hours on a
    day they work for people without shifts; never on a day off, on leave or before joining."""
    moment = min(moment, now - timedelta(minutes=20))
    key = story.key_of(member)
    if key is None:
        return moment
    day = story.local(moment).date()
    for _ in range(40):
        if story.works(key, day):
            shift = story.shift(key, day)
            if shift is None:
                first, last = story.at(day, time(9, 30)), story.at(day, time(18, 0))
            else:
                first, last = shift.starts + timedelta(minutes=30), shift.ends
            if moment >= first:
                return min(moment, last - timedelta(minutes=20))
        day -= timedelta(days=1)
    return moment


def _cards(project: Project, people, rows, *, today, tz, now, rng, start: int, story) -> None:
    """The project's cards, each worked on, finished and checked while the people concerned
    were at work (`_at_work`)."""
    lists = list(project.lists.order_by("position"))
    by_status = dict(zip((BACKLOG, TODO, DOING, REVIEW, DONE), lists, strict=True))
    labels = {label.name: label for label in project.labels.all()}
    milestones = list(project.milestones.order_by("due_on"))
    positions: dict[int, float] = {}
    for number, (title, who, column, label_names, offset, extra) in enumerate(rows, start=1):
        assignee = people[who]
        status = {
            DONE: Task.Status.DONE,
            REVIEW: Task.Status.REVIEW,
            DOING: Task.Status.IN_PROGRESS,
        }.get(column, Task.Status.TODO)
        due_at = _due(today, offset, tz, rng)
        project_list = by_status[column]
        positions[project_list.pk] = positions.get(project_list.pk, 0) + 1024
        created = now + timedelta(days=start + rng.randint(0, 4), hours=rng.randint(-3, 3))
        if created > due_at:
            created = due_at - timedelta(days=rng.randint(2, 6))
        created = _at_work(story, project.lead, created, now)
        started = completed = confirmed = None
        if status != Task.Status.TODO:
            started = max(_at_work(story, assignee, created + timedelta(hours=2), now), created)
        if status in (Task.Status.DONE, Task.Status.REVIEW):
            finished = due_at - timedelta(hours=rng.randint(2, 30))
            completed = max(_at_work(story, assignee, finished, now), started)
        if status == Task.Status.DONE and extra.get("needs_confirmation"):
            checked = due_at - timedelta(hours=1)
            confirmed = max(_at_work(story, project.lead, checked, now), completed)
        milestone = next((m for m in milestones if m.due_on and m.due_on >= due_at.date()), None)
        task = Task.objects.create(
            company=project.company,
            kind=Task.Kind.ASSIGNED,
            title=title,
            description=extra.get("description", ""),
            assignee=assignee,
            created_by=project.lead,
            branch=assignee.home_branch,
            status=status,
            priority=Task.Priority.HIGH if URGENT in label_names else Task.Priority.NORMAL,
            due_at=due_at,
            proof=extra.get("proof", Proof.NONE),
            needs_confirmation=extra.get("needs_confirmation", False),
            started_at=started,
            completed_at=completed,
            confirmed_at=confirmed,
            project=project,
            project_list=project_list,
            milestone=milestone,
            list_position=positions[project_list.pk],
        )
        Task.objects.filter(pk=task.pk).update(
            created_at=created,
            project_list=project_list,
            list_position=positions[project_list.pk],
        )
        start_on = (due_at - timedelta(days=rng.randint(2, 6))).date()
        Card.objects.update_or_create(
            task=task,
            defaults={
                "project": project,
                "number": number,
                "start_on": max(start_on, created.date()),
            },
        )
        TaskLabel.objects.bulk_create(
            TaskLabel(task=task, label=labels[name]) for name in label_names
        )
        for order, (text, done) in enumerate(extra.get("checklist", [])):
            ChecklistItem.objects.create(task=task, text=text, is_done=done, order=order)
        if extra.get("proof") == Proof.PHOTO and status in (Task.Status.REVIEW, Task.Status.DONE):
            _proof_photo(task)
        if column in (DOING, REVIEW) and rng.random() < 0.5:
            comment = TaskComment.objects.create(
                task=task, author=project.lead, text=rng.choice(COMMENTS)
            )
            said = min(now - timedelta(hours=1), created + timedelta(days=1))
            TaskComment.objects.filter(pk=comment.pk).update(
                created_at=max(_at_work(story, project.lead, said, now), created)
            )


def _proof_photo(task: Task) -> None:
    """A tiled-floor picture as the card's proof photo."""
    from PIL import Image, ImageDraw

    from apps.core import uploads

    rng = random.Random(task.pk)
    image = Image.new("RGB", (800, 600), (176, 168, 156))  # grout
    draw = ImageDraw.Draw(image)
    for x in range(0, 800, 120):
        for y in range(0, 600, 120):
            light = int(18 * (1 - y / 600)) + rng.randint(-6, 6)  # brighter towards the window
            base = (226 + light, 228 + light, 224 + light)
            draw.rectangle((x + 4, y + 4, x + 116, y + 116), fill=tuple(min(255, c) for c in base))
            draw.line((x + 10, y + 12, x + 60, y + 12), fill=(240, 242, 238), width=2)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    clean = uploads.sanitize_image(buffer.getvalue())
    task.proof_photo.save(clean.name, clean, save=False)
    Task.objects.filter(pk=task.pk).update(proof_photo=task.proof_photo.name)


def _updates(sergeli, gpp, diabetes, people, now) -> None:
    rows = [
        (
            sergeli,
            people["manager"],
            "on_track",
            "Ta’mir o‘z vaqtida boshlandi. Dori shkaflari buyurtma qilindi, usta har kuni keladi.",
            20,
        ),
        (
            sergeli,
            people["manager"],
            "on_track",
            "Elektr va bo‘yoq ishlari tugadi. Konditsioner o‘rnatildi, internet ulandi.",
            9,
        ),
        (
            sergeli,
            people["manager"],
            "at_risk",
            "Plitka uch kun kechikdi, peshlavha hali o‘rnatilmagan, litsenziya arizasi esa "
            "topshirilmagan. Ochilish elektr tarmog‘ining yakuniy tekshiruviga bog‘liq.",
            1,
        ),
        (
            gpp,
            people["madina"],
            "on_track",
            "O‘z-o‘zini tekshirish tugadi: 42 banddan 37 tasi joyida. Qolgani SOP va jurnallar.",
            12,
        ),
        (
            gpp,
            people["madina"],
            "on_track",
            "Termometrlar kalibrlandi, harorat jurnallari yig‘ildi. Ikki SOP tekshiruvda.",
            2,
        ),
        (
            diabetes,
            people["owner"],
            "on_track",
            "Hafta yakunlandi: 316 kishining qandi bepul o‘lchandi, 48 kishi shifokorga "
            "yo‘naltirildi. 5 mln dan 4,8 mln sarflandi.",
            30,
        ),
    ]
    tz = ZoneInfo(sergeli.company.timezone)
    today = timezone.localtime(now, tz).date()
    for index, (project, author, health, text, days_ago) in enumerate(rows):
        update = ProjectUpdate.objects.create(
            project=project, author=author, health=health, text=text
        )
        # Leads write them at the end of the day, a little before 18:00 company time.
        at = datetime.combine(
            today - timedelta(days=days_ago), time(17, 40 + (index * 13) % 20), tzinfo=tz
        )
        ProjectUpdate.objects.filter(pk=update.pk).update(created_at=min(at, now))


def _time(company, story, projects, people, *, rng) -> None:
    """Time logged over the last week and a half, on the days each person works."""
    today = story.today
    start = today - timedelta(days=today.weekday() + 7)  # last week's Monday
    work = {
        projects[0].pk: ["manager", "worker", "jasur", "madina", "nigora"],
        projects[1].pk: ["owner", "madina", "worker", "nigora"],
    }
    tz = ZoneInfo(company.timezone)
    cards = {
        project.pk: list(
            Task.objects.filter(project=project)
            .exclude(status=Task.Status.TODO)
            .select_related("card")
        )
        for project in projects
    }

    def worked_on(task: Task, day: date) -> bool:
        """Was the card being worked on that day: started and not yet finished."""
        begun = task.card.start_on if getattr(task, "card", None) else None
        if begun is not None and day < begun:
            return False
        if task.completed_at is None:
            return True
        return day <= timezone.localtime(task.completed_at, tz).date()

    entries = []
    day = start
    while day <= today:
        for project in projects:
            for who in work[project.pk]:
                if not story.works(who, day):
                    continue
                member = people[who]
                active = [t for t in cards[project.pk] if worked_on(t, day)]
                options = [t for t in active if t.assignee_id == member.pk]
                for _ in range(rng.choice((1, 1, 2))):
                    # Without a card of their own in progress, the time is on the project.
                    task = rng.choice(options) if options else None
                    entries.append(
                        TimeEntry(
                            company=company,
                            membership=member,
                            project=project,
                            task=task,
                            day=day,
                            minutes=rng.choice((30, 45, 60, 90, 120)),
                            note=rng.choice(("", "", "Obyektda", "Qo‘ng‘iroqlar", "Hujjatlar")),
                            source=rng.choice((TimeEntry.Source.MANUAL, TimeEntry.Source.TIMER)),
                            created_by=member,
                        )
                    )
        day += timedelta(days=1)
    TimeEntry.objects.bulk_create(entries)


def _links(sergeli, gpp, people) -> None:
    for project, title, url, who in (
        (sergeli, "Pol rejasi (PDF)", f"{DOCS}/sergeli/pol-rejasi.pdf", "manager"),
        (sergeli, "Ijara shartnomasi", f"{DOCS}/sergeli/ijara.pdf", "owner"),
        (sergeli, "Litsenziya arizasi holati", f"{DOCS}/sergeli/litsenziya", "madina"),
        (gpp, "GPP talablari ro‘yxati", f"{DOCS}/gpp/talablar.pdf", "madina"),
        (gpp, "Harorat jurnallari (3 oy)", f"{DOCS}/gpp/harorat.xlsx", "worker"),
    ):
        ProjectLink.objects.create(project=project, title=title, url=url, added_by=people[who])


def _files(sergeli, people, now) -> None:
    """A storefront mockup picture, drawn here (no files ship with the demo), and documents."""
    from PIL import Image, ImageDraw

    from apps.core import uploads

    image = Image.new("RGB", (960, 600), (244, 247, 245))
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 120, 880, 520), fill=(255, 255, 255), outline=(46, 125, 107), width=6)
    draw.rectangle((80, 120, 880, 200), fill=(46, 125, 107))
    draw.rectangle((450, 135, 510, 185), fill=(255, 255, 255))  # a green cross
    draw.rectangle((465, 140, 495, 180), fill=(46, 125, 107))
    draw.rectangle((455, 150, 505, 170), fill=(46, 125, 107))
    draw.rectangle((180, 260, 420, 520), fill=(232, 240, 236), outline=(95, 122, 69), width=4)
    draw.rectangle((520, 260, 780, 420), fill=(232, 240, 236), outline=(74, 106, 138), width=4)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    clean = uploads.accept_document(ContentFile(buffer.getvalue()), allowed=("image",))
    _file(sergeli, "Peshlavha maketi.jpg", clean, "image", people["nigora"], now, days_ago=17)
    lease = uploads.accept_document(ContentFile(_pdf("Ijara shartnomasi: Sergeli")))
    _file(sergeli, "Ijara shartnomasi.pdf", lease, "pdf", people["owner"], now, days_ago=39)
    plan = uploads.accept_document(ContentFile(_pdf("Ta'mir rejasi va jadvali")))
    _file(sergeli, "Ta’mir rejasi.pdf", plan, "pdf", people["manager"], now, days_ago=33)
    budget = "Xarajat,Kimga,Summa (so‘m)\n" + "\n".join(
        f"{item},{who},{amount}"
        for item, who, amount in (
            ("Ta’mir: buzish va devorlar", "Ta’mir pudratchisi", 19500000),
            ("Elektr va suvoq", "Ta’mir pudratchisi", 12600000),
            ("Dori shkaflari va javonlar", "Mebel ustaxonasi", 21400000),
            ("Farmatsevtik muzlatgich", "Tibbiy uskunalar do‘koni", 13900000),
            ("Yashil xochli peshlavha", "Reklama ustaxonasi", 5200000),
            ("Pol plitkasi", "Qurilish mollari do‘koni", 4800000),
        )
    )
    sheet = uploads.accept_document(ContentFile(budget.encode()), allowed=("csv",))
    _file(sergeli, "Byudjet.csv", sheet, "csv", people["manager"], now, days_ago=26)


def _file(project, name, clean, kind, who, now, *, days_ago: int) -> None:
    row = ProjectFile(project=project, name=name, kind=kind, size=clean.size, uploaded_by=who)
    row.file.save(clean.name, clean, save=False)
    row.save()
    ProjectFile.objects.filter(pk=row.pk).update(
        created_at=now - timedelta(days=days_ago, hours=days_ago % 5)
    )


def _pdf(title: str) -> bytes:
    """A one-page PDF with a title line (valid enough for any viewer)."""
    text = title.replace("\\", "").replace("(", "").replace(")", "")
    stream = f"BT /F1 20 Tf 72 760 Td ({text}) Tj ET".encode("latin-1", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def _expenses(company, sergeli, gpp, diabetes, owner, *, today: date) -> None:
    """The owner puts money for the new pharmacy into the bank; the projects' expenses are
    booked on it."""
    from apps.finance import services as finance
    from apps.finance.models import Category, MoneyAccount

    if not Category.objects.filter(company=company, system_code="repairs").exists():
        return  # the finance defaults aren't there (finance switched off in this demo)
    account = (
        MoneyAccount.objects.filter(company=company, kind=MoneyAccount.Kind.BANK, is_active=True)
        .order_by("order", "pk")
        .first()
    )
    if account is None:
        account = finance.create_account(company, by=owner, kind="bank", name="Asosiy bank hisobi")
    equipment = (
        Category.objects.filter(company=company, name="Uskunalar").first() or "other_expense"
    )
    licences = (
        Category.objects.filter(company=company, name="Litsenziya va ruxsatnomalar").first()
        or "taxes"
    )
    finance.record_transaction(
        company,
        by=owner,
        kind="owner",
        amount=Decimal("150000000"),
        account=account,
        occurred_on=today - timedelta(days=50),
        description="Ta’sischi Sergeli dorixonasi va tadbirlar uchun mablag‘ kiritdi",
    )
    rows = [
        (sergeli, "other_expense", "18000000", -37, "Sergeli: ijara depoziti, 2 oy"),
        (sergeli, "repairs", "19500000", -30, "Ta’mir pudratchisi: buzish va devorlar"),
        (sergeli, "repairs", "12600000", -22, "Ta’mir pudratchisi: elektr va suvoq"),
        (sergeli, equipment, "21400000", -24, "Mebel ustaxonasi: dori shkaflari va javonlar"),
        (sergeli, equipment, "13900000", -11, "Farmatsevtik muzlatgich, +2…+8 °C"),
        (sergeli, equipment, "4600000", -17, "Kassa apparati va terminal"),
        (sergeli, "marketing", "5200000", -14, "Yashil xochli peshlavha"),
        (sergeli, "repairs", "4800000", -8, "Pol plitkasi va yelim"),
        (sergeli, licences, "3400000", -4, "Litsenziya arizasi: davlat boji"),
        (gpp, "other_expense", "1200000", -26, "Termometr va gigrometrlarni kalibrlash"),
        (gpp, equipment, "3800000", -15, "Harorat yozib boradigan qurilma (data logger)"),
        (gpp, "other_expense", "2500000", -7, "Xodimlar uchun GPP treningi"),
        (diabetes, "other_expense", "2200000", -47, "Bepul o‘lchash uchun test-chiziqlar"),
        (diabetes, "marketing", "1100000", -45, "Plakat va varaqalar"),
        (diabetes, "marketing", "1500000", -42, "Ijtimoiy tarmoqlarda e’lon"),
    ]
    for project, category, amount, offset, description in rows:
        finance.record_transaction(
            company,
            by=owner,
            kind="expense",
            amount=Decimal(amount),
            account=account,
            category=category,
            occurred_on=today + timedelta(days=offset),
            description=description,
            project=project,
        )
