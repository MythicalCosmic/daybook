"""Demo data of package Q2 (quizzes, the daily question, checks, skills, the tutor), called by
`demo.py` after Q1's courses (docs/PLAN-LEARNING.md §14).

Demo Dorixona's question bank: about forty questions of every kind, each from the company's
own knowledge base pages (the fridge at +2…+8 °C, the receiving checklist, prescriptions,
expired goods, the till, the night handover; no legal number the pages don't state). Three
quizzes: a random "Sovuq zanjir testi", a fixed "Retsept testi" and the weekly check's
"Haftalik tekshiruv testi". Four weeks of attempts, checks and questions of the day tell the
story: Madina is strong everywhere and could coach the cold chain, Alisher is weak in the cold
chain and prices, Nigora (nights) in prescriptions and prices, Jasur (courier) answers a little.
The weekly check "Dushanba tekshiruvi" has three closed rounds and an open one; last Monday's
report is in the managers' inboxes, with the open suggestions. Q1's courses are found by
title when they are there; it all works without them.
"""

from __future__ import annotations

import random
from datetime import datetime, time, timedelta

from django.utils import translation

from apps.core import demo_time
from apps.core.demo_plan import Plan
from apps.core.exceptions import DomainError
from apps.knowledge import topics as topic_services
from apps.knowledge.models import Page, Topic
from apps.learning import attempts, checks, conf, daily, drafting, grading, quizzes, suggestions
from apps.learning.models import (
    Assignment,
    CheckRound,
    Course,
    DailyQuestion,
    Question,
    RegularCheck,
    TutorSuggestion,
)
from apps.members.models import Position

# Topics by their place in knowledge.topics.PHARMACY_TOPICS.
COLD, RX, CONTROLLED, STORAGE, GOODS, TILL, ADVICE, SERVICE, HYGIENE = range(9)

