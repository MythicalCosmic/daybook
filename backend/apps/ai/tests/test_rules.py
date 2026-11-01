"""The rules engine: dictated or typed instructions to task drafts, without a model (no DB)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from apps.ai.rules import (
    AMBIGUOUS,
    MAX_DRAFTS,
    NO_MATCH,
    Draft,
    Person,
    draft_tasks,
    to_latin,
)

TZ = ZoneInfo("Asia/Tashkent")
NOW = datetime(2026, 11, 2, 14, 5, tzinfo=TZ)  # a Monday
AUTHOR = 12
PEOPLE = [
    Person(12, "Bekzod", "Mirzayev"),  # the author, head of Chilonzor
    Person(15, "Alisher", "Valiyev"),
    Person(16, "Madina", "Saidova"),
    Person(17, "Jasur", "Tursunov"),
    Person(18, "Nigora", "Azimova"),
]
CROWD = [
    *PEOPLE,
    Person(19, "Alisher", "Karimov"),
    Person(20, "Bekmurod", "Olimov"),
    Person(21, "Sardor", "Qodirov"),
    Person(22, "Sarvar", "Ismoilov"),
]


def at(day: int, hour: int, minute: int = 0) -> datetime:
    """A moment in November 2026, Tashkent time (2 = today, 3 = tomorrow, 6 = Friday)."""
    return datetime(2026, 11, day, hour, minute, tzinfo=TZ)


def task(title, who=None, due=None, *, guess="", urgent=False, photo=False, problems=()):
    return Draft(
        title=title,
        assignee_id=who,
        assignee_guess=guess,
        due_at=due,
        priority="urgent" if urgent else "normal",
        proof="photo" if photo else "none",
        problems=list(problems),
    )


def drafts(text: str, lang: str, people=PEOPLE) -> list[Draft]:
    return draft_tasks(text, people=people, author_id=AUTHOR, now=NOW, lang=lang)


UZBEK = [
    pytest.param(
        "Alisher, ertaga soat 10 gacha muzlatgich haroratini tekshirib, rasmini yubor. "
        "Bekzod, bugun kechqurun kassani sanab qo‘y.",
        [
            task("Muzlatgich haroratini tekshirish", 15, at(3, 10), photo=True),
            task("Kassani sanash", 12, at(2, 18)),  # the author named himself: his own id
        ],
        id="the-contract-example",
    ),
    pytest.param(
        # What the Uzbek speech model really returned for it: lower case, ASCII apostrophes,
        # "bekmzod", "o'naqadir" for o‘nga qadar, "basmi ni yo'qdor" for rasmini yubor.
        "alisher ertaga soat o'naqadir muzlatgich haroratini tekshirib, basmi ni yo'qdor. "
        "bekmzod, bugun kechqurun kassani sanab qo'y.",
        [
            task("Muzlatgich haroratini tekshirish", 15, at(3, 10), photo=True),
            task("Kassani sanash", 12, at(2, 18)),
        ],
        id="real-speech-output",
    ),
    pytest.param(
        "madina opaga bugun kechqurun kassani sanab qo'y",
        [task("Kassani sanash", 16, at(2, 18))],
        id="lower-case-opa-and-ga",
    ),
    pytest.param(
        "alisherga ertaga ertalab yaroqlilik muddatini tekshir",
        [task("Yaroqlilik muddatini tekshirish", 15, at(3, 9))],
        id="dative-name-expiry-check",
    ),
    pytest.param(
        "Madina, yaroqlilik muddatini juma kuni tekshirib chiq.",
        [task("Yaroqlilik muddatini tekshirish", 16, at(6, 18))],
        id="date-in-the-middle-and-auxiliary",
    ),
    pytest.param(
        "Jasurga ayt, bugun soat 16 gacha Chilonzorga buyurtmani yetkazib bersin.",
        [task("Chilonzorga buyurtmani yetkazish", 17, at(2, 16))],
        id="tell-someone-delivery",
    ),
    pytest.param(
        "Nigora, ertaga ertalab qoldiqni sanab, rasmini yuboring.",
        [task("Qoldiqni sanash", 18, at(3, 9), photo=True)],
        id="stock-count-with-photo",
    ),
    pytest.param(
        "Alisher, javonni tartibga keltir, shoshilinch!",
        [task("Javonni tartibga keltirish", 15, urgent=True)],
        id="shelf-tidy-urgent",
    ),
    pytest.param(
        "O‘zim ertaga kassani sanayman.",
        [task("Kassani sanash", None, at(3, 18))],
        id="self-word",
    ),
    pytest.param(
        "Kassani sanab qo‘y",
        [task("Kassani sanash")],
        id="nobody-named-is-for-the-author",
    ),
    pytest.param(
        "Alisher va Madina, bugun kechqurun javonlarni tozalang.",
        [
            task("Javonlarni tozalash", 15, at(2, 18)),
            task("Javonlarni tozalash", 16, at(2, 18)),
        ],
        id="two-people-with-va",
    ),
    pytest.param(
        "1. Alisher, muzlatgich haroratini tekshir 2. Madina, kassani sana "
        "3. Jasur, dorilarni yetkazib ber",
        [
            task("Muzlatgich haroratini tekshirish", 15),
            task("Kassani sanash", 16),
            task("Dorilarni yetkazish", 17),
        ],
        id="numbered-list",
    ),
    pytest.param(
        "Alisher, ertaga omborni tekshir. Keyin qoldiqni sanab chiq.",
        [task("Omborni tekshirish", 15, at(3, 18)), task("Qoldiqni sanash", 15)],
        id="the-person-carries-over",
    ),
    pytest.param(
        "bekzod ertaga soat 9 gacha kassani sanab qo'ysin va keyin hisobotni yozsin",
        [task("Kassani sanash", 12, at(3, 9)), task("Hisobotni yozish", 12)],
        id="va-keyin-splits",
    ),
    pytest.param(
        "Sardor, ertaga soat 9 da kassani sana.",
        [task("Kassani sanash", None, at(3, 9), guess="Sardor", problems=[NO_MATCH])],
        id="unknown-name",
    ),
    pytest.param(
        "sardor aka ertaga soat 9 da omborni tekshirsin",
        [task("Omborni tekshirish", None, at(3, 9), guess="Sardor", problems=[NO_MATCH])],
        id="unknown-name-with-aka",
    ),
    pytest.param(
        "Alisher, bugun soat 9 da kassani sana.",
        [task("Kassani sanash", 15, at(2, 9))],  # passed: kept, the caller flags past_due
        id="a-time-that-has-passed",
    ),
    pytest.param(
        "Madinaga ertaga soat 11 gacha yaroqlilik muddatlarini tekshirish.",
        [task("Yaroqlilik muddatlarini tekshirish", 16, at(3, 11))],
        id="already-a-noun",
    ),
    pytest.param(
        "Bekzod, ertaga omborni tekshir. Keyin rasmini yubor.",
        [task("Omborni tekshirish", 12, at(3, 18), photo=True)],
        id="photo-only-sentence-joins-the-task-before",
    ),
    pytest.param(
        "Алишер, эртага соат 10 гача музлатгич ҳароратини текшириб, расмини юбор.",
        [task("Muzlatgich haroratini tekshirish", 15, at(3, 10), photo=True)],
        id="cyrillic-uzbek",
    ),
    pytest.param(
        "Мадина, бугун кечқурун кассани санаб қўй.",
        [task("Kassani sanash", 16, at(2, 18))],
        id="cyrillic-uzbek-auxiliary",
    ),
    pytest.param(
        "Jasur, zudlik bilan Yunusobodga dori yetkazib ber.",
        [task("Yunusobodga dori yetkazish", 17, urgent=True)],
        id="zudlik-bilan",
    ),
    pytest.param(
        "Alisher, muzlatgichni tozalab va javonni tartibga keltir.",
        [task("Muzlatgichni tozalash", 15), task("Javonni tartibga keltirish", 15)],
        id="va-after-a-verb-splits",
    ),
    pytest.param(
        "Madina, muzlatgich va javonni tozala.",
        [task("Muzlatgich va javonni tozalash", 16)],
        id="va-between-things-does-not-split",
    ),
    pytest.param(
        "Kassa!! ertaga",
        [task("Kassa", None, at(3, 18), urgent=True)],
        id="bangs",
    ),
    pytest.param(
        "nigora opa, indinga soat 10 gacha qoldiqni sanab chiqing",
        [task("Qoldiqni sanash", 18, at(4, 10))],
        id="indinga",
    ),
    pytest.param(
        "Alisher ertaga muzlatgichni soat 10 da tekshirsin",
        [task("Muzlatgichni tekshirish", 15, at(3, 10))],
        id="date-words-apart",
    ),
    pytest.param(
        "Alisher! Ertaga kassani sanab qo'y.",
        [task("Kassani sanash", 15, at(3, 18))],
        id="name-said-on-its-own",
    ),
    pytest.param(
        "Ertaga soat 10 da. Alisher, kassani sana.",
        [task("Kassani sanash", 15, at(3, 10))],
        id="deadline-said-first",
    ),
    pytest.param(
        "Kassani sana. Ertaga.",
        [task("Kassani sanash", None, at(3, 18))],
        id="deadline-said-after",
    ),
    pytest.param(
        "Alisher, buyurtmani bekor qil.",
        [task("Buyurtmani bekor qilish", 15)],  # "bekor" is not Bekzod
        id="bekor-is-a-word",
    ),
]
RUSSIAN = [
    pytest.param(
        "Алишер, завтра до 10 проверь температуру холодильника и пришли фото.",
        [task("Проверить температуру холодильника", 15, at(3, 10), photo=True)],
        id="fridge-temperature",
    ),
    pytest.param(
        "Мадина, сегодня вечером пересчитай кассу.",
        [task("Пересчитать кассу", 16, at(2, 18))],
        id="cash-count",
    ),
    pytest.param(
        "Скажи Алишеру, чтобы до пятницы проверил сроки годности.",
        [task("Проверить сроки годности", 15, at(6, 18))],
        id="expiry-dates-through-someone",
    ),
    pytest.param(
        "Джасур, срочно отвези заказ в аптеку на Юнусабад.",
        [task("Отвезти заказ в аптеку на Юнусабад", 17, urgent=True)],
        id="delivery-urgent",
    ),
    pytest.param(
        "Нигора, проведи инвентаризацию в пятницу утром.",
        [task("Провести инвентаризацию", 18, at(6, 9))],
        id="stock-count",
    ),
    pytest.param(
        "Мадине: разложи товар по полкам, а потом протри витрину.",
        [task("Разложить товар по полкам", 16), task("Протереть витрину", 16)],
        id="shelves-a-potom",
    ),
    pytest.param(
        "Бекзоду завтра к 9 утра принять поставку и сделать фото.",
        [task("Принять поставку", 12, at(3, 9), photo=True)],
        id="dative-name-and-photo",
    ),
]
ENGLISH = [
    pytest.param(
        "Alisher, check the fridge temperature by 10 tomorrow and send a photo.",
        [task("Check the fridge temperature", 15, at(3, 10), photo=True)],
        id="fridge-temperature",
    ),
    pytest.param(
        "Madina, count the cash this evening.",
        [task("Count the cash", 16, at(2, 18))],
        id="cash-count",
    ),
    pytest.param(
        "Ask Jasur to deliver the order to Yunusobod by 4pm, urgent.",
        [task("Deliver the order to Yunusobod", 17, at(2, 16), urgent=True)],
        id="delivery",
    ),
    pytest.param(
        "I'll do the stock count on Friday.",
        [task("Do the stock count", None, at(6, 18))],
        id="self",
    ),
    pytest.param(
        "Nigora: tidy the shelves, then check expiry dates.",
        [task("Tidy the shelves", 18), task("Check expiry dates", 18)],
        id="then-splits",
    ),
    pytest.param(
        "Sardor, take the delivery at 3pm.",
        [task("Take the delivery", None, at(2, 15), guess="Sardor", problems=[NO_MATCH])],
        id="unknown-name",
    ),
    pytest.param(
        "Madina, check the fridge and the showcase today.",
        [task("Check the fridge and the showcase", 16, at(2, 18))],
        id="and-the-does-not-split",
    ),
]


@pytest.mark.parametrize(("text", "expected"), UZBEK)
def test_uzbek(text, expected):
    assert drafts(text, "uz") == expected


@pytest.mark.parametrize(("text", "expected"), RUSSIAN)
def test_russian(text, expected):
    assert drafts(text, "ru") == expected


@pytest.mark.parametrize(("text", "expected"), ENGLISH)
def test_english(text, expected):
    assert drafts(text, "en") == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(
            "Alisher, muzlatgichni tekshir.",
            task("Muzlatgichni tekshirish", None, guess="Alisher", problems=[AMBIGUOUS]),
            id="two-alishers",
        ),
        pytest.param(
            "Alisher Karimov, muzlatgichni tekshir.",
            task("Muzlatgichni tekshirish", 19),
            id="the-surname-decides",
        ),
        pytest.param(
            "alishr, kassani sana",
            # misheard, and both Alishers are as near: their name as written
            task("Kassani sanash", None, guess="Alisher", problems=[AMBIGUOUS]),
            id="misheard-two-alishers",
        ),
        pytest.param(
            "bekmzod, omborni tekshir",
            task("Omborni tekshirish", 12),  # one edit from Bekzod, two from Bekmurod
            id="the-nearest-wins",
        ),
        pytest.param(
            "bekmurod, kassani sana",
            task("Kassani sanash", 20),
            id="exact-beats-near",
        ),
        pytest.param(
            "sardar, omborni tekshir",
            # one edit from Sardor and one from Sarvar: nobody is picked
            task("Omborni tekshirish", None, guess="Sardar", problems=[AMBIGUOUS]),
            id="a-tie-is-ambiguous",
        ),
        pytest.param(
            "Sarvarga ayt, javonni tozalasin",
            task("Javonni tozalash", 22),
            id="sarvarga-ayt",
        ),
    ],
)
def test_names_in_a_crowd(text, expected):
    assert drafts(text, "uz", CROWD) == [expected]


@pytest.mark.parametrize(
    ("text", "names"),
    [
        ("alishr ertaga kassani sana", [15]),  # first word: one letter off is enough
        ("bekmzod bugun omborni tekshirsin", [12]),
        ("alshir ertaga kassani sana", [None]),  # two off without a comma: not a name
        ("alshir, ertaga kassani sana", [15]),  # ...with one, it is
        ("kassani sanab, bekor qil", [None]),  # "bekor" is never Bekzod
    ],
)
def test_misheard_names_need_a_place_where_a_name_is_expected(text, names):
    assert [draft.assignee_id for draft in drafts(text, "uz")] == names


def test_a_misheard_name_goes_to_the_strictly_nearest_person_only():
    people = [Person(1, "Nodir", "Aliyev"), Person(2, "Nodira", "Boboyeva")]

    def heard(text):
        [draft] = draft_tasks(text, people=people, author_id=9, now=NOW, lang="uz")
        return draft.assignee_id, draft.problems

    assert heard("nodiro, kassani sana") == (None, [AMBIGUOUS])  # one edit from both
    assert heard("nodr, kassani sana") == (1, [])  # one from Nodir, two from Nodira
    assert heard("nodirra, kassani sana") == (2, [])  # one from Nodira, two from Nodir


@pytest.mark.parametrize("text", ["", "   ", ".", "?!", "1.", "Alisher", "ertaga", "va"])
def test_nothing_to_do_gives_no_drafts(text):
    assert drafts(text, "uz") == []


def test_at_most_ten_drafts():
    text = "\n".join(f"{n}. Alisher, quti {n} ni ol" for n in range(1, 13))

    found = drafts(text, "uz")

    assert len(found) == MAX_DRAFTS
    assert [draft.title for draft in found[:2]] == ["Quti 1 ni olish", "Quti 2 ni olish"]


def test_the_same_text_gives_the_same_drafts():
    text = "alisher ertaga soat 10 da muzlatgichni tekshirsin, madina kassani sanasin"

    assert drafts(text, "uz") == drafts(text, "uz")


def test_the_text_is_read_not_changed():
    text = "alisher ertaga soat o'naqadir muzlatgichni tekshir"
    kept = str(text)

    drafts(text, "uz")

    assert text == kept


def test_now_must_be_aware():
    with pytest.raises(ValueError):
        draft_tasks(
            "Kassani sana", people=PEOPLE, author_id=AUTHOR, now=datetime(2026, 11, 2), lang="uz"
        )


def test_due_times_are_in_the_companys_zone():
    [draft] = drafts("Alisher, ertaga soat 10 da kassani sana", "uz")

    assert draft.due_at.utcoffset() == timedelta(hours=5)


def test_uzbek_titles_write_o_and_g_with_the_turned_comma():
    [draft] = drafts("Alisher, to'g'ri narxni yozib qo'y", "uz")

    assert draft.title == "To‘g‘ri narxni yozish"


@pytest.mark.parametrize(
    ("cyrillic", "latin"),
    [
        ("Алишер", "Alisher"),
        ("Эртага соат 10 гача", "Ertaga soat 10 gacha"),
        ("Ғайрат", "G‘ayrat"),
        ("ўзим", "o‘zim"),
        ("Ёқуб", "Yoqub"),
        ("Евгений", "Yevgeniy"),
        ("Валиев", "Valiyev"),
        ("қўйинг", "qo‘ying"),
        ("маълумот", "ma’lumot"),
        ("ШЕР", "SHER"),
        ("Latin stays as it is", "Latin stays as it is"),
    ],
)
def test_to_latin(cyrillic, latin):
    assert to_latin(cyrillic) == latin
