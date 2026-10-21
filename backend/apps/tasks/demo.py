"""Demo data of the task pages (apps/core/demo_plan.py): Demo Dorixona's routines (shift
handovers, fridge readings twice a day, receiving from distributors, expiry checks, price tags,
defektura, cleaning, the till) with two months of history on the days each person works,
onboarding templates, reminder policies with Uzbek texts, today's work in every state (waiting
for a check with proof photos, sent back, late, with rewards), comments, reminder logs and one
person who blocked the bot.

`seed(company, people, now)`; `people` has owner, manager, worker, madina, jasur, nigora.
"""

import io
import random
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.files.base import ContentFile
from django.db.models import DateTimeField, ExpressionWrapper, F, OuterRef, Subquery
from PIL import Image, ImageDraw, ImageFilter

from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.core import demo_plan, uploads
from apps.members.models import Membership
from apps.reminders.models import ReminderLog, ReminderPolicy, ReminderText
from apps.tasks.models import Activity, ChecklistItem, Proof, Task, TaskComment, TaskTemplate

HISTORY_DAYS = 60  # two months: the reports compare a month with the one before
EVERY_DAY = [0, 1, 2, 3, 4, 5, 6]
PALETTES = [
    ((240, 244, 242), [(46, 125, 107), (226, 236, 233), (64, 112, 160), (198, 70, 64)]),
    ((244, 242, 238), [(255, 255, 255), (63, 138, 131), (209, 160, 64), (74, 106, 138)]),
    ((236, 241, 246), [(250, 250, 250), (90, 150, 110), (210, 90, 80), (70, 110, 170)]),
]
COLD_CHAIN = (
    "Sovuq zanjir: muzlatgichda +2…+8 °C bo‘lishi kerak. Termometrdagi raqamni yozing; "
    "chegaradan chiqsa, darhol mudirga xabar bering va dorilarni zaxira muzlatgichga o‘tkazing."
)