# (topic, kind, text, data, explanation, difficulty)
QUESTIONS = [
    # The cold chain -----------------------------------------------------------------------
    (
        COLD,
        "single",
        "Insulin qaysi haroratda saqlanadi?",
        {
            "options": [
                {"text": "+2 °C dan +8 °C gacha", "correct": True},
                {"text": "0 °C dan +4 °C gacha", "correct": False},
                {"text": "+8 °C dan +15 °C gacha", "correct": False},
                {"text": "+15 °C dan +25 °C gacha", "correct": False},
            ]
        },
        "Insulin, vaksinalar va ba’zi ko‘z tomchilari muzlatgichda +2 °C dan +8 °C gacha "
        "saqlanadi.",
        "easy",
    ),
    (
        COLD,
        "true_false",
        "Insulinni muzlatgichning muzlatish kamerasiga qo‘yish mumkin.",
        {"answer": False},
        "Muzlagan insulin ishlatilmaydi: u +2 °C dan +8 °C gacha saqlanadi.",
        "easy",
    ),
    (
        COLD,
        "multi",
        "Qaysi dorilar muzlatgichda saqlanadi?",
        {
            "options": [
                {"text": "Insulin", "correct": True},
                {"text": "Vaksinalar", "correct": True},
                {"text": "Paratsetamol tabletkasi", "correct": False},
                {"text": "Aktivlangan ko‘mir", "correct": False},
            ]
        },
        "Issiqqa sezgir dorilar (insulin, vaksinalar) sovuq zanjirda saqlanadi.",
        "medium",
    ),
    (
        COLD,
        "number",
        "Muzlatgich harorati kuniga necha marta jurnalga yoziladi?",
        {"value": 2, "tolerance": 0, "unit": "marta"},
        "Haroratni kuniga ikki marta — 09:00 da va 20:30 da — botdagi vazifaga yozamiz.",
        "easy",
    ),
    (
        COLD,
        "order",
        "Muzlatgich harorati chegaradan chiqdi. Nima qilasiz? To‘g‘ri tartibda.",
        {
            "items": [
                {"text": "Darhol mudirga xabar bering"},
                {"text": "Dorilarni zaxira muzlatgichga o‘tkazing"},
                {"text": "Nima bo‘lganini jurnalga yozing"},
            ]
        },
        "Avval mudir, keyin dorilarni saqlab qolish, so‘ng jurnal.",
        "medium",
    ),
    (
        COLD,
        "text",
        "Muzlatgichdagi dorilar qaysi harorat oralig‘ida saqlanadi? (masalan: 2–8)",
        {"answers": ["2–8", "+2 – +8", "2-8 daraja"], "case": False},
        "Muzlatgichda +2 °C dan +8 °C gacha.",
        "medium",
    ),
    (
        COLD,
        "true_false",
        "Harorati chegaradan chiqqan dorini mudir ruxsatisiz sotmaymiz.",
        {"answer": True},
        "Bunday dori mudir qaroriga qadar sotilmaydi.",
        "easy",
    ),
    (
        COLD,
        "single",
        "Sovuq zanjir dorisi xaridorga qanday yetkaziladi?",
        {
            "options": [
                {"text": "Termosumkada, sovutgich elementi bilan", "correct": True},
                {"text": "Oddiy paketda", "correct": False},
                {"text": "Qog‘oz qutida", "correct": False},
            ]
        },
        "Sovuq zanjir dorilari faqat termosumkada, sovutgich elementi bilan yetkaziladi.",
        "medium",
    ),
    # Prescription medicines ---------------------------------------------------------------
    (
        RX,
        "single",
        "Retseptli dorini qachon sotish mumkin?",
        {
            "options": [
                {"text": "Amaldagi retsept ko‘rsatilganda", "correct": True},
                {"text": "Xaridor iltimos qilganda", "correct": False},
                {"text": "Dori omborda ko‘p bo‘lganda", "correct": False},
                {"text": "Kassir ruxsat berganda", "correct": False},
            ]
        },
        "Retseptli dorilar faqat amaldagi retsept (qog‘oz yoki elektron) bilan sotiladi.",
        "easy",
    ),
    (
        RX,
        "true_false",
        "Retseptli dorilarni vitrinaga qo‘yish mumkin.",
        {"answer": False},
        "Retseptli dorilar vitrinaga qo‘yilmaydi.",
        "easy",
    ),
    (
        RX,
        "multi",
        "Qog‘oz retseptda nimalarni tekshirasiz?",
        {
            "options": [
                {"text": "Retseptning muddati", "correct": True},
                {"text": "Shifokor imzosi", "correct": True},
                {"text": "Muhr", "correct": True},
                {"text": "Xaridorning ish joyi", "correct": False},
            ]
        },
        "Retseptning muddati, shifokor imzosi va muhri tekshiriladi.",
        "medium",
    ),
    (
        RX,
        "order",
        "Retsept bo‘yicha dori berish tartibi",
        {
            "items": [
                {"text": "Retseptning muddati, imzosi va muhrini tekshiring"},
                {"text": "Dorini ta’sir etuvchi moddasi (XPN) bo‘yicha bering"},
                {"text": "Qog‘oz retseptni qoldiring va retseptlar jurnaliga yozing"},
            ]
        },
        "Avval retseptni tekshiramiz, keyin dori beramiz, so‘ng jurnalga yozamiz.",
        "medium",
    ),
    (
        RX,
        "true_false",
        "Antibiotiklar faqat elektron retsept bilan beriladi.",
        {"answer": True},
        "Antibiotiklar va tizimli gormonlar faqat elektron retsept bilan beriladi.",
        "medium",
    ),
    (
        RX,
        "match",
        "Atamalarni ma’nosi bilan juftlang",
        {
            "pairs": [
                {"left": "XPN", "right": "Ta’sir etuvchi moddaning xalqaro nomi"},
                {
                    "left": "Retseptlar jurnali",
                    "right": "Berilgan retseptli dorilar yoziladigan daftar",
                },
                {"left": "Elektron retsept", "right": "Tizimda tekshiriladigan retsept"},
            ]
        },
        "",
        "medium",
    ),
    (
        RX,
        "text",
        "Dorini savdo nomi emas, ta’sir etuvchi moddasi bo‘yicha beramiz. Uning qisqartmasi nima?",
        {"answers": ["XPN", "МНН", "INN"], "case": False},
        "XPN: ta’sir etuvchi moddaning xalqaro patentlanmagan nomi.",
        "hard",
    ),
    (
        RX,
        "true_false",
        "Retseptli dorilar uyga yetkazib berilmaydi.",
        {"answer": True},
        "Xaridor retsept bilan dorixonaga keladi.",
        "medium",
    ),
    # Controlled substances ----------------------------------------------------------------
    (
        CONTROLLED,
        "single",
        "Nazoratdagi moddalar qayerda saqlanadi?",
        {
            "options": [
                {"text": "Metall seyfda", "correct": True},
                {"text": "Vitrinada", "correct": False},
                {"text": "Kassa yonidagi javonda", "correct": False},
                {"text": "Muzlatgichda", "correct": False},
            ]
        },
        "Nazoratdagi moddalar faqat Yunusobod dorixonasida, metall seyfda saqlanadi.",
        "medium",
    ),
    (
        CONTROLLED,
        "true_false",
        "Nazoratdagi moddaning har bir kirimi va sotuvi o‘sha kuni "
        "raqamlangan, tikilgan kitobga yoziladi.",
        {"answer": True},
        "Har bir kirim va sotuv o‘sha kuni kitobga yoziladi.",
        "medium",
    ),
    (
        CONTROLLED,
        "true_false",
        "Nazoratdagi moddalar ikkala dorixonamizda ham saqlanadi.",
        {"answer": False},
        "Ular faqat Yunusobod dorixonasida saqlanadi.",
        "easy",
    ),
    # Storage and expiry dates -------------------------------------------------------------
    (
        STORAGE,
        "single",
        "Muddati o‘tgan dori topildi. Birinchi navbatda nima qilinadi?",
        {
            "options": [
                {"text": "Sotuvdan olinib, “Karantin” javoniga o‘tkaziladi", "correct": True},
                {"text": "Chegirma bilan sotiladi", "correct": False},
                {"text": "Javonda qoldiriladi", "correct": False},
            ]
        },
        "Muddati o‘tgan dori darhol sotuvdan olinadi va karantinga qo‘yiladi.",
        "easy",
    ),
    (
        STORAGE,
        "number",
        "Har dushanba muddati necha kundan kam qolgan dorilarni tekshiramiz?",
        {"value": 90, "tolerance": 0, "unit": "kun"},
        "Har dushanba muddati 90 kundan kam qolgan dorilarni tekshirib, oldingi qatorga qo‘yamiz.",
        "medium",
    ),
    (
        STORAGE,
        "order",
        "Muddati o‘tgan dori bilan ishlash tartibi",
        {
            "items": [
                {"text": "Karantin javoniga o‘tkazing va ro‘yxatga yozing"},
                {"text": "Mudir hisobdan chiqarish dalolatnomasini tuzadi"},
                {"text": "Dori komissiya ishtirokida yo‘q qilinadi"},
            ]
        },
        "Karantin, dalolatnoma, so‘ng komissiya bilan yo‘q qilish.",
        "medium",
    ),
    (
        STORAGE,
        "true_false",
        "Savdo zalida dorilar +15 °C dan +25 °C gacha haroratda saqlanadi.",
        {"answer": True},
        "Xona harorati +15 °C dan +25 °C gacha bo‘lishi kerak.",
        "easy",
    ),
    (
        STORAGE,
        "text",
        "Yaroqlilik muddati eng yaqin dori birinchi sotiladi. Bu qoidaning "
        "inglizcha qisqartmasi nima?",
        {"answers": ["FEFO"], "case": False},
        "FEFO: first expired, first out.",
        "hard",
    ),
    (
        STORAGE,
        "single",
        "Muddati 90 kundan kam qolgan dori javonda qayerga qo‘yiladi?",
        {
            "options": [
                {"text": "Oldingi qatorga", "correct": True},
                {"text": "Orqa qatorga", "correct": False},
                {"text": "Omborga", "correct": False},
            ]
        },
        "Muddati yaqin dori oldingi qatorga qo‘yiladi.",
        "easy",
    ),
    (
        STORAGE,
        "multi",
        "Qaysi dorilar sotuvdan olinadi?",
        {
            "options": [
                {"text": "Muddati o‘tgan", "correct": True},
                {"text": "Sifatsiz deb topilgan", "correct": True},
                {"text": "Narxi o‘zgargan", "correct": False},
                {"text": "Yangi kirimdan kelgan", "correct": False},
            ]
        },
        "Muddati o‘tgan yoki sifatsiz deb topilgan dori darhol sotuvdan olinadi.",
        "medium",
    ),
    (
        STORAGE,
        "number",
        "Savdo zalida namlik necha foizdan past bo‘lishi kerak?",
        {"value": 60, "tolerance": 0, "unit": "%"},
        "Dorilar 60 % dan past namlikda saqlanadi.",
        "hard",
    ),
    # Goods receipt ------------------------------------------------------------------------
    (
        GOODS,
        "order",
        "Kirimni qabul qilish tartibi",
        {
            "items": [
                {"text": "Nakladnoydagi nom va miqdorni sanab chiqing"},
                {"text": "Har bir qatorning seriyasi va yaroqlilik muddatini tekshiring"},
                {"text": "Sovuq zanjir dorilarini darhol muzlatgichga qo‘ying"},
                {"text": "Nakladnoyni rasmga olib, ilovaga yuklang"},
            ]
        },
        "Kirim nakladnoy bilan, tartib bilan qabul qilinadi.",
        "medium",
    ),
    (
        GOODS,
        "number",
        "Kirim necha daqiqadan oshmasligi kerak?",
        {"value": 30, "tolerance": 0, "unit": "daqiqa"},
        "Kirim 30 daqiqadan oshmasligi kerak.",
        "medium",
    ),
    (
        GOODS,
        "true_false",
        "Yaroqlilik muddati 6 oydan kam qolgan dorini qabul qilamiz.",
        {"answer": False},
        "Bunday dori qabul qilinmaydi: haydovchi bilan dalolatnoma tuziladi.",
        "medium",
    ),
    (
        GOODS,
        "single",
        "Dori nima bilan qabul qilinadi?",
        {
            "options": [
                {"text": "Nakladnoy bilan", "correct": True},
                {"text": "Haydovchining so‘zi bilan", "correct": False},
                {"text": "Telefondagi xabar bilan", "correct": False},
            ]
        },
        "Dori faqat nakladnoy bilan qabul qilinadi.",
        "easy",
    ),
    (
        GOODS,
        "match",
        "Kirim atamalarini juftlang",
        {
            "pairs": [
                {"left": "Nakladnoy", "right": "Yuk xati"},
                {"left": "Seriya", "right": "Partiya raqami"},
                {"left": "Defektura", "right": "Topilmagan dorilar ro‘yxati"},
                {"left": "Kirim", "right": "Dorilarni qabul qilish"},
            ]
        },
        "",
        "easy",
    ),
    # Prices and the till ------------------------------------------------------------------
    (
        TILL,
        "true_false",
        "Har bir dorining narxi ko‘rinib turishi kerak.",
        {"answer": True},
        "Narx ko‘rinib turadi va mas’ul shaxs imzosi bilan tasdiqlanadi.",
        "easy",
    ),
    (
        TILL,
        "single",
        "Narx yorliqlari qachon yangilanadi?",
        {
            "options": [
                {"text": "Yangi kirimdan keyin seshanba va juma kunlari", "correct": True},
                {"text": "Faqat oy oxirida", "correct": False},
                {"text": "Xaridor so‘raganda", "correct": False},
            ]
        },
        "Narx yorliqlarini yangi kirimdan keyin seshanba va juma kunlari yangilaymiz.",
        "hard",
    ),
    (
        TILL,
        "number",
        "Kassani ochishda boshlang‘ich qoldiq necha so‘m bo‘ladi?",
        {"value": 300000, "tolerance": 0, "unit": "so‘m"},
        "Boshlang‘ich qoldiq: 300 000 so‘m mayda pul.",
        "medium",
    ),
    (
        TILL,
        "order",
        "Smena oxirida kassani yopish tartibi",
        {
            "items": [
                {"text": "Terminalda kunlik hisobotni chiqaring va rasmga oling"},
                {"text": "Kassa apparatida Z-hisobot chiqaring va rasmga oling"},
                {"text": "Naqd pulni nominallar bo‘yicha sanang"},
                {"text": "Mayda pulni keyingi smenaga qoldiring"},
            ]
        },
        "Avval hisobotlar, keyin ko‘r sanash, so‘ng mayda pul.",
        "hard",
    ),
    (
        TILL,
        "true_false",
        "Sotilgan dorini xaridor qaytarib bera oladi.",
        {"answer": False},
        "Sotilgan dorilar qaytarib olinmaydi va almashtirilmaydi.",
        "medium",
    ),
    (
        TILL,
        "single",
        "Kassa qoldig‘i 300 000 so‘mdan farq qilsa, nima qilasiz?",
        {
            "options": [
                {"text": "Smenani ochmay, darhol mudirga xabar beraman", "correct": True},
                {"text": "Farqni o‘zim to‘ldiraman", "correct": False},
                {"text": "Smenani ochib, kechqurun aytaman", "correct": False},
            ]
        },
        "Qoldiq farq qilsa, smena ochilmaydi va mudirga xabar beriladi.",
        "medium",
    ),
    # Analogues and advice, customer service, hygiene --------------------------------------
    (
        ADVICE,
        "true_false",
        "Tashxis qo‘yish yoki dori va dozani o‘zimiz tanlab berish shifokorning ishi.",
        {"answer": True},
        "Bu shifokorning ishi: biz retseptni o‘qiymiz.",
        "easy",
    ),
    (
        SERVICE,
        "single",
        "Xaridor so‘ragan dori qolmagan bo‘lsa, nima qilasiz?",
        {
            "options": [
                {"text": "Defekturaga yozaman va qachon kelishini aytaman", "correct": True},
                {"text": "“Bilmayman” deyman", "correct": False},
                {"text": "Boshqa dorini o‘zim tanlab beraman", "correct": False},
            ]
        },
        "Dori bo‘lmasa, defekturaga yozib, qachon kelishini aytamiz.",
        "easy",
    ),
    (
        SERVICE,
        "number",
        "Xaridor kirganda necha soniya ichida salomlashamiz?",
        {"value": 5, "tolerance": 0, "unit": "soniya"},
        "Xaridor kirganda 5 soniya ichida salomlashamiz.",
        "easy",
    ),
    (
        HYGIENE,
        "multi",
        "Ish kiyimiga nimalar kiradi?",
        {
            "options": [
                {"text": "Oq xalat", "correct": True},
                {"text": "Ism va lavozim yozilgan bejik", "correct": True},
                {"text": "Yopiq, toza poyabzal", "correct": True},
                {"text": "Bosh kiyim", "correct": False},
            ]
        },
        "Oq xalat, bejik va yopiq toza poyabzal.",
        "easy",
    ),
]

