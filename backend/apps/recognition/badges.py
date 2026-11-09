"""The badge catalogue (docs/PLAN-LEARNING.md §7.3): what can be earned and how.

Each badge has a lucide icon name (the dashboard and the mini app draw it), a tier (bronze,
silver, gold) and its name and how to earn it in English, Uzbek and Russian: the catalogue is
part of the product, like the level names (`rules.LEVEL_NAMES`). A badge comes once per person;
`topic_expert` once per topic (`ref` = the topic id) and `top3_month` once per month (`ref` =
"YYYY-MM"). The rules that award them live in `apps.recognition.progress`.

    badges.CATALOGUE["perfect_score"].name()          # in the active language
    badges.title("top3_month", "2026-11")              # "Top three of the month: November 2026"
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.recognition.rules import language

BRONZE, SILVER, GOLD = "bronze", "silver", "gold"
TIERS = (BRONZE, SILVER, GOLD)


@dataclass(frozen=True)
class Badge:
    key: str
    icon: str  # a lucide icon name
    tier: str
    names: dict[str, str]
    descriptions: dict[str, str]
    per_ref: bool = False  # earned again for another topic or month

    def name(self, code: str | None = None) -> str:
        return self.names[language(code)]

    def description(self, code: str | None = None) -> str:
        return self.descriptions[language(code)]


def _badge(key, icon, tier, en, uz, ru, *, per_ref=False) -> Badge:
    return Badge(
        key=key,
        icon=icon,
        tier=tier,
        names={"en": en[0], "uz": uz[0], "ru": ru[0]},
        descriptions={"en": en[1], "uz": uz[1], "ru": ru[1]},
        per_ref=per_ref,
    )


BADGES: tuple[Badge, ...] = (
    _badge(
        "first_lesson",
        "circle-play",
        BRONZE,
        ("First lesson", "Watch a video lesson to the end."),
        ("Birinchi dars", "Video darsni oxirigacha ko‘ring."),
        ("Первый урок", "Досмотрите видеоурок до конца."),
    ),
    _badge(
        "first_quiz",
        "clipboard-check",
        BRONZE,
        ("First test", "Pass a test."),
        ("Birinchi test", "Testdan o‘ting."),
        ("Первый тест", "Сдайте тест."),
    ),
    _badge(
        "perfect_score",
        "target",
        SILVER,
        ("Perfect score", "Answer every question of a test right."),
        ("A’lo natija", "Testning barcha savollariga to‘g‘ri javob bering."),
        ("Без единой ошибки", "Ответьте верно на все вопросы теста."),
    ),
    _badge(
        "course_finisher",
        "graduation-cap",
        SILVER,
        ("Course finished", "Finish a course: every required step."),
        ("Kurs tugatildi", "Kursning barcha majburiy qadamlarini bajaring."),
        ("Курс пройден", "Пройдите все обязательные шаги курса."),
    ),
    _badge(
        "five_courses",
        "library",
        GOLD,
        ("Five courses", "Finish five courses."),
        ("Beshta kurs", "Beshta kursni tugating."),
        ("Пять курсов", "Пройдите пять курсов."),
    ),
    _badge(
        "streak_7",
        "flame",
        BRONZE,
        (
            "A week in a row",
            "Learn something on 7 workdays in a row. Days off and leave don't break it.",
        ),
        (
            "Bir hafta ketma-ket",
            "7 ish kuni ketma-ket nimadir o‘rganing. Dam olish kunlari va ta’til uzmaydi.",
        ),
        (
            "Неделя подряд",
            "Учитесь 7 рабочих дней подряд. Выходные и отпуск серию не прерывают.",
        ),
    ),
    _badge(
        "streak_30",
        "flame",
        SILVER,
        ("A month in a row", "Learn something on 30 workdays in a row."),
        ("Bir oy ketma-ket", "30 ish kuni ketma-ket nimadir o‘rganing."),
        ("Месяц подряд", "Учитесь 30 рабочих дней подряд."),
    ),
    _badge(
        "streak_100",
        "flame",
        GOLD,
        ("100 days in a row", "Learn something on 100 workdays in a row."),
        ("100 kun ketma-ket", "100 ish kuni ketma-ket nimadir o‘rganing."),
        ("100 дней подряд", "Учитесь 100 рабочих дней подряд."),
    ),
    _badge(
        "daily_10",
        "lightbulb",
        SILVER,
        ("Ten right answers", "Answer the question of the day right ten times."),
        ("O‘nta to‘g‘ri javob", "Kun savoliga o‘n marta to‘g‘ri javob bering."),
        ("Десять верных ответов", "Ответьте верно на вопрос дня десять раз."),
    ),
    _badge(
        "topic_expert",
        "brain",
        GOLD,
        ("Topic expert", "Reach 90% in a topic over at least 10 answers."),
        ("Mavzu bilimdoni", "Bir mavzuda kamida 10 ta javob bilan 90% natijaga erishing."),
        ("Знаток темы", "Наберите 90% по теме, ответив хотя бы на 10 вопросов."),
        per_ref=True,
    ),
    _badge(
        "early_bird",
        "sunrise",
        SILVER,
        ("Early bird", "Finish a mandatory course within three days of getting it."),
        (
            "Tezkor o‘quvchi",
            "Majburiy kursni biriktirilganidan keyin uch kun ichida tugating.",
        ),
        ("Ранняя пташка", "Пройдите обязательный курс за три дня после назначения."),
    ),
    _badge(
        "helper",
        "hand-heart",
        SILVER,
        ("Kind colleague", "Thank your colleagues 10 times."),
        ("Mehribon hamkasb", "Hamkasblaringizga 10 marta rahmat ayting."),
        ("Добрый коллега", "Поблагодарите коллег 10 раз."),
    ),
    _badge(
        "thanked",
        "heart-handshake",
        SILVER,
        ("Appreciated", "Get 10 thanks from colleagues."),
        ("Qadrli hamkasb", "Hamkasblardan 10 ta rahmat oling."),
        ("Ценный коллега", "Получите 10 благодарностей от коллег."),
    ),
    _badge(
        "on_time_week",
        "calendar-check",
        SILVER,
        ("On time all week", "Finish every task of a work week on time, at least 5 of them."),
        (
            "Hafta bo‘yi o‘z vaqtida",
            "Ish haftasidagi barcha vazifalarni o‘z vaqtida bajaring, kamida 5 ta.",
        ),
        ("Вся неделя вовремя", "Выполните вовремя все задачи рабочей недели, не меньше 5."),
    ),
    _badge(
        "top3_month",
        "trophy",
        GOLD,
        ("Top three of the month", "Be one of the three with the most points in a month."),
        (
            "Oyning eng yaxshi uchligi",
            "Bir oyda eng ko‘p ball to‘plagan uch kishidan biri bo‘ling.",
        ),
        ("Тройка лучших месяца", "Войдите в тройку лидеров по баллам за месяц."),
        per_ref=True,
    ),
)
CATALOGUE: dict[str, Badge] = {badge.key: badge for badge in BADGES}

MONTHS = {
    "en": (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ),
    "uz": (
        "yanvar",
        "fevral",
        "mart",
        "aprel",
        "may",
        "iyun",
        "iyul",
        "avgust",
        "sentabr",
        "oktabr",
        "noyabr",
        "dekabr",
    ),
    "ru": (
        "январь",
        "февраль",
        "март",
        "апрель",
        "май",
        "июнь",
        "июль",
        "август",
        "сентябрь",
        "октябрь",
        "ноябрь",
        "декабрь",
    ),
}


def month_label(ref: str, code: str | None = None) -> str:
    """ "2026-11" as "November 2026" / "2026-yil noyabr" / "ноябрь 2026"."""
    try:
        year, month = (int(part) for part in ref.split("-"))
        name = MONTHS[language(code)][month - 1]
    except ValueError, IndexError:
        return ref
    lang = language(code)
    if lang == "uz":
        return f"{year}-yil {name}"
    return f"{name} {year}"


def title(key: str, ref: str = "", *, topic: str | None = None, code: str | None = None) -> str:
    """The badge's name for one award: with the topic or the month when it has one."""
    badge = CATALOGUE.get(key)
    if badge is None:
        return key
    name = badge.name(code)
    if key == "topic_expert" and topic:
        return f"{name}: {topic}"
    if key == "top3_month" and ref:
        return f"{name}: {month_label(ref, code)}"
    return name