def seed(company, people: dict[str, Membership], now: datetime) -> None:
    story = demo_plan.Plan(company, people, now)
    rng = random.Random(911)
    today = story.today
    owner, manager = people["owner"], people["manager"]
    chilonzor, yunusobod = story.branches["C"], story.branches["Y"]
    strict, gentle = _policies(company)

    def members(keys):
        return [story.member(key) for key in keys if story.member(key) is not None]

    def routine(title, due, *, who=(), weekdays=None, **fields):
        template = TaskTemplate.objects.create(
            company=company,
            title=title,
            due_time=due,
            weekdays=weekdays if weekdays is not None else EVERY_DAY,
            created_by=owner,
            **fields,
        )
        template.assignees.set(members(who))
        TaskTemplate.objects.filter(pk=template.pk).update(created_at=now - timedelta(days=90))
        _history(AuditLog.Action.TEMPLATE_CREATED, template, owner, now - timedelta(days=90))
        return template

    def adopt(title, due, *, who=(), **fields):
        """The core demo's routine of the same work, made richer (checklist, proof, policy),
        so the Routines page never lists the same work twice. Without the core demo (the
        `demo_people` fixture) the routine is made here."""
        template = TaskTemplate.objects.filter(
            company=company, title=title, personal=False, onboarding=False
        ).first()
        if template is None:
            return routine(title, due, who=who, **fields)
        before = audit.snapshot(template)
        for name, value in fields.items():
            setattr(template, name, value)
        template.save()
        template.assignees.add(*members(who))
        TaskTemplate.objects.filter(pk=template.pk).update(created_at=now - timedelta(days=90))
        if changes := audit.diff(before, audit.snapshot(template)):
            _history(
                AuditLog.Action.TEMPLATE_CHANGED,
                template,
                manager,
                now - timedelta(days=12, hours=3),
                changes=changes,
            )
        return template

    openers = ["worker", "gulnora"]  # Chilonzor, 08:00 to 20:00
    closers = ["madina", "sardor"]  # Chilonzor, 10:00 to 22:00
    days = ["shahzoda", "kamola"]  # Yunusobod, 08:00 to 20:00
    nights = ["nigora", "dilshod"]  # Yunusobod, 20:00 to 08:00

    handover = adopt(
        demo_plan.HANDOVER,
        time(8, 15),
        who=openers + days,
        needs_confirmation=True,
        reminder_policy=strict,
        escalate_to=manager,
        description=(
            "Dorixonani oldingi smenadan qabul qiling: kassa, muzlatgich, retseptli dorilar "
            "shkafi va navbatchilik jurnali."
        ),
        checklist=[
            "Kassa qoldig‘ini sanash",
            "Muzlatgich haroratini tekshirish",
            "Retseptli dorilar shkafini tekshirish",
            "Navbatchilik jurnaliga imzo",
        ],
    )
    night_handover = routine(
        "Tungi navbatni qabul qilish",
        time(20, 15),
        who=nights,
        branch=yunusobod,
        needs_confirmation=True,
        reminder_policy=strict,
        description="Kunduzgi farmatsevtdan kassani, muzlatgichni va retseptlar jurnalini oling.",
        checklist=["Kassa qoldig‘i", "Muzlatgich harorati", "Retseptlar jurnali"],
    )
    fridge_morning = adopt(
        demo_plan.FRIDGE_MORNING,
        time(9, 0),
        who=openers + days,
        proof=Proof.TEXT,
        reminder_policy=strict,
        description=COLD_CHAIN,
    )
    fridge_evening = adopt(
        demo_plan.FRIDGE_EVENING,
        time(20, 30),
        who=closers + nights,
        proof=Proof.TEXT,
        reminder_policy=strict,
        description=COLD_CHAIN,
    )
    cash_report = adopt(
        demo_plan.CASH_REPORT,
        time(21, 45),
        who=closers,
        branch=chilonzor,
        proof=Proof.PHOTO,
        needs_confirmation=True,
        reminder_policy=strict,
        description="Z-hisobotni chiqaring va terminal sverkasi bilan birga suratga oling.",
        checklist=["Z-hisobot", "Terminal sverkasi", "Naqd pulni seyfga qo‘yish"],
    )
    day_cash = routine(
        "Kunduzgi kassani topshirish",
        time(19, 45),
        who=days,
        branch=yunusobod,
        proof=Proof.PHOTO,
        reminder_policy=strict,
        description="Kassani sanab, tungi farmatsevtga topshiring. Farqni izohda yozing.",
    )
    night_cash = routine(
        "Tungi kassa tekshiruvi",
        time(23, 30),
        who=nights,
        branch=yunusobod,
        proof=Proof.TEXT,
        description="Kassadagi naqd pulni sanang va summani yozing.",
    )
    receiving = routine(
        demo_plan.RECEIVING,
        time(11, 0),
        who=["otabek"],
        weekdays=[0, 1, 2, 3, 4, 5],
        proof=Proof.PHOTO,
        escalate_to=manager,
        description=(
            "Nakladnoy bo‘yicha sanab oling. Seriya va yaroqlilik muddatini tekshiring; "
            "muddati 6 oydan kam qolganini qabul qilmang, mudirga yozing."
        ),
        checklist=[
            "Nakladnoy bo‘yicha sanash",
            "Seriya va yaroqlilik muddati",
            "Sovuq zanjir dorilari: harorat yorlig‘i",
            "Nakladnoyga imzo",
        ],
    )
    expiry = routine(
        "Muddati yaqin dorilarni tekshirish",
        time(12, 0),
        who=["otabek", "malika"],
        weekdays=[0],
        proof=Proof.ANY,
        needs_confirmation=True,
        checklist=[
            "90 kundan kam qolganlarini ajratish",
            "Ro‘yxatni mudirga yuborish",
            "Muddati yaqinlarini oldinga qo‘yish",
        ],
    )
    tags = routine(
        "Narx yorliqlarini yangilash",
        time(14, 0),
        who=[*closers, "malika"],
        weekdays=[1, 4],
        proof=Proof.PHOTO,
        description="Yangi kirimdagi narxlar bo‘yicha. Retseptli dorilar vitrinaga qo‘yilmaydi.",
    )
    defektura = routine(
        "Defektura ro‘yxatini yozish",
        time(19, 0),
        who=openers + days,
        proof=Proof.TEXT,
        description="Bugun so‘ralgan, lekin dorixonada bo‘lmagan dorilarni yozing.",
    )
    cleaning = routine(
        "Nam tozalash va kvarslash",
        time(21, 30),
        who=closers + nights,
        proof=Proof.PHOTO,
        checklist=[
            "Pollarni dezinfeksiyalovchi bilan yuvish",
            "Peshtaxta va vitrinani artish",
            "Kvars lampasini 30 daqiqaga yoqish",
            "Jurnalga yozish",
        ],
    )
    evening_report = routine(
        "Kechki savdo hisobotini ko‘rib chiqish",
        time(21, 30),
        who=["manager"],
        weekdays=[0, 1, 2, 3, 4],
        reminder_policy=gentle,
        description="Ikkala dorixonaning kunlik savdosi va kassa farqini ko‘rib chiqing.",
    )
    orders = adopt(
        demo_plan.TELEGRAM_ORDERS,
        time(12, 0),
        who=openers,
        branch=chilonzor,
        description=(
            "Telegramdagi buyurtmalarga javob bering. Retseptli dori so‘rashsa, retsept bilan "
            "dorixonaga kelishini ayting: retseptli dorilar yetkazib berilmaydi."
        ),
    )
    deliveries = adopt(
        demo_plan.DELIVERIES,
        time(13, 0),
        who=["jasur"],
        reminder_policy=gentle,
        description=(
            "Click, Payme va Uzum orqali to‘langan buyurtmalar. Sovuq zanjir dorilari faqat "
            "termosumkada. Mijozga topshirgach belgilang."
        ),
    )
    rx_log = routine(
        "Retseptlar jurnalini tekshirish",
        time(16, 0),
        who=["manager", "farrux"],
        weekdays=[4],
        needs_confirmation=False,
        description="Haftaning retseptlarini jurnal bilan solishtiring.",
    )
    routine(
        "Kassa apparatini haftalik tozalash",
        time(21, 0),
        who=["madina"],
        branch=chilonzor,
        weekdays=[6],
        is_active=False,
    )

    # Onboarding: what every new person (or a new pharmacist) gets in the first days.
    pharmacist = story.member("worker").position if story.member("worker") else None
    for title, days_after, due, positions, extra in [
        (
            "Dorixonaning ichki tartibi bilan tanishish",
            1,
            time(12, 0),
            [],
            {"checklist": ["Yong‘in chiqishlari", "Birinchi yordam qutisi", "Signalizatsiya"]},
        ),
        ("Oq xalat va bejikni olish", 1, time(10, 0), [], {"proof": Proof.PHOTO}),
        (
            "Kassa dasturini o‘rganish",
            2,
            time(17, 0),
            [pharmacist] if pharmacist else [],
            {
                "checklist": ["Sotuv va to‘lov turlari", "Smenani ochish va yopish", "Z-hisobot"],
                "needs_confirmation": True,
            },
        ),
        ("Mudir bilan tanishuv suhbati", 3, time(15, 0), [], {"escalate_to": manager}),
    ]:
        template = TaskTemplate.objects.create(
            company=company,
            title=title,
            due_time=due,
            onboarding=True,
            due_after_days=days_after,
            created_by=owner,
            **extra,
        )
        template.positions.set(positions)

    # Two months of routine work, so reports, trends and compliance have something to show:
    # (routine, person, share on time, share missed in the last three weeks).
    plan = [
        (handover, "worker", 0.86, 0.02),
        (handover, "gulnora", 0.9, 0.0),
        (handover, "shahzoda", 0.92, 0.0),
        (handover, "kamola", 0.8, 0.0),
        (night_handover, "nigora", 0.95, 0.0),
        (night_handover, "dilshod", 0.9, 0.0),
        (fridge_morning, "worker", 0.8, 0.04),
        (fridge_morning, "gulnora", 0.9, 0.0),
        (fridge_morning, "shahzoda", 0.93, 0.0),
        (fridge_morning, "kamola", 0.85, 0.03),
        (fridge_evening, "madina", 0.93, 0.0),
        (fridge_evening, "sardor", 0.88, 0.0),
        (fridge_evening, "nigora", 1.0, 0.0),
        (fridge_evening, "dilshod", 0.9, 0.0),
        (cash_report, "madina", 0.9, 0.0),
        (cash_report, "sardor", 0.85, 0.0),
        (day_cash, "shahzoda", 0.9, 0.0),
        (day_cash, "kamola", 0.85, 0.0),
        (night_cash, "nigora", 0.95, 0.0),
        (night_cash, "dilshod", 0.9, 0.0),
        (receiving, "otabek", 0.7, 0.0),
        (expiry, "otabek", 0.8, 0.0),
        (expiry, "malika", 0.95, 0.0),
        (tags, "madina", 0.85, 0.0),
        (tags, "sardor", 0.8, 0.0),
        (tags, "malika", 0.9, 0.0),
        (defektura, "worker", 0.82, 0.0),
        (defektura, "gulnora", 0.88, 0.0),
        (defektura, "shahzoda", 0.9, 0.0),
        (defektura, "kamola", 0.8, 0.0),
        (cleaning, "madina", 0.9, 0.0),
        (cleaning, "sardor", 0.85, 0.0),
        (cleaning, "nigora", 0.95, 0.0),
        (cleaning, "dilshod", 0.9, 0.0),
        (evening_report, "manager", 0.88, 0.0),
        (orders, "worker", 0.82, 0.0),
        (orders, "gulnora", 0.9, 0.0),
        (deliveries, "jasur", 0.62, 0.0),
        (rx_log, "manager", 0.9, 0.0),
        (rx_log, "farrux", 0.95, 0.0),
    ]
    plan = [row for row in plan if story.member(row[1]) is not None]
    # Days somebody already has the routine's task (the core demo's own history): never a
    # second task for the same person on the same day.
    taken = set(
        Task.objects.filter(company=company, template__isnull=False).values_list(
            "template_id", "assignee_id", "for_date"
        )
    )
    rows, logs = [], []
    for template, key, on_time, missed in plan:
        member = story.member(key)
        for days_ago in range(HISTORY_DAYS, 0, -1):
            day = today - timedelta(days=days_ago)
            if not template.is_due_on(day) or not story.works(key, day):
                continue
            if (template.pk, member.pk, day) in taken:
                continue
            # Misses only in the last three weeks: older open routine work would read as a
            # neglected list rather than a team's recent slips.
            chance = missed if days_ago <= 21 else 0.0
            task, steps = _history_task(company, story, template, member, day, rng, on_time, chance)
            rows.append(task)
            logs.extend((task, step) for step in steps)
    Task.objects.bulk_create(rows)
    # Made the evening before, like daily generation does.
    Task.objects.filter(pk__in=[task.pk for task in rows]).update(
        created_at=F("due_at") - timedelta(hours=8)
    )
    _bulk_logs(logs)
    # The last two days keep their proof photos, so the photo wall has something to page back to.
    for task in rows:
        if (
            task.completed_at
            and task.proof == Proof.PHOTO
            and (today - task.for_date).days <= 1
            and rng.random() < 0.6
        ):
            _photo(task, SCENES.get(task.title, "shelf"), rng)

    _today(company, story, plan, now, rng)
    _given(company, story, people, now, rng, strict)