# How likely each learner gets a topic right (the story), by the people's keys.
SKILL = {
    "madina": {COLD: 0.97, RX: 0.93, STORAGE: 0.92, GOODS: 0.9, TILL: 0.88},
    "worker": {COLD: 0.3, RX: 0.75, STORAGE: 0.62, GOODS: 0.78, TILL: 0.4},
    "nigora": {COLD: 0.72, RX: 0.35, STORAGE: 0.75, GOODS: 0.7, TILL: 0.42},
    "jasur": {COLD: 0.62, RX: 0.5, STORAGE: 0.6, GOODS: 0.65, TILL: 0.55},
}
DEFAULT_SKILL = 0.7
LEARNERS = ("madina", "worker", "nigora", "jasur")


def seed(company, people, now) -> None:
    """Add demo rows to `company`. `people` maps owner, manager, worker, madina, jasur
    and nigora to their memberships."""
    owner = people["owner"]
    rng = random.Random("q2-demo")  # the same story every build
    plan = Plan(company, people, now)
    topics = _topics(company, owner)
    with translation.override(company.default_language), demo_time.quiet():
        start = now - timedelta(days=35)
        with demo_time.moment(start):
            bank = _bank(company, owner, topics)
            tests = _quizzes(company, owner, topics, bank)
            check = _check(company, owner, tests["check"])
        _settings(company, owner, now, start)
        _history(company, people, plan, tests, rng, now)
        _rounds(company, people, plan, check, rng, now)
        _dailies(company, people, plan, rng, now)
        _story(company, people, topics, now)
        _report(company, now)
        _drafts(company, owner, now)


