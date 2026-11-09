"""The question of the day (docs/PLAN-LEARNING.md §4.8, §9.2): who gets one and when, which
question, the bot's message and its edit after answering in the app."""

import random
from datetime import date, time, timedelta

import pytest

from apps.inbox.models import NotificationPreference
from apps.learning import conf, daily
from apps.learning.models import AnswerLog, DailyQuestion
from apps.learning.tests.q2.fixtures import (
    local,
    person,
    position,
    question,
    switch_on,
    topic,
)
from apps.recognition import conf as recognition_conf
from apps.recognition.models import PointsEntry
from apps.timeoff.models import Holiday, TimeOff

pytestmark = pytest.mark.django_db

# Monday 9 November 2026, after 11:00 in Tashkent.
MONDAY = local(2026, 11, 9, 11, 5)


@pytest.fixture
def on(pharmacy):
    row = conf.get_settings(pharmacy)
    row.daily_question = True
    row.daily_at = time(11, 0)
    row.save()
    question(pharmacy, "single", topic=topic(pharmacy))
    return pharmacy


@pytest.fixture
def chat(staff):
    staff.user.telegram_id = 700100
    staff.user.save(update_fields=["telegram_id"])
    return staff


@pytest.fixture
def edits(monkeypatch):
    found = []
    monkeypatch.setattr(
        "apps.notifications.telegram.edit_message",
        lambda bot, chat_id, message_id, text, reply_markup=None: found.append(
            (chat_id, message_id, text, reply_markup)
        ),
    )
    return found


def test_one_question_per_person_on_a_workday_after_its_time(on, chat, sent_messages):
    assert daily.send_daily_questions(MONDAY - timedelta(minutes=10)) == 0  # 10:55: not yet
    assert daily.send_daily_questions(MONDAY) == 1
    assert daily.send_daily_questions(MONDAY + timedelta(minutes=10)) == 0  # once a day
    found = DailyQuestion.objects.get()
    assert (found.membership, found.day, found.sent_at) == (chat, date(2026, 11, 9), MONDAY)
    [message] = sent_messages
    assert message["chat_id"] == 700100
    assert "Question of the day" in message["text"]
    buttons = [row[0]["text"] for row in message["reply_markup"]["inline_keyboard"]]
    assert sorted(text[3:] for text in buttons) == [
        "+15 dan +25 gacha",
        "+2 dan +8 gacha",
        "0 dan +4 gacha",
    ]
    assert [text[:3] for text in buttons] == ["A. ", "B. ", "C. "]


def test_nothing_on_a_day_off_a_holiday_or_while_off(on, chat, sent_messages):
    sunday = MONDAY - timedelta(days=1)
    assert daily.send_daily_questions(sunday) == 0
    Holiday.objects.create(company=on, date=date(2026, 11, 9), name="Bayram")
    assert daily.send_daily_questions(MONDAY) == 0
    Holiday.objects.all().delete()
    learning = conf.get_settings(on)
    learning.daily_question = False
    learning.save()
    assert daily.send_daily_questions(MONDAY) == 0
    assert not DailyQuestion.objects.exists() and sent_messages == []


def test_people_on_time_off_and_other_positions_get_none(on, staff, sent_messages):
    away = person(on)
    TimeOff.objects.create(
        company=on,
        membership=away,
        status="approved",
        first_day=date(2026, 11, 2),
        last_day=date(2026, 11, 13),
    )
    pharmacists = position(on)
    pharmacist = person(on, position=pharmacists)
    learning = conf.get_settings(on)
    learning.daily_position_ids = [pharmacists.pk]
    learning.save()
    daily.send_daily_questions(MONDAY)
    assert list(DailyQuestion.objects.values_list("membership", flat=True)) == [pharmacist.pk]


def test_nobody_gets_one_while_learning_is_off(on, chat, sent_messages):
    on.features = [feature for feature in on.features if feature != "learning"]
    on.save(update_fields=["features"])
    assert daily.send_daily_questions(MONDAY) == 0
    assert not DailyQuestion.objects.exists()


def test_the_weakest_rated_topic_first_then_the_unrated(on, staff):
    cold, rx, till = topic(on), topic(on, "Retsept"), topic(on, "Kassa")
    weak = question(on, "true_false", topic=rx)
    question(on, "true_false", topic=till)
    for share in (0, 0, 1):
        AnswerLog.objects.create(
            company=on,
            membership=staff,
            question=weak,
            topic=rx,
            source="daily",
            correct=share == 1,
            share=share,
            at=MONDAY - timedelta(days=3),
        )
    for seed in range(5):
        assert daily.pick(staff, MONDAY.date(), random.Random(seed)).topic == rx
    strong = person(on)
    for share in (1, 1, 1):
        AnswerLog.objects.create(
            company=on,
            membership=strong,
            question=weak,
            topic=rx,
            source="daily",
            correct=True,
            share=share,
            at=MONDAY - timedelta(days=3),
        )
    # Strong where rated: the unrated topics come first.
    picked = {daily.pick(strong, MONDAY.date(), random.Random(seed)).topic for seed in range(8)}
    assert picked <= {cold, till} and picked