# Today -------------------------------------------------------------------------------------


def _today(company, story, plan, now, rng) -> None:
    """Today's routine tasks of the people working today, made at midnight like daily
    generation: done by now when their time has passed, except Alisher's morning fridge reading
    and the courier's deliveries, which run late. The core demo's own tasks stay as they are."""
    today = story.today
    start_of_day = min(now - timedelta(minutes=10), story.at(today, time(0, 5)))
    for template, key, _on_time, _missed in plan:
        member = story.member(key)
        if not template.is_due_on(today) or not story.works(key, today):
            continue
        if Task.objects.filter(template=template, assignee=member, for_date=today).exists():
            continue
        due = story.at(today, template.due_time)
        status, completed, fields = Task.Status.TODO, None, {}
        late = (template.title, key) in (
            (demo_plan.FRIDGE_MORNING, "worker"),
            (demo_plan.DELIVERIES, "jasur"),
        )
        if due < now and late:
            fields = {"reminders_sent": 3, "escalated_at": due + timedelta(minutes=50)}
            if fields["escalated_at"] > now:
                fields = {"reminders_sent": 1}
        elif due < now:
            completed = due - timedelta(minutes=rng.randint(4, 35))
            review = template.needs_confirmation or template.title == demo_plan.RECEIVING
            status = Task.Status.REVIEW if review else Task.Status.DONE
        task = Task.objects.create(
            company=company,
            kind=Task.Kind.DAILY,
            template=template,
            for_date=today,
            title=template.title,
            description=template.description,
            assignee=member,
            created_by=template.created_by,
            due_at=due,
            status=status,
            completed_at=completed,
            proof=template.proof,
            proof_text=_reading(rng) if completed and template.proof == Proof.TEXT else "",
            needs_confirmation=template.needs_confirmation,
            reminder_policy=template.reminder_policy,
            escalate_to=template.escalate_to,
            branch=member.home_branch,
            **fields,
        )
        for index, text in enumerate(template.checklist):
            ChecklistItem.objects.create(
                task=task, text=text, is_done=status != Task.Status.TODO, order=index
            )
        Task.objects.filter(pk=task.pk).update(created_at=start_of_day)
        if status == Task.Status.REVIEW and template.proof == Proof.PHOTO:
            _photo(task, SCENES.get(template.title, "boxes"), rng)
        if fields.get("reminders_sent"):
            for step in range(1, fields["reminders_sent"] + 1):
                _log(
                    task,
                    ReminderLog.Kind.REMINDER,
                    step,
                    member,
                    due + timedelta(minutes=15 * step),
                )
            if fields.get("escalated_at"):
                escalate = task.escalate_to or story.member("manager")
                _log(task, ReminderLog.Kind.ESCALATION, 3, escalate, fields["escalated_at"])