def _topics(company, owner) -> dict[int, Topic]:
    topic_services.add_pharmacy_topics(company, by=owner)
    with translation.override(company.default_language):
        names = [str(name) for name, _colour in topic_services.PHARMACY_TOPICS]
    found = {topic.name: topic for topic in Topic.objects.filter(company=company)}
    return {index: found[name] for index, name in enumerate(names) if name in found}


def _bank(company, owner, topics) -> list[Question]:
    made = []
    for topic, kind, text, data, explanation, difficulty in QUESTIONS:
        made.append(
            quizzes.create_question(
                company,
                by=owner,
                kind=kind,
                text=text,
                data=data,
                explanation=explanation,
                topic_id=topics[topic].pk if topic in topics else None,
                difficulty=difficulty,
                points=2 if kind in ("order", "match") else 1,
            )
        )
    return made


def _quizzes(company, owner, topics, bank) -> dict:
    def topic_ids(*indexes):
        return [topics[index].pk for index in indexes if index in topics]

    cold = quizzes.create_quiz(
        company,
        by=owner,
        title="Sovuq zanjir testi",
        description="Muzlatgich, harorat jurnali va sovuq zanjir dorilarini yetkazish.",
        mode="random",
        question_count=5,
        topic_ids=topic_ids(COLD, STORAGE),
        pass_percent=70,
        time_limit_seconds=600,
        retry_after_minutes=30,
        show_answers="after",
    )
    rx_questions = [question.pk for question in bank if question.topic_id in topic_ids(RX)]
    prescriptions = quizzes.create_quiz(
        company,
        by=owner,
        title="Retsept testi",
        description="Retseptli dorini berish tartibi: tekshirish, berish, jurnal.",
        mode="fixed",
        question_ids=rx_questions,
        shuffle_questions=False,
        pass_percent=80,
        max_attempts=3,
        show_answers="passed",
    )
    weekly = quizzes.create_quiz(
        company,
        by=owner,
        title="Haftalik tekshiruv testi",
        description="Har dushanba besh savol: sovuq zanjir, retsept, saqlash, kirim, kassa.",
        mode="random",
        question_count=5,
        topic_ids=topic_ids(COLD, RX, STORAGE, GOODS, TILL),
        pass_percent=60,
        show_answers="after",
    )
    for quiz in (cold, prescriptions, weekly):
        quizzes.publish_quiz(quiz, by=owner)
    return {"cold": cold, "rx": prescriptions, "check": weekly}


