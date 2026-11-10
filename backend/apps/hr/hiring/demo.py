"""Demo Dorixona's hiring (called from `apps.hr.demo.seed`; the story is apps/core/demo_plan.py).

- **Farmatsevt, Chilonzor**: open for twelve days, until 18 days from now, asks for the diploma.
  Bekzod (Chilonzor's head) runs it: six applicants, one new today and one yesterday, one he
  is screening, one invited to an interview on Thursday, one with an offer, one turned down.
- **Kassir, Yunusobod**: open for a week; Farrux runs it. Three applicants: new, screening and
  invited to an interview. Its position comes with the Cashier access, which only an owner may
  give, so the Hire button tells Farrux to ask Dilnoza.
- **Farmatsevt, Yunusobod**: closed three weeks ago. Kamola (who joined 21 days ago) was hired
  through it; the other applicant didn't come to the interview.
- **Kuryer, Chilonzor**: a draft the owner started yesterday.

Applicants are invented people (Telegram ids 3021 to 3030, which `seed_demo --reset` removes),
who write in Uzbek or Russian. Everything goes through the services as of its moment, so the
history, the audit log and the team's inbox read like weeks of real hiring.
"""

import io
from datetime import time, timedelta
from decimal import Decimal

from PIL import Image, ImageDraw

from apps.accounts.models import User
from apps.core import demo_plan as plan
from apps.core.demo_time import moment
from apps.hr.hiring import questions, services
from apps.hr.models import Applicant, ApplicantEvent, Vacancy
from apps.members.models import AccessRole, Position

CASHIER = "Kassir"
# Telegram ids of the applicants (inside seed_demo's clean-up range, 3001 to 3040).
FIRST_ID = 3021

PHARMACIST_QUESTIONS = [
    {"text": "Farmatsevtik ma’lumotingiz bormi (kollej yoki institut)?", "kind": "yes_no"},
    {
        "text": "Qaysi smena sizga qulay?",
        "kind": "choice",
        "options": ["Ertalabki (08:00–20:00)", "Kechki (10:00–22:00)", "Farqi yo‘q"],
    },
    {"text": "Dorixonada necha yil ishlagansiz?", "kind": "number"},
    {"text": "Mutaxassis sertifikatingiz amal qiladimi?", "kind": "yes_no"},
    {"text": "O‘zingiz haqingizda qisqacha yozing", "kind": "text", "required": False},
]
CASHIER_QUESTIONS = [
    {"text": "Kassa apparati bilan ishlaganmisiz?", "kind": "yes_no"},
    {
        "text": "Qaysi smena qulay?",
        "kind": "choice",
        "options": ["Kunduzgi (08:00–20:00)", "Tungi (20:00–08:00)", "Farqi yo‘q"],
    },
    {"text": "Qachondan ishga chiqa olasiz?", "kind": "text"},
]
COURIER_QUESTIONS = [
    {"text": "Velosipedingiz yoki skuteringiz bormi?", "kind": "yes_no"},
    {"text": "Chilonzor tumanini yaxshi bilasizmi?", "kind": "yes_no"},
]