# Given by hand -----------------------------------------------------------------------------


def _given(company, story, people, now, rng, strict) -> None:
    owner, manager = people["owner"], people["manager"]
    today = story.today

    def on_day(key, day, hour, minute=0):
        return story.at(day, time(hour, minute))

    def next_day(key, after=None):
        return story.next_working_day(key, after or today) or today + timedelta(days=1)

    def last_day(key):
        return story.last_working_day(key, today) or today - timedelta(days=1)

    def given(title, key, due, *, by=owner, status=Task.Status.TODO, **fields):
        person = story.member(key)
        if person is None:
            return None
        checklist = fields.pop("checklist", ())
        task = Task.objects.create(
            company=company,
            kind=Task.Kind.ASSIGNED,
            title=title,
            assignee=person,
            created_by=by,
            due_at=due,
            status=status,
            branch=person.home_branch,
            **fields,
        )
        for index, (text, done) in enumerate(checklist):
            ChecklistItem.objects.create(task=task, text=text, is_done=done, order=index)
        Activity.objects.create(
            company=company, recipient=person, actor=by, kind=Activity.Kind.ASSIGNED, task=task
        )
        # Given the day before its deadline (or earlier, for work already finished).
        given_at = min(due, fields.get("completed_at") or due, now) - timedelta(hours=20)
        Task.objects.filter(pk=task.pk).update(created_at=given_at)
        Activity.objects.filter(task=task).update(created_at=given_at)
        _history(AuditLog.Action.TASK_ASSIGNED, task, by, given_at, assignee=str(person))
        if task.confirmed_at:
            _history(AuditLog.Action.TASK_CONFIRMED, task, task.confirmed_by, task.confirmed_at)
        return task

    # The storekeeper (or, without him, the head) missed calling a distributor about a late
    # delivery: overdue since the last working day, chased four times, escalated.
    caller = "otabek" if story.member("otabek") else "manager"
    called = last_day(caller)
    supplier = given(
        "Distribyutorga qo‘ng‘iroq: kechikkan nakladnoy №4471",
        caller,
        on_day(caller, called, 15),
        by=manager if caller != "manager" else owner,
        proof=Proof.TEXT,
        priority=Task.Priority.URGENT,
        reminders_sent=4,
        escalated_at=on_day(caller, called, 16, 40),
        description=(
            "«Oqtosh Med Ta’minot»dan Amoksitsillin 500 mg kapsula №16 va Omeprazol 20 mg "
            "kapsula №30 kelmadi. Yangi sanani so‘rab, izohga yozing."
        ),
    )
    if supplier is not None:
        _comment(
            supplier,
            manager if caller != "manager" else owner,
            "Telefon: «Oqtosh Med Ta’minot» savdo bo‘limi, +998 71 200 44 55.",
            on_day(caller, called, 11),
        )
        _history(
            AuditLog.Action.TASK_CHANGED,
            supplier,
            manager,
            on_day(caller, called, 12, 10),
            changes={"priority": ["high", "urgent"]},
        )
        for step in (1, 2, 3, 4):
            _log(
                supplier,
                ReminderLog.Kind.REMINDER,
                step,
                supplier.assignee,
                supplier.due_at + timedelta(minutes=20 * step),
            )
        _log(
            supplier,
            ReminderLog.Kind.ESCALATION,
            3,
            manager if caller != "manager" else owner,
            supplier.due_at + timedelta(hours=1, minutes=40),
        )

    # Madina's price tags wait for the head's check since her last shift.
    tagged_on = last_day("madina")
    price_tags = given(
        "Narx yorliqlari: vitaminlar va retseptsiz dorilar javoni",
        "madina",
        on_day("madina", tagged_on, 21),
        status=Task.Status.REVIEW,
        completed_at=on_day("madina", tagged_on, 20, 35),
        proof=Proof.PHOTO,
        needs_confirmation=True,
        reward=Decimal("50000.00"),
        checklist=[("Vitaminlar", True), ("Yo‘tal va shamollash", True), ("Kassa oldi", True)],
    )
    if price_tags is not None:
        _photo(price_tags, "tags", rng)

    # Nigora's catalogue photos came back: retake in daylight.
    photos = given(
        "Onlayn katalog uchun yangi dorilarni suratga olish",
        "nigora",
        on_day("nigora", next_day("nigora"), 23),
        status=Task.Status.RETURNED,
        proof=Proof.PHOTO,
        needs_confirmation=True,
        description="Katalog uchun 12 ta qadoq, oq fonda, har biridan bittadan.",
    )
    returned_at = now - timedelta(hours=1, minutes=15)
    if photos is not None:
        _comment(photos, owner, "Qadoqlar yaltirab chiqqan, yorug‘ joyda qayta oling.", returned_at)
        _history(
            AuditLog.Action.TASK_RETURNED,
            photos,
            owner,
            returned_at,
            reason="Qadoqlar yaltirab chiqqan, yorug‘ joyda qayta oling.",
        )
    given(
        "Ombordagi konditsionerni ta’mirlatish (xona harorati 25 °C dan oshmasin)",
        "manager",
        on_day("manager", next_day("manager"), 17),
        priority=Task.Priority.HIGH,
        description="Dori saqlash xonasida harorat 24 °C ga yetdi. Usta chaqiring.",
    )
    back = next_day("madina", story.day(1))
    given(
        "Oylik hisobot uchun kassa daftarini topshirish",
        "madina",
        on_day("madina", back, 20),
        by=manager,
        reward=Decimal("30000.00"),
    )
    given(
        "Ombor javonlarini qayta tartiblash",
        "otabek",
        on_day("otabek", next_day("otabek", story.day(1)), 17),
        priority=Task.Priority.LOW,
        checklist=[("Antibiotiklar bo‘limi", False), ("Vitaminlar va gigiyena", False)],
    )
    banner_day = last_day("nigora")
    banner = given(
        "«Gripp mavsumi» e’lonini vitrinaga osish",
        "nigora",
        on_day("nigora", banner_day, 22, 30),
        status=Task.Status.DONE,
        completed_at=on_day("nigora", banner_day, 21, 50),
        confirmed_at=min(
            on_day("nigora", banner_day + timedelta(days=1), 9, 20), now - timedelta(minutes=20)
        ),
        confirmed_by=owner,
        proof=Proof.PHOTO,
        reward=Decimal("75000.00"),
    )
    if banner is not None:
        _photo(banner, "window", rng)
    if story.works("worker", today) and now >= story.at(today, time(11, 0)):
        glass = given(
            "Vitrina oynalarini artish",
            "worker",
            story.at(today, time(11, 0)),
            status=Task.Status.DONE,
            completed_at=story.at(today, time(10, 40)),
            proof=Proof.PHOTO,
        )
        _photo(glass, "window", rng)
    given(
        "Kassa uchun yangi terminalni sozlash",
        "madina",
        on_day("madina", back, 12),
        by=manager,
        status=Task.Status.CANCELLED,
    )
    given(
        "Muddati o‘tgan dorilarni hisobdan chiqarish dalolatnomasi",
        "otabek",
        on_day("otabek", next_day("otabek"), 15),
        by=manager,
        checklist=[("Ro‘yxat", True), ("Dalolatnoma", False), ("Mudir imzosi", False)],
    )
    given(
        "Litsenziyani uzaytirish uchun hujjatlarni tayyorlash",
        "owner",
        story.at(story.day(10), time(17, 0)),
        by=owner,
        priority=Task.Priority.HIGH,
    )

    # The head's own to-do list: personal, so only owners (with the setting on) see it.
    own_day = today if story.works("manager", today) else next_day("manager")
    own = Task.objects.create(
        company=company,
        kind=Task.Kind.PERSONAL,
        title="Bankdagi to‘lovlarni tekshirish",
        assignee=manager,
        created_by=manager,
        due_at=story.at(own_day, time(17, 0)),
        branch=manager.home_branch,
    )
    noted = min(now - timedelta(hours=2), story.at(own_day, time(9, 10)))
    Task.objects.filter(pk=own.pk).update(created_at=noted)

    # A heads-up before a fridge reading, and the person who blocked the bot two days ago.
    first_reading = (
        Task.objects.filter(
            company=company, for_date=today, template__title=demo_plan.FRIDGE_MORNING
        )
        .order_by("pk")
        .first()
    )
    if first_reading is not None:
        _log(
            first_reading,
            ReminderLog.Kind.HEADS_UP,
            0,
            first_reading.assignee,
            first_reading.due_at - timedelta(minutes=15),
        )
    blocked_at = now - timedelta(days=2, hours=4)
    nigora = people["nigora"].user
    nigora.employee_bot_blocked_at = blocked_at
    nigora.save(update_fields=["employee_bot_blocked_at"])
    if photos is not None:
        _log(photos, ReminderLog.Kind.REMINDER, 1, people["nigora"], blocked_at, "blocked the bot")
        _log(photos, ReminderLog.Kind.BLOCKED, 1, manager, blocked_at)