def _check(company, owner, quiz) -> RegularCheck:
    staff = list(
        Position.objects.filter(
            company=company,
            name__in=["Pharmacist", "Senior pharmacist", "Courier", "Farmatsevt", "Provizor"],
        ).values_list("pk", flat=True)
    )
    return checks.create_check(
        company,
        by=owner,
        title="Dushanba tekshiruvi",
        quiz_id=quiz.pk,
        every="week",
        weekday=0,
        at="10:00",
        answer_within_hours=48,
        audience_all=not staff,
        position_ids=staff,
    )


def _settings(company, owner, now, start) -> None:
    with demo_time.moment(start):
        daily.update_settings(company, by=owner, daily_question=True, daily_at="11:00")


# Four weeks of answers ---------------------------------------------------------------------


def _answer(question: Question, order: list, right: bool, rng: random.Random) -> dict | None:
    """The learner's answer: the right one, or a likely wrong one."""
    kind, data = question.kind, question.data
    correct = grading.right_answer(kind, data, order)
    if right:
        return correct
    if kind == "single":
        wrong = [value for value in order if value != correct["option"]]
        return {"option": rng.choice(wrong)}
    if kind == "multi":
        picked = correct["options"][:1] + [v for v in order if v not in correct["options"]][:1]
        return {"options": picked}
    if kind == "true_false":
        return {"value": not correct["value"]}
    if kind == "order":
        return {"order": list(reversed(correct["order"]))}
    if kind == "match":
        values = list(correct["pairs"].values())
        shifted = values[1:] + values[:1]
        return {"pairs": dict(zip(correct["pairs"], shifted, strict=True))}
    if kind == "text":
        return {"text": "bilmayman"}
    value = data.get("value", 0)
    return {"value": value * 2 if value else 1}


