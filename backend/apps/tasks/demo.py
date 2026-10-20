"""Demo data for the owner console's task pages (docs/PLAN-OWNER.md §2.3 rule 22): routines per
branch and position with a month of history, onboarding templates, reminder policies with
Uzbek texts, today's work in every state (waiting for a check with proof photos, sent back,
late, with rewards), comments, reminder logs and one person who blocked the bot.

`seed(company, people, now)`; `people` has owner, manager, worker, madina, jasur, nigora.
"""

import io
import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFilter

from apps.core import uploads
from apps.members.models import Membership, Position
from apps.reminders.models import ReminderLog, ReminderPolicy, ReminderText
from apps.tasks.models import Activity, ChecklistItem, Proof, Task, TaskComment, TaskTemplate

HISTORY_DAYS = 60  # two months: the reports compare a month with the one before
PALETTES = [
    ((242, 236, 224), [(198, 113, 57), (122, 138, 94), (74, 106, 138), (209, 160, 64)]),
    ((232, 238, 242), [(63, 138, 131), (166, 106, 79), (138, 90, 122), (122, 138, 94)]),
    ((246, 240, 232), [(209, 160, 64), (198, 113, 57), (74, 106, 138), (63, 138, 131)]),
]


def seed(company, people: dict[str, Membership], now: datetime) -> None:
    rng = random.Random(911)
    tz = ZoneInfo(company.timezone)
    today = timezone.localtime(now, tz).date()
    branches = list(company.branches.order_by("order", "pk"))
    chilonzor = branches[0]
    yunusobod = branches[1] if len(branches) > 1 else branches[0]
    owner, manager = people["owner"], people["manager"]
    positions = {p.name: p for p in Position.objects.for_company(company)}

    strict, gentle = _policies(company)

    def position(name: str) -> list[Position]:
        return [positions[name]] if name in positions else []

    def routine(title, due, *, who=(), roles=(), branch=None, weekdays=None, **fields):
        template = TaskTemplate.objects.create(
            company=company,
            title=title,
            due_time=due,
            weekdays=weekdays if weekdays is not None else [0, 1, 2, 3, 4, 5, 6],
            created_by=owner,
            branch=branch,
            **fields,
        )
        template.assignees.set(who)
        template.positions.set([p for name in roles for p in position(name)])
        TaskTemplate.objects.filter(pk=template.pk).update(created_at=now - timedelta(days=90))
        return template

    def adopt(core_title, fallback, due, *, who=(), english=None, **fields):
        """The core demo's routine of the same work, made richer (branch, checklist, proof,
        policy), so the Routines page never lists the same work twice for one person. The core
        demo writes English, so its routines get the `english` description and checklist.
        Without the core demo (the `demo_people` fixture) the routine is made as `fallback`."""
        template = TaskTemplate.objects.filter(
            company=company, title=core_title, personal=False, onboarding=False
        ).first()
        if template is None:
            return routine(fallback, due, who=who, **fields)
        for name, value in (fields | (english or {})).items():
            setattr(template, name, value)
        template.save()
        template.assignees.add(*who)
        TaskTemplate.objects.filter(pk=template.pk).update(created_at=now - timedelta(days=90))
        return template

    opening = adopt(
        "Opening checklist",
        "Do‘konni ochish: tekshiruv ro‘yxati",
        time(8, 30),
        who=[people["worker"]],
        branch=chilonzor,
        proof=Proof.PHOTO,
        needs_confirmation=True,
        reminder_policy=strict,
        escalate_to=manager,
        description=(
            "Chiroqlar, kassa qoldig‘i, vitrina va eshik. Oxirida do‘kon ichidan bitta rasm."
        ),
        checklist=[
            "Chiroqlar va musiqani yoqish",
            "Kassa boshlang‘ich qoldig‘ini sanash",
            "Vitrina va eshikni tekshirish",
            "Pol tozaligini ko‘zdan kechirish",
        ],
        english={
            "description": (
                "Lights, till float, shop window and door. One photo from inside the shop at "
                "the end."
            ),
            "checklist": [
                "Lights and music on",
                "Count the till float",
                "Check the window and the door",
                "Floor is clean",
            ],
        },
    )
    closing = routine(
        "Kassani yopish va Z-hisobot",
        time(21, 15),
        who=[people["madina"]],
        branch=chilonzor,
        proof=Proof.PHOTO,
        needs_confirmation=True,
        reminder_policy=strict,
        description="Z-hisobotni chiqarib, terminal cheki bilan birga suratga oling.",
        checklist=["Z-hisobot", "Terminal yakuniy cheki", "Naqd pulni seyfga qo‘yish"],
    )
    fridge = routine(
        "Muzlatgich haroratini yozish",
        time(9, 30),
        who=[people["worker"], people["madina"]],
        branch=chilonzor,
        proof=Proof.TEXT,
        description="Ichimliklar muzlatgichi: +2…+6 °C bo‘lishi kerak. Raqamni yozing.",
    )
    delivery = adopt(
        "Receive the morning delivery",
        "Ertalabki yukni qabul qilish",
        time(10, 0),
        who=[people["jasur"]],
        branch=yunusobod,
        proof=Proof.PHOTO,
        description="Nakladnaya bo‘yicha sanab oling, kamchilik bo‘lsa Bekzodga yozing.",
        checklist=["Qutilar soni", "Muddatini tekshirish", "Nakladnayaga imzo"],
        escalate_to=manager,
        english={
            "description": "Count it against the waybill; tell Bekzod if anything is short.",
            "checklist": ["Number of boxes", "Expiry dates", "Sign the waybill"],
        },
    )
    orders = adopt(
        "Deliver online orders",
        "Onlayn buyurtmalarni yetkazish",
        time(13, 0),
        who=[people["nigora"]],
        branch=yunusobod,
        weekdays=[0, 1, 2, 3, 4, 5],
        reminder_policy=gentle,
        description="Payme va Click orqali kelgan buyurtmalar. Mijozga yetkazilgach belgilang.",
        english={
            "description": "Orders paid through Payme and Click. Tick it once they're delivered."
        },
    )
    shelves = routine(
        "Javonlarni to‘ldirish va narx yorliqlari",
        time(16, 0),
        who=[people["jasur"], people["nigora"]],
        branch=yunusobod,
        proof=Proof.PHOTO,
        checklist=["Ichimliklar", "Shirinliklar", "Kosmetika", "Narx yorliqlari"],
    )
    inventory = routine(
        "Haftalik inventarizatsiya: kosmetika bo‘limi",
        time(18, 0),
        who=[people["worker"]],
        branch=chilonzor,
        weekdays=[5],
        proof=Proof.ANY,
        needs_confirmation=True,
    )
    routine(
        "Kechki vitrina yoritilishini tekshirish",
        time(20, 30),
        who=[people["madina"]],
        branch=chilonzor,
        is_active=False,
    )
    evening_report = routine(
        "Kechki savdo hisobotini tekshirish",
        time(21, 30),
        who=[people["manager"]],
        reminder_policy=gentle,
        weekdays=[0, 1, 2, 3, 4, 5],
        description="Ikkala filialning kunlik savdosi va kassa farqini ko‘rib chiqing.",
    )
    replies = TaskTemplate.objects.filter(
        company=company, title="Reply to customer messages", personal=False
    ).first()

    # Onboarding: what every new person (or a new cashier) gets on the first days.
    for title, days, due, roles, extra in [
        (
            "Xavfsizlik qoidalari bilan tanishish",
            1,
            time(12, 0),
            (),
            {"checklist": ["Yong‘in chiqishlari", "Birinchi yordam qutisi", "Signalizatsiya kodi"]},
        ),
        ("Ish formasi va bejikni olish", 1, time(10, 0), (), {"proof": Proof.PHOTO}),
        (
            "Kassa dasturini o‘rganish",
            2,
            time(17, 0),
            ("Cashier",),
            {
                "checklist": ["Sotuvni ochish", "Qaytarish", "Smena yopish"],
                "needs_confirmation": True,
            },
        ),
        ("Menejer bilan tanishuv suhbati", 3, time(15, 0), (), {"escalate_to": manager}),
    ]:
        template = TaskTemplate.objects.create(
            company=company,
            title=title,
            due_time=due,
            onboarding=True,
            due_after_days=days,
            created_by=owner,
            **extra,
        )
        template.positions.set([p for name in roles for p in position(name)])

    # A month of routine work, so reports, trends and compliance have something to show. It
    # keeps the core demo's story: Nigora is never late, Jasur is often late but his only
    # missed tasks are the core demo's two.
    history = [
        (opening, people["worker"], 0.86, 0.02),
        (closing, people["madina"], 0.9, 0.0),
        (fridge, people["worker"], 0.8, 0.04),
        (fridge, people["madina"], 0.93, 0.0),
        (delivery, people["jasur"], 0.62, 0.0),
        (orders, people["nigora"], 1.0, 0.0),
        (shelves, people["jasur"], 0.7, 0.0),
        (shelves, people["nigora"], 1.0, 0.0),
        (inventory, people["worker"], 0.75, 0.0),
        (evening_report, manager, 0.88, 0.0),
    ]
    if replies is not None:  # the core demo's routine: give it a history too
        history.append((replies, people["worker"], 0.82, 0.0))
    # Days somebody already has the routine's task (the core demo's own history, some of it
    # without `for_date`): never a second task for the same person on the same day.
    taken = {
        (template_id, assignee_id, for_date or timezone.localtime(due_at, tz).date())
        for template_id, assignee_id, for_date, due_at in Task.objects.filter(
            company=company, template__isnull=False
        ).values_list("template_id", "assignee_id", "for_date", "due_at")
        if for_date or due_at
    }
    for template, person, on_time, missed in history:
        for days_ago in range(HISTORY_DAYS, 0, -1):
            day = today - timedelta(days=days_ago)
            if not template.is_due_on(day) or (template.pk, person.pk, day) in taken:
                continue
            _history_task(company, template, person, day, tz, rng, on_time, missed)

    # Today: routine tasks in every state, made at midnight like daily generation. The core
    # demo may already have given someone today's task of a routine: theirs stays.
    start_of_day = datetime.combine(today, time(0, 5), tzinfo=tz)

    def earlier_today(**delta) -> datetime:
        """A deadline that has passed, but today: late work stays today's (yesterday's numbers
        are history, and the core demo's 14-day story counts only its own misses)."""
        return max(now - timedelta(**delta), min(start_of_day, now))

    def today_task(template, person, **fields):
        already = Task.objects.filter(
            company=company,
            template=template,
            assignee=person,
            due_at__gte=start_of_day - timedelta(minutes=5),
            due_at__lt=start_of_day + timedelta(days=1),
        ).first()
        if already is not None:
            return already
        due = datetime.combine(today, template.due_time, tzinfo=tz)
        task = Task.objects.create(
            company=company,
            kind=Task.Kind.DAILY,
            template=template,
            for_date=today,
            title=template.title,
            description=template.description,
            assignee=person,
            created_by=template.created_by,
            due_at=due,
            proof=template.proof,
            needs_confirmation=template.needs_confirmation,
            reminder_policy=template.reminder_policy,
            escalate_to=template.escalate_to,
            branch=person.home_branch,
            **fields,
        )
        for index, text in enumerate(template.checklist):
            ChecklistItem.objects.create(
                task=task, text=text, is_done=task.status != Task.Status.TODO, order=index
            )
        Task.objects.filter(pk=task.pk).update(created_at=min(start_of_day, now))
        return task

    morning = datetime.combine(today, time(8, 45), tzinfo=tz)
    early = now < morning + timedelta(hours=2)
    opened = today_task(
        opening,
        people["worker"],
        status=Task.Status.REVIEW,
        completed_at=min(now, morning - timedelta(minutes=6)),
    )
    if opened.status == Task.Status.REVIEW and not opened.proof_photo:
        _photo(opened, "store", rng)
    received = today_task(
        delivery,
        people["jasur"],
        status=Task.Status.REVIEW if not early else Task.Status.TODO,
        completed_at=min(now, datetime.combine(today, time(10, 12), tzinfo=tz))
        if not early
        else None,
    )
    if received.status == Task.Status.REVIEW:
        _photo(received, "boxes", rng)
    shelf = today_task(
        shelves, people["nigora"], status=Task.Status.DONE, completed_at=now - timedelta(minutes=35)
    )
    _photo(shelf, "shelf", rng)
    late_shelf = today_task(
        shelves, people["jasur"], reminders_sent=3, escalated_at=now - timedelta(minutes=20)
    )
    Task.objects.filter(pk=late_shelf.pk).update(due_at=earlier_today(hours=1, minutes=10))
    fridge_task = today_task(
        fridge,
        people["madina"],
        status=Task.Status.DONE,
        completed_at=now - timedelta(hours=2),
        proof_text="+4 °C",
    )
    today_task(fridge, people["worker"], reminders_sent=2)
    Task.objects.filter(template=fridge, for_date=today, assignee=people["worker"]).update(
        due_at=earlier_today(minutes=50)
    )
    today_task(closing, people["madina"])
    Task.objects.filter(template=closing, for_date=today).update(due_at=now + timedelta(hours=5))
    today_task(
        orders,
        people["nigora"],
        status=Task.Status.IN_PROGRESS,
        started_at=now - timedelta(minutes=40),
    )
    Task.objects.filter(template=orders, for_date=today).update(
        due_at=now + timedelta(hours=1, minutes=30)
    )

    # Work given by hand, some with rewards.
    def given(title, person, due, *, by=owner, status=Task.Status.TODO, **fields):
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
        return task

    window = given(
        "Kuzgi vitrinani yangilash",
        people["worker"],
        now + timedelta(days=1, hours=3),
        status=Task.Status.IN_PROGRESS,
        started_at=now - timedelta(hours=2),
        priority=Task.Priority.HIGH,
        proof=Proof.PHOTO,
        needs_confirmation=True,
        reward=Decimal("150000.00"),
        description=(
            "Yangi kolleksiya: chap tomonda chegirma relsi, o‘ngda yangi kelganlar. "
            "Narx kartochkalarini unutmang."
        ),
        checklist=[
            ("Eski vitrinani yig‘ish", True),
            ("Kiyimlarni dazmollash", True),
            ("Manekenlarni kiyintirish", False),
            ("Ko‘chadan rasm", False),
        ],
    )
    _comment(window, owner, "Manekenlar omborda, yuqori javonda.", now - timedelta(hours=3))
    _comment(
        window,
        people["worker"],
        "Soat 15:00 gacha tugataman, chiroqlarni ham almashtiraman.",
        now - timedelta(hours=2, minutes=40),
    )
    supplier = given(
        "Yetkazib beruvchiga qo‘ng‘iroq: kechikkan buyurtma №4471",
        people["jasur"],
        earlier_today(hours=3),
        by=manager,
        proof=Proof.TEXT,
        priority=Task.Priority.URGENT,
        reminders_sent=4,
        escalated_at=now - timedelta(hours=1, minutes=40),
        description="Juma kuni kelishi kerak edi. Yangi sanani so‘rab, izohga yozing.",
    )
    _comment(supplier, manager, "Telefon: Sharq Savdo, Akmal aka.", now - timedelta(hours=4))
    tags = given(
        "Qishki kolleksiya uchun narx yorliqlari",
        people["madina"],
        now + timedelta(hours=2),
        status=Task.Status.REVIEW,
        completed_at=now - timedelta(minutes=18),
        proof=Proof.PHOTO,
        needs_confirmation=True,
        reward=Decimal("50000.00"),
        checklist=[("3-relis", True), ("4-relis", True), ("Kassa oldi", True)],
    )
    _photo(tags, "tags", rng)
    photos = given(
        "Yangi kelgan mahsulotlarni suratga olish",
        people["nigora"],
        now + timedelta(hours=4),
        status=Task.Status.RETURNED,
        proof=Proof.PHOTO,
        needs_confirmation=True,
        description="Instagram uchun 12 ta mahsulot, oq fonda, har biridan bittadan.",
    )
    _comment(
        photos,
        owner,
        "Kunduzgi yorug‘likda qayta oling, ranglar xira chiqqan.",
        now - timedelta(hours=1, minutes=15),
    )
    given(
        "Chilonzor: konditsionerni ta’mirlash ustasini chaqirish",
        manager,
        now + timedelta(days=2),
        priority=Task.Priority.HIGH,
        description="Sotuv zalidagi konditsioner shovqin qilyapti. Kafolat talonini oling.",
    )
    given(
        "Oylik hisobot uchun kassa daftarini topshirish",
        people["madina"],
        now + timedelta(days=3),
        by=manager,
        reward=Decimal("30000.00"),
    )
    given(
        "Yunusobod: ombor javonlarini qayta tartiblash",
        people["jasur"],
        now + timedelta(days=4),
        priority=Task.Priority.LOW,
        checklist=[("Ichimliklar bo‘limi", False), ("Maishiy kimyo", False)],
    )
    done_given = given(
        "Bayramona aksiya bannerini osish",
        people["nigora"],
        now - timedelta(days=1, hours=2),
        status=Task.Status.DONE,
        completed_at=now - timedelta(days=1, hours=3),
        confirmed_at=now - timedelta(days=1),
        confirmed_by=owner,
        proof=Proof.PHOTO,
        reward=Decimal("75000.00"),
    )
    _photo(done_given, "window", rng)
    glass = given(
        "Vitrina oynalarini artish",
        people["worker"],
        now - timedelta(minutes=20),
        status=Task.Status.DONE,
        completed_at=now - timedelta(minutes=28),
        proof=Proof.PHOTO,
    )
    _photo(glass, "window", rng)
    given(
        "Kassir uchun yangi terminalni sozlash",
        people["madina"],
        now + timedelta(hours=6),
        by=manager,
        status=Task.Status.CANCELLED,
    )

    # The manager's own to-do list: personal, so only owners (with the setting on) see it.
    own = Task.objects.create(
        company=company,
        kind=Task.Kind.PERSONAL,
        title="Bankdagi to‘lovlarni tekshirish",
        assignee=manager,
        created_by=manager,
        due_at=now + timedelta(hours=5),
        branch=manager.home_branch,
    )
    Task.objects.filter(pk=own.pk).update(created_at=now - timedelta(hours=6))

    # Reminders: today's late work, an escalation and a blocked bot.
    for step in (1, 2, 3, 4):
        _log(
            supplier,
            ReminderLog.Kind.REMINDER,
            step,
            people["jasur"],
            supplier.due_at + timedelta(minutes=20 * step),
        )
    _log(supplier, ReminderLog.Kind.ESCALATION, 3, manager, supplier.due_at + timedelta(hours=1))
    for step in (1, 2, 3):
        _log(
            late_shelf,
            ReminderLog.Kind.REMINDER,
            step,
            people["jasur"],
            now - timedelta(minutes=70) + timedelta(minutes=20 * step),
        )
    _log(late_shelf, ReminderLog.Kind.ESCALATION, 3, manager, now - timedelta(minutes=20))
    _log(fridge_task, ReminderLog.Kind.HEADS_UP, 0, people["madina"], now - timedelta(hours=3))
    blocked_user = people["nigora"].user
    blocked_user.employee_bot_blocked_at = now - timedelta(days=2, hours=4)
    blocked_user.save(update_fields=["employee_bot_blocked_at"])
    _log(
        photos,
        ReminderLog.Kind.REMINDER,
        1,
        people["nigora"],
        now - timedelta(days=2, hours=4),
        error="blocked the bot",
    )
    _log(photos, ReminderLog.Kind.BLOCKED, 1, manager, now - timedelta(days=2, hours=4))