# Pieces ------------------------------------------------------------------------------------


def _policies(company) -> tuple[ReminderPolicy, ReminderPolicy]:
    strict = ReminderPolicy.objects.create(
        company=company,
        name="Kassa va sovuq zanjir (qattiq)",
        heads_up_minutes=15,
        repeat_every_minutes=10,
        max_reminders=8,
        escalate_after=2,
        quiet_from=time(23, 50),
        quiet_until=time(6, 0),
        snooze_minutes=10,
        max_snoozes=1,
        replace_previous=True,
    )
    ReminderText.objects.bulk_create(
        [
            ReminderText(
                policy=strict,
                from_step=1,
                text="{name}, {task} {due} da bajarilishi kerak edi. Iltimos, hoziroq bajaring.",
            ),
            ReminderText(
                policy=strict,
                from_step=2,
                text="⚠️ {task} {late} kechikdi. Mudirga xabar berildi.",
            ),
            ReminderText(
                policy=strict,
                from_step=5,
                text="🚨 {name}, {task} hali ham bajarilmagan. Mudir kutyapti.",
            ),
        ]
    )
    gentle = ReminderPolicy.objects.create(
        company=company,
        name="Yumshoq (ofis va yetkazish)",
        heads_up_minutes=30,
        repeat_every_minutes=60,
        max_reminders=4,
        escalate_after=0,
        quiet_from=time(20, 0),
        quiet_until=time(9, 0),
        quiet_days=[6],
        snooze_minutes=30,
        max_snoozes=2,
    )
    ReminderText.objects.create(
        policy=gentle, from_step=1, text="Salom, {name}! {task} uchun eslatma: muddat {due} edi."
    )
    return strict, gentle