def _chance(key: str, question: Question, topics_by_id: dict[int, int]) -> float:
    index = topics_by_id.get(question.topic_id)
    return SKILL.get(key, {}).get(index, DEFAULT_SKILL)


def take(attempt, key, rng, topics_by_id, at: datetime) -> None:
    """Answer every question of `attempt` as `key` would, then finish it at `at`."""
    found = attempts.questions_of(attempt)
    for item in attempt.items:
        question = found.get(item["question"])
        if question is None:
            continue
        right = rng.random() < _chance(key, question, topics_by_id)
        attempts.save_answer(
            attempt, question.pk, _answer(question, item["order"], right, rng), now=at
        )
    attempts.finish(attempt, now=at)


def _topics_by_id(company) -> dict[int, int]:
    with translation.override(company.default_language):
        names = [str(name) for name, _colour in topic_services.PHARMACY_TOPICS]
    return {
        topic.pk: names.index(topic.name)
        for topic in Topic.objects.filter(company=company)
        if topic.name in names
    }


def _history(company, people, plan, tests, rng, now) -> None:
    """Each learner's quizzes over four weeks, inside their working hours."""
    topics_by_id = _topics_by_id(company)
    for key in LEARNERS:
        member = people.get(key)
        if member is None:
            continue
        for days_ago, quiz in ((26, "cold"), (19, "rx"), (12, "cold"), (5, "rx"), (2, "cold")):
            if key == "jasur" and quiz == "rx":
                continue  # the courier hands out no prescriptions
            day = _workday(plan, key, now, days_ago)
            if day is None:
                continue
            afternoon = plan.at(day, time(15, 0)) + timedelta(minutes=rng.randint(0, 90))
            at = plan.at_work(key, day, afternoon)
            with demo_time.moment(at):
                try:
                    attempt, _new = attempts.start(tests[quiz], member, now=at)
                except DomainError, attempts.NotAllowed:
                    continue  # used up, or the wait: the story goes on
                take(attempt, key, rng, topics_by_id, at + timedelta(minutes=rng.randint(4, 9)))


