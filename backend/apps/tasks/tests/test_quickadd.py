"""Quick add (apps.tasks.quickadd): the cases from research R2 §6.6, plus the 2027 letters."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from apps.tasks.quickadd import parse

TZ = ZoneInfo("Asia/Tashkent")
WED_10 = datetime(2026, 10, 21, 10, 0, tzinfo=TZ)  # a Wednesday morning
WED_1910 = datetime(2026, 10, 21, 19, 10, tzinfo=TZ)  # the same evening
THU_01 = datetime(2026, 10, 22, 1, 0, tzinfo=TZ)  # a night shift, just after midnight
FRI_10 = datetime(2026, 10, 23, 10, 0, tzinfo=TZ)
DEC31_15 = datetime(2026, 12, 31, 15, 0, tzinfo=TZ)

# (now, typed, title, due as "YYYY-MM-DD HH:MM" or None, other fields that must match)
CASES = [
    # Uzbek (Latin), the date at the end or at the start
    (
        WED_10,
        "Narx yorliqlarini yangilash ertaga 10:00",
        "Narx yorliqlarini yangilash",
        "2026-10-22 10:00",
        {},
    ),
    (
        WED_10,
        "Ertaga soat 9 da nakladnoyni qabul qilish",
        "Nakladnoyni qabul qilish",
        "2026-10-22 09:00",
        {},
    ),
    (WED_10, "Kassani topshirish soat beshda", "Kassani topshirish", "2026-10-21 17:00", {}),
    (WED_10, "Kassani sanash 18:00 gacha", "Kassani sanash", "2026-10-21 18:00", {}),
    (WED_10, "Kassani sanash - bugun soat 18 ga qadar", "Kassani sanash", "2026-10-21 18:00", {}),
    (
        WED_10,
        "Muzlatgich haroratini yozish kechqurun",
        "Muzlatgich haroratini yozish",
        "2026-10-21 18:00",
        {},
    ),
    (WED_10, "Dori buyurtmasi indinga ertalab", "Dori buyurtmasi", "2026-10-23 09:00", {}),
    (WED_10, "Hisobot dushanba kuni", "Hisobot", "2026-10-26 18:00", {"guessed_time": True}),
    (WED_10, "Hisobot keyingi juma", "Hisobot", "2026-10-30 18:00", {}),
    (WED_10, "Hisobot jumagacha", "Hisobot", "2026-10-23 18:00", {}),
    (WED_10, "Qo‘ng‘iroq qilish 2 soatdan keyin", "Qo‘ng‘iroq qilish", "2026-10-21 12:00", {}),
    (WED_10, "Qo‘ng‘iroq qilish yarim soatdan keyin", "Qo‘ng‘iroq qilish", "2026-10-21 10:30", {}),
    (
        WED_10,
        "Qo‘ng‘iroq qilish bir yarim soatdan keyin",
        "Qo‘ng‘iroq qilish",
        "2026-10-21 11:30",
        {},
    ),
    (WED_10, "Tekshirish o‘n besh daqiqadan keyin", "Tekshirish", "2026-10-21 10:15", {}),
    (WED_10, "Javob berish 2 soat ichida", "Javob berish", "2026-10-21 12:00", {}),
    (WED_10, "Yig‘ilish 25-oktabr soat 15:00 da", "Yig‘ilish", "2026-10-25 15:00", {}),
    (WED_10, "Yig‘ilish 5-noyabrda", "Yig‘ilish", "2026-11-05 18:00", {}),
    (WED_10, "Inventarizatsiya hafta oxirida", "Inventarizatsiya", "2026-10-24 18:00", {}),
    (WED_10, "Sanitariya kuni oy oxirida", "Sanitariya kuni", "2026-10-31 18:00", {}),
    (WED_10, "Inventarizatsiya keyingi hafta", "Inventarizatsiya", "2026-10-26 18:00", {}),
    (WED_10, "Kassa 9 yarimda", "Kassa", "2026-10-22 09:30", {"rolled": True}),
    (WED_10, "Yetkazish tushdan keyin", "Yetkazish", "2026-10-21 15:00", {}),
    (WED_10, "Kassa hisoboti kun oxirigacha", "Kassa hisoboti", "2026-10-21 18:00", {}),
    (WED_10, "Kassa hisoboti kechqurun soat 7 da", "Kassa hisoboti", "2026-10-21 19:00", {}),
    (
        WED_10,
        "Seyfni tekshirish kechasi 2 da",
        "Seyfni tekshirish",
        "2026-10-22 02:00",
        {"rolled": True},
    ),
    (
        WED_10,
        "Muzlatgichni tekshirish har kuni 9:00",
        "Muzlatgichni tekshirish",
        "2026-10-22 09:00",
        {"repeat": "daily", "rolled": True},
    ),
    (
        WED_10,
        "Har kuni soat 20:30 da muzlatgich harorati",
        "Muzlatgich harorati",
        "2026-10-21 20:30",
        {"repeat": "daily"},
    ),
    (
        WED_10,
        "Haftalik hisobot har dushanba soat 10 da",
        "Haftalik hisobot",
        "2026-10-26 10:00",
        {"repeat": "weekly"},
    ),
    (WED_10, "Kassani tekshirish shoshilinch", "Kassani tekshirish", None, {"priority": "urgent"}),
    (WED_10, "Ertaga 18:00 gacha kassani sanash", "Kassani sanash", "2026-10-22 18:00", {}),
    (WED_10, "Kassani sanash ertaga, 18:00", "Kassani sanash", "2026-10-22 18:00", {}),
    (
        WED_10,
        "Bugun kechqurun 8 da kassani topshirish",
        "Kassani topshirish",
        "2026-10-21 20:00",
        {},
    ),
    (WED_10, "Kassa soat toʻqqizda", "Kassa", "2026-10-22 09:00", {"rolled": True}),  # U+02BB
    (
        WED_10,
        "Tekshirish o`n besh daqiqadan keyin",
        "Tekshirish",
        "2026-10-21 10:15",
        {},
    ),  # backtick
    (WED_10, "Kassa soat 12 da", "Kassa", "2026-10-21 12:00", {}),
    (WED_10, "Kassa 00:30", "Kassa", "2026-10-22 00:30", {"rolled": True}),
    (WED_10, "Kassa ertaga 9:00!!", "Kassa", "2026-10-22 09:00", {"priority": "urgent"}),
    (
        WED_10,
        "Juma namozi",
        "Namozi",
        "2026-10-23 18:00",
        {},
    ),  # known: undo by tapping the highlight
    # Uzbek (Cyrillic)
    (WED_10, "Касса ҳисоботи эртага соат 10 да", "Касса ҳисоботи", "2026-10-22 10:00", {}),
    (WED_10, "Дори қабул қилиш душанба куни эрталаб", "Дори қабул қилиш", "2026-10-26 09:00", {}),
    # Russian
    (WED_10, "Позвонить поставщику завтра в 10", "Позвонить поставщику", "2026-10-22 10:00", {}),
    (
        WED_10,
        "В пятницу в 15:00 сверка с дистрибьютором",
        "Сверка с дистрибьютором",
        "2026-10-23 15:00",
        {},
    ),
    (
        WED_10,
        "Проверить сроки годности до пятницы",
        "Проверить сроки годности",
        "2026-10-23 18:00",
        {},
    ),
    (WED_10, "Сдать кассу сегодня до 18", "Сдать кассу", "2026-10-21 18:00", {}),
    (WED_10, "Заказ через 2 часа", "Заказ", "2026-10-21 12:00", {}),
    (WED_10, "Перезвонить через полчаса", "Перезвонить", "2026-10-21 10:30", {}),
    (WED_10, "Перезвонить через полтора часа", "Перезвонить", "2026-10-21 11:30", {}),
    (WED_10, "Ответить в течение часа", "Ответить", "2026-10-21 11:00", {}),
    (WED_10, "Отчёт через 2 дня в 10:00", "Отчёт", "2026-10-23 10:00", {}),
    (WED_10, "Инвентаризация через неделю", "Инвентаризация", "2026-10-28 18:00", {}),
    (WED_10, "Инвентаризация в конце месяца", "Инвентаризация", "2026-10-31 18:00", {}),
    (WED_10, "Встреча послезавтра вечером", "Встреча", "2026-10-23 18:00", {}),
    (WED_10, "Планёрка в следующий понедельник в 9", "Планёрка", "2026-10-26 09:00", {}),
    (WED_10, "Отчёт каждый понедельник в 9", "Отчёт", "2026-10-26 09:00", {"repeat": "weekly"}),
    (
        WED_10,
        "Отчёт по будням в 9",
        "Отчёт",
        "2026-10-22 09:00",
        {"repeat": "weekdays", "rolled": True},
    ),
    (WED_10, "Забрать заказ в 3 часа дня", "Забрать заказ", "2026-10-21 15:00", {}),
    (WED_10, "Закрыть смену в 7 вечера", "Закрыть смену", "2026-10-21 19:00", {}),
    (WED_10, "Проверить сейф в 2 ночи", "Проверить сейф", "2026-10-22 02:00", {"rolled": True}),
    (WED_10, "Срочно проверить холодильник", "Проверить холодильник", None, {"priority": "urgent"}),
    (WED_10, "Через 15 минут перезвонить", "Перезвонить", "2026-10-21 10:15", {}),
    (WED_10, "Дежурство в субботу", "Дежурство", "2026-10-24 18:00", {}),
    (WED_10, "Сверка 25 октября в 10", "Сверка", "2026-10-25 10:00", {}),
    (
        WED_10,
        "Позвонить zavtra v 10",
        "Позвонить zavtra v 10",
        None,
        {},
    ),  # translit + Latin "v": not read
    # English
    (WED_10, "Call supplier tomorrow 3pm", "Call supplier", "2026-10-22 15:00", {}),
    (WED_10, "Check fridge in 2 hours", "Check fridge", "2026-10-21 12:00", {}),
    (WED_10, "Inventory next monday", "Inventory", "2026-10-26 18:00", {}),
    (WED_10, "Report friday", "Report", "2026-10-23 18:00", {}),
    (WED_10, "Report next friday at 9", "Report", "2026-10-30 09:00", {}),
    (WED_10, "Order stock by 5pm", "Order stock", "2026-10-21 17:00", {}),
    (WED_10, "Pay invoice on oct 25", "Pay invoice", "2026-10-25 18:00", {}),
    (
        WED_10,
        "Check fridge every day at 9",
        "Check fridge",
        "2026-10-22 09:00",
        {"repeat": "daily", "rolled": True},
    ),
    (WED_10, "Tomorrow 9am: call supplier", "Call supplier", "2026-10-22 09:00", {}),
    (WED_10, "Count cash tonight", "Count cash", "2026-10-21 21:00", {}),
    (WED_10, "Inventory this weekend", "Inventory", "2026-10-24 18:00", {}),
    (WED_10, "Call back in half an hour", "Call back", "2026-10-21 10:30", {}),
    # Numbers that are and aren't times
    (WED_10, "Yetkazish 3 da", "Yetkazish", "2026-10-21 15:00", {}),  # bare 1-6: afternoon
    (WED_10, "Kassa в 8", "Kassa", "2026-10-22 08:00", {"rolled": True}),  # bare 7-12: as written
    (WED_10, "Seyf 03:00", "Seyf", "2026-10-22 03:00", {"rolled": True}),  # a leading zero is meant
    (
        WED_10,
        "Yig‘ilish 10.11",
        "Yig‘ilish",
        "2026-11-10 18:00",
        {},
    ),  # D.M with a real month: a date
    (WED_10, "Kassa 18.30", "Kassa", "2026-10-21 18:30", {}),  # month 30 can't be: a time
    (WED_10, "Kassa в 10.11", "Kassa", "2026-10-21 10:11", {}),  # "в" makes it a time
    (WED_10, "5 ta quti qabul qilish", "5 ta quti qabul qilish", None, {}),
    (WED_10, "Kassa 2", "Kassa 2", None, {}),
    # Words that only look like dates stay in the title
    (WED_10, "Ertalabki muzlatgich harorati", "Ertalabki muzlatgich harorati", None, {}),
    (WED_10, "Bugungi kassa hisoboti", "Bugungi kassa hisoboti", None, {}),
    (WED_10, "Hisobotni erta-indin topshirish", "Hisobotni erta-indin topshirish", None, {}),
    (WED_10, "Hisobot erta-indin", "Hisobot erta-indin", None, {}),
    (
        WED_10,
        "Nakladnoyni ertaga keladigan mashinaga tayyorlash",
        "Nakladnoyni ertaga keladigan mashinaga tayyorlash",
        None,
        {},
    ),
    (WED_10, "Holodilnik!!", "Holodilnik", None, {"priority": "urgent"}),
    # the marks count wherever they are, and leave the title (mini app review)
    (WED_10, "Dori !! ertaga", "Dori", "2026-10-22 18:00", {"priority": "urgent"}),
    (WED_10, "!! Dori ertaga", "Dori", "2026-10-22 18:00", {"priority": "urgent"}),
    (WED_10, "Dori !!! olib kelish", "Dori olib kelish", None, {"priority": "urgent"}),
    (WED_10, "Salom!", "Salom!", None, {}),
    # "till" is the cash register in a pharmacy, never "until" (dashboard review)
    (
        WED_10,
        "Count the till tomorrow 18:00 !!",
        "Count the till",
        "2026-10-22 18:00",
        {"priority": "urgent"},
    ),
    (WED_10, "today 18:00 close the till", "Close the till", "2026-10-21 18:00", {}),
    (WED_10, "ertaga 10:00", "", "2026-10-22 10:00", {}),
    # The evening: a part of the day that's under way, a time that's gone
    (WED_1910, "Kassa bugun kechqurun", "Kassa", "2026-10-21 20:30", {}),
    (WED_1910, "Kassa kechqurun", "Kassa", "2026-10-21 20:30", {}),
    (WED_1910, "Kassa 18:00", "Kassa", "2026-10-22 18:00", {"rolled": True}),
    (WED_1910, "Kassa bugun 18:00", "Kassa", None, {"past": True}),
    (WED_1910, "Kassa bugun", "Kassa", None, {"day": "2026-10-21", "guessed_time": True}),
    (WED_1910, "Kassa ertalab", "Kassa", "2026-10-22 09:00", {"rolled": True}),
    # After midnight on a night shift, "ertaga" is still the coming morning
    (THU_01, "Nakladnoy ertaga 9:00", "Nakladnoy", "2026-10-22 09:00", {}),
    (THU_01, "Kassa bugun 18:00", "Kassa", "2026-10-22 18:00", {}),
    (THU_01, "Kassa indinga", "Kassa", "2026-10-23 18:00", {}),
    (THU_01, "Kassa payshanba", "Kassa", "2026-10-22 18:00", {}),
    (THU_01, "Сдать смену завтра в 8", "Сдать смену", "2026-10-22 08:00", {}),
    # Weekdays-only repeats skip the weekend
    (
        FRI_10,
        "Hisobot ish kunlari soat 9 da",
        "Hisobot",
        "2026-10-26 09:00",
        {"repeat": "weekdays", "rolled": True},
    ),
    # Around the new year, and dates that have passed
    (DEC31_15, "Yig‘ilish 5 yanvar", "Yig‘ilish", "2027-01-05 18:00", {}),
    (DEC31_15, "Kassa 31.12 14:00", "Kassa", None, {"past": True}),
    (DEC31_15, "Kassa 31.12 16:00", "Kassa", "2026-12-31 16:00", {}),
    (DEC31_15, "Bayram 25.12", "Bayram", "2027-12-25 18:00", {}),
    (DEC31_15, "Hisobot 29.02", "Hisobot", "2028-02-29 18:00", {}),
    (DEC31_15, "Hisobot oy oxirida", "Hisobot", "2026-12-31 18:00", {}),
]


def _shown(moment: datetime | None) -> str | None:
    return moment.strftime("%Y-%m-%d %H:%M") if moment else None


@pytest.mark.parametrize(
    ("now", "typed", "title", "due", "extra"),
    CASES,
    ids=[f"{now:%a%H%M}-{typed}" for now, typed, *_ in CASES],
)
def test_what_people_type(now, typed, title, due, extra):
    got = parse(typed, now=now)

    assert got.title == title
    assert _shown(got.due_at) == due
    if got.due_at:
        assert got.due_at.utcoffset().total_seconds() == 5 * 3600  # Tashkent time
    for name, value in extra.items():
        actual = getattr(got, name)
        actual = actual.isoformat() if hasattr(actual, "isoformat") else actual
        assert actual == value, name
    for name in ("rolled", "past", "guessed_time"):  # flags not expected must be off
        if name == "guessed_time" and due and due.endswith("18:00"):
            continue  # a day without a time gets 18:00, which the cases don't always spell out
        if name not in extra:
            assert not getattr(got, name), name


def test_highlight_spans_are_positions_in_the_original_text():
    text = "Narx yorliqlarini yangilash ertaga 10:00"
    assert parse(text, now=WED_10).spans == ((28, 40),)
    text = "Ertaga soat 9 da nakladnoyni qabul qilish"
    assert [text[a:b] for a, b in parse(text, now=WED_10).spans] == ["Ertaga soat 9 da"]
    text = "Kassani sanash - bugun soat 18 ga qadar!!"
    spans = parse(text, now=WED_10).spans
    assert [text[a:b] for a, b in spans] == ["bugun soat 18 ga qadar", "!!"]


def test_a_naive_now_is_refused():
    with pytest.raises(ValueError):
        parse("ertaga", now=datetime(2026, 10, 21, 10, 0))


# The 2027 alphabet (Law O‘RQ-1184, in force 22.04.2027): ö ğ ş ç read like o‘ g‘ sh ch, and a
# span found in the folded text is still the right span of what was typed.
@pytest.mark.parametrize(
    ("typed", "title", "due"),
    [
        ("Hisobot duşanba kuni", "Hisobot", "2026-10-26 18:00"),
        ("Kassa topşirish keçqurun", "Kassa topşirish", "2026-10-21 18:00"),
        ("Tekshirish ön beş daqiqadan keyin", "Tekshirish", "2026-10-21 10:15"),
        ("Hisobot çorşanba", "Hisobot", "2026-10-28 18:00"),
        ("Yetkazish tuşdan keyin", "Yetkazish", "2026-10-21 15:00"),
        ("Kassa soat töqqizda", "Kassa", "2026-10-22 09:00"),
        ("Şoşilinç: muzlatgich ertaga 9:00", "Muzlatgich", "2026-10-22 09:00"),
        ("Inventarizatsiya Payşanba", "Inventarizatsiya", "2026-10-22 18:00"),
    ],
)
def test_the_2027_letters(typed, title, due):
    got = parse(typed, now=WED_10)
    assert got.title == title
    assert _shown(got.due_at) == due
    for start, end in got.spans:
        assert 0 <= start < end <= len(typed)


def test_spans_survive_letters_that_fold_to_two():
    text = "Topşiriq: kassa şanba kuni"
    got = parse(text, now=WED_10)
    assert [text[a:b] for a, b in got.spans] == ["şanba kuni"]
    assert got.title == "Topşiriq: kassa"


def test_urgent_words_in_the_new_spelling():
    assert parse("Kassani tekshirish şoşilinç", now=WED_10).priority == "urgent"


@pytest.mark.parametrize(
    ("typed", "repeat", "weekdays"),
    [
        ("Muzlatgichni tekshirish har kuni 9:00", "daily", (0, 1, 2, 3, 4, 5, 6)),
        ("Отчёт по будням в 9", "weekdays", (0, 1, 2, 3, 4)),
        ("Haftalik hisobot har dushanba soat 10 da", "weekly", (0,)),
        ("Report every week", "weekly", (2,)),  # every week from today, a Wednesday
        ("Kassa ertaga 10:00", None, None),
    ],
)
def test_repeat_and_its_weekdays(typed, repeat, weekdays):
    got = parse(typed, now=WED_10)
    assert got.repeat == repeat
    assert got.repeat_weekdays == weekdays


def test_nothing_found_keeps_the_text_as_it_was():
    got = parse("  Vitrinani artish  ", now=WED_10)
    assert got.title == "Vitrinani artish"
    assert got.due_at is None and not got.found and got.repeat is None


def test_only_a_date_leaves_no_title():
    got = parse("ertaga 10:00", now=WED_10, lang="uz")
    assert got.title == ""
    assert _shown(got.due_at) == "2026-10-22 10:00"


def test_urgency_marks_inside_the_text_are_highlighted_too():
    text = "Dori !! ertaga"
    got = parse(text, now=WED_10)
    assert [text[a:b] for a, b in got.spans] == ["!!", "ertaga"]