def test_never_a_question_seen_in_the_last_30_days_while_others_are_left(on, staff):
    seen = question(on, "true_false", topic=topic(on))
    fresh = question(on, "true_false", topic=topic(on))
    DailyQuestion.objects.exclude(question__in=[seen, fresh]).delete()
    from apps.learning.models import Question

    Question.objects.exclude(pk__in=[seen.pk, fresh.pk]).update(state="archived")
    DailyQuestion.objects.create(
        company=on, membership=staff, day=MONDAY.date() - timedelta(days=12), question=seen
    )
    for seed in range(6):
        assert daily.pick(staff, MONDAY.date(), random.Random(seed)) == fresh
    DailyQuestion.objects.create(
        company=on, membership=staff, day=MONDAY.date() - timedelta(days=5), question=fresh
    )
    # Both seen lately: the one asked longest ago.
    assert daily.pick(staff, MONDAY.date()) == seen


def test_a_kind_for_the_app_says_so_in_the_bot(on, chat, sent_messages):
    from apps.learning.models import Question

    Question.objects.update(state="archived")
    question(on, "order")
    daily.send_daily_questions(MONDAY)
    [message] = sent_messages
    assert "answered in the app" in message["text"]


def test_someone_who_turned_the_bot_message_off_still_gets_the_card(on, chat, sent_messages):
    NotificationPreference.objects.create(
        membership=chat, kind="learning.daily", in_app=True, telegram=False
    )
    assert daily.send_daily_questions(MONDAY) == 1
    assert sent_messages == [] and DailyQuestion.objects.get().sent_at is not None


def test_answered_in_the_app_the_bot_message_becomes_the_result(
    on, chat, edits, monkeypatch, freeze, django_capture_on_commit_callbacks
):
    monkeypatch.setattr("apps.notifications.telegram.send_message", lambda *args, **kw: 4242)
    daily.send_daily_questions(MONDAY)
    found = DailyQuestion.objects.get()
    assert found.chat_message_id == 4242
    freeze(MONDAY + timedelta(hours=1))
    with django_capture_on_commit_callbacks(execute=True):
        outcome = daily.answer(found, chat, {"option": "b"})
    assert outcome.correct is False
    [(chat_id, message_id, text, markup)] = edits
    assert (chat_id, message_id) == (700100, 4242)
    letter = "ABC"[found.order.index("a")]
    assert "Not quite." in text and f"The right answer: {letter}. +2 dan +8 gacha" in text
    assert markup is None  # no https mini app in tests: no button


def test_a_wrong_answer_earns_the_companys_points_for_trying(on, staff, freeze):
    """Recognition's points table, not a number of learning's own: 1 by default, or the
    company's "daily_tried" row (PLAN-LEARNING §7.1)."""
    switch_on(on, "recognition")
    table = recognition_conf.get_settings(on)
    table.points_table = {"daily_tried": 3}
    table.save()
    freeze(MONDAY)
    found = DailyQuestion.objects.create(
        company=on,
        membership=staff,
        day=MONDAY.date(),
        question=question(on, "single"),
        order=["c", "a", "b"],
    )
    outcome = daily.answer(found, staff, {"option": "b"})
    assert outcome.correct is False and outcome.points == 3
    entry = PointsEntry.objects.get(membership=staff)
    assert (entry.reason, entry.key, entry.points) == ("daily", f"daily:{found.pk}", 3)
    assert daily.tried_points(on) == 3
    table.points_table = {}
    table.save()
    assert daily.tried_points(on) == 1


def test_the_multi_choice_toggles_are_kept_until_answered(on, staff, freeze):
    freeze(MONDAY)
    found = DailyQuestion.objects.create(
        company=on,
        membership=staff,
        day=MONDAY.date(),
        question=question(on, "multi"),
        order=["c", "a", "b"],
    )
    assert daily.toggle(found, staff, "a") == ["a"]
    assert daily.toggle(found, staff, "c") == ["c", "a"]
    assert daily.toggle(found, staff, "a") == ["c"]
    found.refresh_from_db()
    assert found.answered_at is None
    assert daily.today_for(staff) == found