# Who applied for the open pharmacist's job at Chilonzor: (name, language, source, days ago,
# the hour (or, today, how many hours ago), answers, a diploma photo, then what happened:
# (days ago, hour, stage or "note", the message to them, the reason, or the note)).
CHILONZOR = [
    (
        "Ulug‘bek Hamroyev",
        "uz",
        "link",
        10,
        time(19, 12),
        ["no", "Farqi yo‘q", "1", "no", ""],
        False,
        [(9, time(11, 0), "rejected", "Farmatsevtik ma’lumoti yo‘q")],
    ),
    (
        "Мадина Ахмедова",
        "ru",
        "qr",
        9,
        time(21, 30),
        [
            "yes",
            "Ertalabki (08:00–20:00)",
            "7",
            "yes",
            "Работала провизором в аптечной сети 7 лет, знаю учёт рецептурных препаратов.",
        ],
        True,
        [
            (8, time(10, 20), "screening", ""),
            (8, time(10, 25), "note", "Qo‘ng‘iroq qildim: tajribasi katta, ruschada gaplashadi"),
            (
                7,
                time(12, 0),
                "interview",
                "Приходите в пятницу в 11:00 в филиал Чиланзар, возьмите диплом.",
            ),
            (
                3,
                time(16, 40),
                "offer",
                "Предлагаем 6 000 000 сум в месяц, график 2/2. Ждём ваш ответ.",
            ),
        ],
    ),
    (
        "Javohir To‘xtayev",
        "uz",
        "link",
        6,
        time(13, 5),
        [
            "yes",
            "Kechki (10:00–22:00)",
            "3",
            "yes",
            "Farmatsevtika kollejini 2022-yilda bitirganman.",
        ],
        True,
        [
            (5, time(9, 30), "screening", ""),
            (
                2,
                time(15, 10),
                "interview",
                "Payshanba kuni soat 10:00 da suhbatga keling. Manzil: Chilonzor 9-kvartal, 14-uy.",
            ),
        ],
    ),
    (
        "Елена Ким",
        "ru",
        "qr",
        4,
        time(20, 45),
        ["yes", "Farqi yo‘q", "5", "yes", ""],
        False,
        [
            (3, time(10, 0), "screening", ""),
            (3, time(10, 5), "note", "Sertifikati 2027-yilgacha amal qiladi"),
        ],
    ),
    (
        "Dilfuza Raximova",
        "uz",
        "link",
        1,
        time(18, 30),
        ["yes", "Ertalabki (08:00–20:00)", "2", "no", "Yaqinda bitirganman, tez o‘rganaman."],
        False,
        [],
    ),
    (
        "Sanjar Qosimov",
        "uz",
        "qr",
        0,
        3,  # hours ago
        ["yes", "Farqi yo‘q", "4", "yes", ""],
        False,
        [],
    ),
]
YUNUSOBOD = [
    (
        "Тимур Хасанов",
        "ru",
        "link",
        5,
        time(11, 20),
        ["yes", "Tungi (20:00–08:00)", "С понедельника"],
        False,
        [
            (4, time(9, 45), "screening", ""),
            (1, time(17, 0), "interview", "Приходите завтра в 09:30 в филиал Юнусабад."),
        ],
    ),
    (
        "Ruxshona Abdullayeva",
        "uz",
        "link",
        2,
        time(14, 0),
        ["no", "Kunduzgi (08:00–20:00)", "Keyingi haftadan"],
        False,
        [(1, time(10, 30), "screening", "")],
    ),
    (
        "Nilufar Sobirova",
        "uz",
        "qr",
        0,
        5,  # hours ago
        ["yes", "Farqi yo‘q", "Hoziroq"],
        False,
        [],
    ),
]
PHONES = (
    "+998901234401",
    "+998935550202",
    "+998977001303",
    "+998946662404",
    "+998901117505",
    "+998998880606",
    "+998935553707",
    "+998977774808",
    "+998946669909",
    "+998901112010",
)