def _workday(plan: Plan, key: str, now: datetime, days_ago: int):
    """The latest day at or before `days_ago` days back that `key` works (within a week)."""
    for back in range(days_ago, days_ago + 7):
        day = plan.day(-back)
        if plan.works(key, day):
            return day
    return None


def _rounds(company, people, plan, check, rng, now) -> None:
    """Three closed rounds of the weekly check, and this week's still open."""
    topics_by_id = _topics_by_id(company)
    local = plan.local(now)
    monday = local.date() - timedelta(days=local.weekday())
    starts = [plan.at(monday - timedelta(weeks=weeks), time(10, 0)) for weeks in (3, 2, 1, 0)]
    starts = [moment for moment in starts if moment <= now]
    for index, moment in enumerate(starts):
        with demo_time.moment(moment):
            round_ = checks.start_round(check, moment)
        if round_ is None:
            continue
        current = index == len(starts) - 1
        for entry in round_.entries.select_related("membership"):
            key = plan.key_of(entry.membership)
            if key not in LEARNERS or (current and key in ("worker", "nigora")):
                continue  # this week Alisher and Nigora still have to answer
            if not current and key == "nigora" and index == 1:
                continue  # one round Nigora didn't answer
            at = moment + timedelta(hours=rng.randint(1, 30), minutes=rng.randint(0, 50))
            if at >= min(now, round_.due_at):
                continue
            with demo_time.moment(at):
                attempt, _new = attempts.start(check.quiz, entry.membership, entry=entry, now=at)
                take(attempt, key, rng, topics_by_id, at + timedelta(minutes=rng.randint(3, 8)))
        if round_.due_at <= now:
            with demo_time.moment(round_.due_at):
                checks.close_round(round_, round_.due_at)
        elif round_.due_at < now + timedelta(hours=20):
            # Late in the week the open round would close before anyone sees it: one more day.
            CheckRound.objects.filter(pk=round_.pk).update(due_at=now + timedelta(hours=30))
    check.refresh_from_db()
    RegularCheck.objects.filter(pk=check.pk).update(next_run_at=checks.next_occurrence(check, now))