def _reading(rng: random.Random) -> str:
    """A fridge reading inside the cold chain's 2 to 8 °C."""
    return f"+{rng.choice([3, 4, 4, 5, 5, 6])} °C"


def _history_task(company, story, template, person, day, rng, on_time: float, missed: float):
    """One past day's task (not saved) and the reminder steps it got."""
    due = story.at(day, template.due_time)
    roll = rng.random()
    if roll < missed:
        status, completed = Task.Status.TODO, None
    elif roll < missed + on_time:
        status, completed = Task.Status.DONE, due - timedelta(minutes=rng.randint(4, 55))
    else:
        status, completed = Task.Status.DONE, due + timedelta(minutes=rng.randint(12, 140))
    late = completed is None or completed > due
    task = Task(
        company=company,
        kind=Task.Kind.DAILY,
        template=template,
        for_date=day,
        title=template.title,
        assignee=person,
        created_by=template.created_by,
        due_at=due,
        status=status,
        completed_at=completed,
        confirmed_at=completed + timedelta(minutes=15)
        if completed and template.needs_confirmation
        else None,
        proof=template.proof,
        proof_text=_reading(rng) if template.proof == Proof.TEXT and completed else "",
        needs_confirmation=template.needs_confirmation,
        reminder_policy=template.reminder_policy,
        branch=person.home_branch,
        reminders_sent=0 if not late else (3 if completed is None else rng.randint(1, 3)),
    )
    return task, list(range(1, task.reminders_sent + 1))