def seed(company, people, now) -> None:
    story = plan.Plan(company, people, now)
    owner, bekzod, farrux = people["owner"], story.member("manager"), story.member("farrux")
    chilonzor, yunusobod = story.branches["C"], story.branches["Y"]
    pharmacist = Position.objects.get(company=company, name=plan.PHARMACIST)
    cashier = _cashier_position(company)
    ids = iter(range(FIRST_ID, FIRST_ID + 20))
    phones = iter(PHONES)

    # Farmatsevt at Chilonzor, Bekzod's.
    with moment(story.at(story.day(-13), time(9, 40))):
        open_post = services.create_vacancy(
            company,
            by=bekzod,
            title="Farmatsevt",
            position=pharmacist,
            branch=chilonzor,
            description=(
                "Chilonzor filialimizga farmatsevt kerak: retsept bo‘yicha dori berish, "
                "maslahat, kassa va qabul. 2/2 smena jadvali, rasmiy ishga joylash, "
                "oylik o‘z vaqtida. Farmatsevtika kolleji yoki instituti diplomi shart."
            ),
            salary_from=Decimal("4500000"),
            salary_to=Decimal("6000000"),
            questions=PHARMACIST_QUESTIONS,
            asks_document=True,
            closes_on=story.day(18),
        )
    with moment(story.at(story.day(-12), time(10, 5))):
        services.set_status(open_post, Vacancy.Status.OPEN, by=bekzod)
    for row in CHILONZOR:
        _applicant(story, open_post, bekzod, next(ids), next(phones), row)
    Vacancy.objects.filter(pk=open_post.pk).update(link_opens=47)

    # Kassir at Yunusobod, Farrux's.
    with moment(story.at(story.day(-7), time(9, 0))):
        till_post = services.create_vacancy(
            company,
            by=farrux,
            publish=True,
            title="Kassir",
            position=cashier,
            branch=yunusobod,
            description=(
                "Yunusobod filialimizga (24 soat ishlaydi) kassir kerak: to‘lovlarni qabul "
                "qilish, kassa hisoboti, mijozlar bilan muloyim muomala."
            ),
            salary_from=Decimal("3500000"),
            salary_to=Decimal("4200000"),
            questions=CASHIER_QUESTIONS,
        )
    for row in YUNUSOBOD:
        _applicant(story, till_post, farrux, next(ids), next(phones), row)
    Vacancy.objects.filter(pk=till_post.pk).update(link_opens=23)

    _closed_post(story, farrux, pharmacist, yunusobod, next(ids))

    with moment(story.at(story.day(-1), time(18, 10))):
        services.create_vacancy(
            company,
            by=owner,
            title="Kuryer (velosipedda)",
            branch=chilonzor,
            description="Chilonzor tumani bo‘ylab dori yetkazib berish, kunduzgi smena.",
            salary_from=Decimal("3000000"),
            questions=COURIER_QUESTIONS,
        )


def _cashier_position(company) -> Position:
    """The cashier's job title, with the Cashier access (only an owner gives it)."""
    role = AccessRole.objects.filter(company=company, name="Cashier").first()
    position, _ = Position.objects.get_or_create(
        company=company, name=CASHIER, defaults={"order": 99, "role": role}
    )
    return position


def _person(telegram_id: int, name: str, language: str) -> User:
    first, _space, last = name.partition(" ")
    user, _ = User.objects.get_or_create(
        telegram_id=telegram_id,
        defaults={
            "username": f"tg{telegram_id}",
            "first_name": first,
            "last_name": last,
            "language": language,
        },
    )
    return user


def _applicant(story, vacancy, by, telegram_id, phone, row) -> Applicant:
    name, language, source, days_ago, hour, answers, photo, steps = row
    user = _person(telegram_id, name, language)
    if isinstance(hour, int):
        applied = story.now.replace(microsecond=0) - timedelta(hours=hour)
    else:
        applied = story.at(story.day(-days_ago), hour)
    rows = [
        questions.answer_row(question, answer)
        for question, answer in zip(vacancy.questions, answers, strict=True)
    ]
    with moment(applied):
        applicant = services.apply(
            vacancy.pk,
            user,
            name=name,
            phone=phone,
            answers=rows,
            source=source,
            document=_diploma(name) if photo else None,
        )
    for step_days, step_hour, stage, text in steps:
        with moment(story.at(story.day(-step_days), step_hour)):
            if stage == "note":
                services.add_note(applicant, by=by, text=text)
            elif stage == "rejected":
                applicant = services.reject(applicant, by=by, reason=text)
            else:
                applicant = services.move(applicant, stage, by=by, message=text)
    return applicant