def _dailies(company, people, plan, rng, now) -> None:
    """The question of the day on the learners' working days of the last three weeks; today's
    still to answer for Alisher."""
    settings_row = conf.get_settings(company)
    topics_by_id = _topics_by_id(company)
    for days_ago in range(21, -1, -1):
        day = plan.day(-days_ago)
        if day.weekday() not in (company.workdays or []):
            continue
        sent = plan.at(day, settings_row.daily_at)
        if sent > now:
            continue
        for key in LEARNERS:
            member = people.get(key)
            if member is None or not plan.works(key, day):
                continue
            with demo_time.moment(sent):
                question = daily.pick(member, day, rng)
                if question is None:
                    return
                found = DailyQuestion.objects.create(
                    company=company,
                    membership=member,
                    day=day,
                    question=question,
                    order=grading.shown_order(question.kind, question.data, rng=rng),
                    sent_at=sent,
                )
            if days_ago == 0 and key == "worker":
                continue  # Alisher hasn't answered today's yet
            if rng.random() > 0.85:
                continue  # some days nobody answers
            at = plan.at_work(key, day, sent + timedelta(minutes=rng.randint(5, 240)))
            right = rng.random() < _chance(key, question, topics_by_id)
            with demo_time.moment(at):
                daily.answer(found, member, _answer(question, found.order, right, rng), now=at)


# The tutor ---------------------------------------------------------------------------------


def _story(company, people, topics, now) -> None:
    """The suggestions the facts call for, and the three of the story whatever Q1 has: assign
    "Sovuq zanjir" to Alisher (when the course is there), Madina could coach the cold chain, a
    lesson is missing on prices."""
    last_monday = _last_monday(company, now)
    with demo_time.moment(last_monday):
        suggestions.refresh(company, last_monday)
    worker, madina, nigora = people.get("worker"), people.get("madina"), people.get("nigora")
    cold, till = topics.get(COLD), topics.get(TILL)
    course = Course.objects.filter(company=company, title__icontains="Sovuq zanjir").first()
    wanted = []
    if worker and cold and course and not _finished(worker, course):
        wanted.append(
            {
                "membership": worker,
                "kind": TutorSuggestion.Kind.ASSIGN,
                "topic": cold,
                "course": course,
                "score": 38,
                "params": {"score": 38, "answers": 14},
            }
        )
    if madina and cold and worker:
        wanted.append(
            {
                "membership": madina,
                "kind": TutorSuggestion.Kind.MENTOR,
                "topic": cold,
                "score": 96,
                "params": {"score": 96, "weak": 1},
            }
        )
    if till and worker and nigora:
        wanted.append(
            {"kind": TutorSuggestion.Kind.LESSON_NEEDED, "topic": till, "params": {"weak": 2}}
        )
    for row in wanted:
        exists = TutorSuggestion.objects.filter(
            company=company,
            state=TutorSuggestion.State.OPEN,
            membership=row.get("membership"),
            kind=row["kind"],
            topic=row["topic"],
        ).exists()
        if not exists:
            with demo_time.moment(last_monday):
                TutorSuggestion.objects.create(company=company, **row)


def _finished(member, course) -> bool:
    return Assignment.objects.filter(
        membership=member, course=course, state=Assignment.State.COMPLETED
    ).exists()


def _last_monday(company, now: datetime) -> datetime:
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(company.timezone)
    local = now.astimezone(zone)
    monday = local.date() - timedelta(days=local.weekday() or 7)
    return datetime.combine(monday, time(9, 0), zone)


def _report(company, now) -> None:
    """Last Monday's weekly report in the managers' inboxes (the tutor's own run)."""
    from apps.ai import agents
    from apps.ai import conf as ai_conf
    from apps.ai.agents import tutor

    if not ai_conf.ai_on(company):
        return
    state = agents.state_of(company, tutor.KEY)
    if not state.enabled:
        state.enabled = True
        state.save(update_fields=["enabled", "updated_at"])
    last_monday = _last_monday(company, now)
    with demo_time.moment(last_monday):
        tutor.send_reports(company, agents.config_of(tutor.AGENT, state), last_monday)


def _drafts(company, owner, now) -> None:
    """Questions the rules wrote from the cold chain page last week, waiting for review."""
    page = Page.objects.filter(company=company, title__icontains="sovuq zanjir").first()
    if page is None:
        return
    at = now - timedelta(days=3)
    with demo_time.moment(at):
        job = drafting.create_job(company, by=owner, page_id=page.pk, count=4, engine="rules")
        drafting.run_job(job.pk)