def _bulk_logs(logs) -> None:
    """Reminder logs for many tasks in a few queries: sent 20 minutes apart after the deadline."""
    made = ReminderLog.objects.bulk_create(
        ReminderLog(task=task, kind=ReminderLog.Kind.REMINDER, step=step, recipient=task.assignee)
        for task, step in logs
    )
    due = Subquery(Task.objects.filter(pk=OuterRef("task_id")).values("due_at")[:1])
    for step in {step for _task, step in logs}:
        ReminderLog.objects.filter(pk__in=[log.pk for log in made if log.step == step]).update(
            sent_at=ExpressionWrapper(
                due + timedelta(minutes=20 * step), output_field=DateTimeField()
            )
        )


# Proof photos by routine.
SCENES = {
    demo_plan.RECEIVING: "boxes",
    demo_plan.CASH_REPORT: "tags",
    "Kunduzgi kassani topshirish": "tags",
    "Narx yorliqlarini yangilash": "tags",
    "Nam tozalash va kvarslash": "store",
}


def _history(action, target, by: Membership, at: datetime, **details) -> None:
    """An audit row as if `by` had done it at `at`, so History tabs tell a story."""
    row = audit.record(
        action, company_id=target.company_id, actor=by.user, target=target, **details
    )
    AuditLog.objects.filter(pk=row.pk).update(created_at=at)