def _closed_post(story, farrux, pharmacist, yunusobod, telegram_id) -> None:
    """Three weeks ago: the job Kamola got. The other applicant didn't come to the interview."""
    company = story.company
    with moment(story.at(story.day(-40), time(9, 30))):
        post = services.create_vacancy(
            company,
            by=farrux,
            publish=True,
            title="Farmatsevt",
            position=pharmacist,
            branch=yunusobod,
            description="Yunusobod filialiga kunduzgi smenaga farmatsevt kerak.",
            salary_from=Decimal("4500000"),
            questions=PHARMACIST_QUESTIONS[:3],
            asks_document=True,
        )
    missing = (
        "Шохрух Назаров",
        "ru",
        "link",
        33,
        time(12, 40),
        ["yes", "Farqi yo‘q", "2"],
        False,
        [
            (32, time(10, 0), "interview", "Ertaga soat 11:00 da suhbatga kutamiz."),
            (30, time(18, 0), "rejected", "Suhbatga kelmadi, qo‘ng‘iroqqa javob bermadi"),
        ],
    )
    _applicant(story, post, farrux, telegram_id, "+998935559911", missing)
    kamola = story.member("kamola")
    if kamola is not None:
        _hired_before(story, post, farrux, kamola)
    with moment(story.at(story.day(-20), time(9, 0))):
        services.set_status(post, Vacancy.Status.CLOSED, by=farrux)
    Vacancy.objects.filter(pk=post.pk).update(link_opens=31)


def _hired_before(story, post, farrux, kamola) -> None:
    """Kamola's application, from her answers to her first day (she is on the team already, so
    her record is written as it was then rather than hired again)."""
    steps = [
        (-35, time(20, 10), "", "new"),
        (-34, time(9, 50), "new", "screening"),
        (-31, time(15, 0), "screening", "interview"),
        (-27, time(11, 30), "interview", "offer"),
        (-21, time(9, 0), "offer", "hired"),
    ]
    applied = story.at(story.day(-35), time(20, 10))
    with moment(applied):
        applicant = Applicant.objects.create(
            company=story.company,
            vacancy=post,
            user=kamola.user,
            name=kamola.full_name,
            phone=kamola.user.phone,
            telegram_username=kamola.user.telegram_username,
            language=kamola.user.language,
            answers=[
                questions.answer_row(question, answer)
                for question, answer in zip(
                    post.questions, ["yes", "Ertalabki (08:00–20:00)", "4"], strict=True
                )
            ],
            source=Applicant.Source.QR,
            stage=Applicant.Stage.NEW,
            stage_changed_at=applied,
        )
    for offset, hour, was, stage in steps:
        at = story.at(story.day(offset), hour)
        with moment(at):
            ApplicantEvent.objects.create(
                company=story.company,
                applicant=applicant,
                kind=ApplicantEvent.Kind.APPLIED if not was else ApplicantEvent.Kind.MOVED,
                from_stage=was,
                to_stage=stage,
                by=farrux if was else None,
                notified=stage in ("interview", "offer", "hired"),
            )
    Applicant.objects.filter(pk=applicant.pk).update(
        stage=Applicant.Stage.HIRED,
        stage_changed_at=at,
        hired_at=at,
        membership=kamola,
    )


def _diploma(name: str) -> bytes:
    """A made-up diploma photo: a cream sheet with a border, a seal and lines of "text"."""
    sheet = Image.new("RGB", (1200, 850), (246, 240, 226))
    draw = ImageDraw.Draw(sheet)
    draw.rectangle((30, 30, 1170, 820), outline=(150, 112, 60), width=10)
    draw.rectangle((60, 60, 1140, 790), outline=(190, 160, 110), width=3)
    draw.rectangle((380, 120, 820, 160), fill=(120, 90, 50))
    for index, width in enumerate((700, 640, 760, 520, 690, 600)):
        top = 240 + index * 62
        draw.rectangle((250, top, 250 + width, top + 18), fill=(110, 100, 90))
    draw.ellipse((880, 600, 1060, 780), outline=(168, 90, 39), width=8)
    draw.ellipse((915, 635, 1025, 745), fill=(212, 150, 110))
    out = io.BytesIO()
    sheet.save(out, "JPEG", quality=80)
    return out.getvalue()