def _policies(company) -> tuple[ReminderPolicy, ReminderPolicy]:
    strict = ReminderPolicy.objects.create(
        company=company,
        name="Kassa va ochilish (qattiq)",
        heads_up_minutes=15,
        repeat_every_minutes=10,
        max_reminders=8,
        escalate_after=2,
        quiet_from=time(23, 0),
        quiet_until=time(7, 0),
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
                text="⚠️ {task} {late} kechikdi. Menejerga xabar berildi.",
            ),
            ReminderText(
                policy=strict,
                from_step=5,
                text="🚨 {name}, {task} hali ham bajarilmagan. Bu kassa tartibiga ta’sir qiladi.",
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


def _history_task(
    company, template, person, day: date, tz, rng: random.Random, on_time: float, missed: float
):
    due = datetime.combine(day, template.due_time, tzinfo=tz)
    roll = rng.random()
    if roll < missed:
        status, completed = Task.Status.TODO, None
    elif roll < missed + on_time:
        status, completed = Task.Status.DONE, due - timedelta(minutes=rng.randint(4, 55))
    else:
        status, completed = Task.Status.DONE, due + timedelta(minutes=rng.randint(12, 140))
    task = Task.objects.create(
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
        proof_text="+5 °C" if template.proof == Proof.TEXT and completed else "",
        needs_confirmation=template.needs_confirmation,
        reminder_policy=template.reminder_policy,
        branch=person.home_branch,
        reminders_sent=0 if completed is None or completed <= due else rng.randint(1, 3),
    )
    if completed is None or completed > due:
        for step in range(1, (3 if completed is None else task.reminders_sent) + 1):
            _log(task, ReminderLog.Kind.REMINDER, step, person, due + timedelta(minutes=20 * step))
    Task.objects.filter(pk=task.pk).update(created_at=due - timedelta(hours=8))
    # The last two days keep their proof photos, so the photo wall has something to page back to.
    if (
        completed
        and template.proof == Proof.PHOTO
        and (timezone.localdate(timezone=tz) - day).days <= 2
    ):
        _photo(task, PHOTO_SCENES.get(template.title, "shelf"), rng)
    return task


PHOTO_SCENES = {
    "Opening checklist": "store",
    "Receive the morning delivery": "boxes",
    "Do‘konni ochish: tekshiruv ro‘yxati": "store",
    "Kassani yopish va Z-hisobot": "tags",
    "Ertalabki yukni qabul qilish": "boxes",
    "Javonlarni to‘ldirish va narx yorliqlari": "shelf",
}


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
    """A 1200 by 900 picture of shelves, boxes, a storefront, price tags or a window display."""
    background, colors = rng.choice(PALETTES)
    image = Image.new("RGB", (1200, 900), background)
    draw = ImageDraw.Draw(image)
    if kind in ("shelf", "tags", "store"):
        for row in range(4):
            top = 120 + row * 190
            draw.rectangle((60, top + 150, 1140, top + 166), fill=(150, 120, 90))
            x = 80
            while x < 1100:
                width = rng.randint(50, 110)
                height = rng.randint(80, 145)
                draw.rounded_rectangle(
                    (x, top + 150 - height, x + width, top + 148), radius=8, fill=rng.choice(colors)
                )
                if kind == "tags":
                    draw.rectangle((x + 6, top + 152, x + 46, top + 164), fill=(255, 255, 255))
                x += width + rng.randint(6, 18)
        if kind == "store":
            draw.rectangle((0, 0, 1200, 90), fill=(60, 54, 48))
            for lamp in range(6):
                draw.ellipse((90 + lamp * 190, 30, 150 + lamp * 190, 70), fill=(255, 236, 190))
    elif kind == "boxes":
        draw.rectangle((0, 640, 1200, 900), fill=(170, 160, 150))
        for _ in range(9):
            x, y = rng.randint(40, 980), rng.randint(330, 560)
            w, h = rng.randint(160, 240), rng.randint(140, 220)
            draw.rectangle(
                (x, y, x + w, y + h), fill=(196, 160, 112), outline=(140, 108, 70), width=6
            )
            draw.line((x, y + h // 2, x + w, y + h // 2), fill=(222, 196, 150), width=10)
    else:  # window
        draw.rectangle((80, 80, 1120, 820), fill=(214, 226, 236), outline=(90, 80, 70), width=24)
        for index in range(3):
            cx = 280 + index * 320
            draw.ellipse((cx - 50, 220, cx + 50, 320), fill=(232, 200, 170))
            draw.rounded_rectangle(
                (cx - 90, 320, cx + 90, 700), radius=40, fill=colors[index % len(colors)]
            )
        draw.rectangle((80, 80, 1120, 170), fill=colors[-1])
    image = image.filter(ImageFilter.GaussianBlur(1.2))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=82)
    return out.getvalue()