def _comment(task, author, text, at):
    comment = TaskComment.objects.create(task=task, author=author, text=text)
    TaskComment.objects.filter(pk=comment.pk).update(created_at=at)


def _log(task, kind, step, recipient, at, error=""):
    log = ReminderLog.objects.create(
        task=task, kind=kind, step=step, recipient=recipient, delivered=not error, error=error
    )
    ReminderLog.objects.filter(pk=log.pk).update(sent_at=at)


def _photo(task: Task, scene: str, rng: random.Random) -> None:
    """A believable-looking proof photo (drawn, so the demo needs no files) and its preview."""
    data = _scene(scene, rng)
    picture = uploads.sanitize_image(ContentFile(data, name="proof.jpg"))
    task.proof_photo.save(picture.name, picture, save=False)
    thumb = uploads.make_thumb(ContentFile(data, name="proof.jpg"))
    task.proof_thumb.save(thumb.name, thumb, save=False)
    task.save(update_fields=["proof_photo", "proof_thumb"])


def _scene(kind: str, rng: random.Random) -> bytes:
    """A 1200 by 900 picture of pharmacy shelves, delivery boxes, price tags or a window."""
    background, colors = rng.choice(PALETTES)
    image = Image.new("RGB", (1200, 900), background)
    draw = ImageDraw.Draw(image)
    if kind in ("shelf", "tags", "store"):
        for row in range(4):
            top = 120 + row * 190
            draw.rectangle((60, top + 150, 1140, top + 166), fill=(200, 205, 205))
            x = 80
            while x < 1100:
                width = rng.randint(40, 90)
                height = rng.randint(70, 140)
                draw.rounded_rectangle(
                    (x, top + 150 - height, x + width, top + 148), radius=4, fill=rng.choice(colors)
                )
                if kind == "tags":
                    draw.rectangle((x + 4, top + 152, x + 40, top + 164), fill=(255, 236, 120))
                x += width + rng.randint(4, 12)
        if kind == "store":
            draw.rectangle((0, 0, 1200, 90), fill=(46, 125, 107))
            draw.rectangle((570, 18, 630, 72), fill=(255, 255, 255))
            draw.rectangle((582, 30, 618, 60), fill=(46, 125, 107))
    elif kind == "boxes":
        draw.rectangle((0, 640, 1200, 900), fill=(190, 190, 186))
        for _ in range(9):
            x, y = rng.randint(40, 980), rng.randint(330, 560)
            w, h = rng.randint(160, 240), rng.randint(140, 220)
            draw.rectangle(
                (x, y, x + w, y + h), fill=(214, 196, 160), outline=(150, 126, 90), width=6
            )
            draw.rectangle((x + 20, y + 20, x + 90, y + 60), fill=(255, 255, 255))
    else:  # window
        draw.rectangle((80, 80, 1120, 820), fill=(222, 234, 240), outline=(90, 100, 100), width=24)
        draw.rectangle((80, 80, 1120, 170), fill=(46, 125, 107))
        for index in range(4):
            x = 180 + index * 230
            draw.rounded_rectangle((x, 380, x + 150, 640), radius=10, fill=colors[index % 4])
            draw.rectangle((x + 20, 420, x + 130, 470), fill=(255, 255, 255))
    image = image.filter(ImageFilter.GaussianBlur(1.0))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=82)
    return out.getvalue()
