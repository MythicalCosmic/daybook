"""The mini app's quiz, daily question and check endpoints (docs/PLAN-LEARNING.md §13, Q2):
the exact shapes, no right answer before answering, only one's own, 404 while learning is off."""

import json
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.learning import daily as daily_service
from apps.learning import grading
from apps.learning.models import (
    Attempt,
    CheckEntry,
    CheckRound,
    DailyQuestion,
    Question,
    RegularCheck,
)
from apps.learning.tests.q2.fixtures import DATA, person, question, quiz, topic

pytestmark = pytest.mark.django_db

BASE = "/api/v1/companies/{}/learning/"
PLAY_KEYS = {"id", "kind", "text", "image_url", "points", "options", "left", "right", "unit"}
INTRO_KEYS = {
    "id",
    "title",
    "emoji",
    "description",
    "questions",
    "time_limit_seconds",
    "pass_percent",
    "max_attempts",
    "attempts_used",
    "retry_at",
    "best",
    "in_progress",
    "can_start",
    "reason",
}
RESULT_KEYS = {
    "id",
    "state",
    "score",
    "max_score",
    "percent",
    "passed",
    "points",
    "retry_at",
    "course_step_done",
    "review",
}
EXPLANATION = "Insulin muzlatgichda saqlanadi, chunki issiqda buziladi."


def url(company, rest: str) -> str:
    return BASE.format(company.pk) + rest


@pytest.fixture
def every_kind(pharmacy):
    """A quiz with one question of each kind, each with an explanation."""
    cold = topic(pharmacy)
    asked = [
        question(pharmacy, kind, topic=cold, explanation=EXPLANATION, text=f"{kind}?")
        for kind in DATA
    ]
    return quiz(pharmacy, asked, shuffle_options=True)


def secrets_absent(data) -> None:
    """Nothing in `data` says what the right answer is (§3: never before answering)."""
    text = json.dumps(data, ensure_ascii=False)
    for secret in ("muzlatgich", "37.25", "37,25", EXPLANATION, "tolerance", '"pairs"'):
        assert secret not in text, secret

    def walk(node):
        if isinstance(node, dict):
            if {"kind", "options", "left", "right"} <= set(node):
                assert set(node) == PLAY_KEYS
                for row in node["options"] + node["left"] + node["right"]:
                    assert set(row) == {"id", "text"}
            for key in ("correct", "answer", "right_answer", "explanation", "value"):
                if key in node:
                    assert node[key] is None, key
            if "answers" in node:
                assert node["answers"] == {}
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)


def test_no_right_answer_in_any_response_before_answering(api_as, pharmacy, staff, every_kind):
    client = api_as(staff)
    today = daily_service.today(pharmacy)
    daily = DailyQuestion.objects.create(
        company=pharmacy,
        membership=staff,
        day=today,
        question=Question.objects.get(kind="multi"),
        order=["c", "a", "b"],
    )
    responses = [
        client.get(url(pharmacy, f"quizzes/{every_kind.pk}/")),
        client.post(url(pharmacy, f"quizzes/{every_kind.pk}/attempts/"), {}, format="json"),
    ]
    attempt_id = responses[-1].json()["id"]
    responses += [
        client.get(url(pharmacy, f"attempts/{attempt_id}/")),
        client.post(url(pharmacy, f"quizzes/{every_kind.pk}/attempts/"), {}, format="json"),
        client.get(url(pharmacy, "daily/")),
        client.get(url(pharmacy, "checks/")),
    ]
    assert [response.status_code for response in responses] == [200, 201, 200, 200, 200, 200]
    for response in responses:
        secrets_absent(response.json())
    play = responses[1].json()
    assert [row["kind"] for row in play["questions"]] == list(DATA)
    order_question = next(row for row in play["questions"] if row["kind"] == "order")
    assert [row["text"] for row in order_question["options"]] != ["Sanash", "Tekshirish", "Joylash"]
    match = next(row for row in play["questions"] if row["kind"] == "match")
    assert [row["id"] for row in match["left"]] == ["l1", "l2"]
    assert [row["id"] for row in match["right"]] == ["r1", "r2"]
    assert responses[4].json()["daily"]["id"] == daily.pk


def test_the_quiz_intro(api_as, pharmacy, staff, every_kind):
    every_kind.time_limit_seconds, every_kind.max_attempts = 600, 3
    every_kind.save()
    found = api_as(staff).get(url(pharmacy, f"quizzes/{every_kind.pk}/")).json()
    assert set(found) == INTRO_KEYS
    assert found | {"id": 0} == {
        "id": 0,
        "title": "Sovuq zanjir testi",
        "emoji": "",
        "description": "",
        "questions": 7,
        "time_limit_seconds": 600,
        "pass_percent": 70,
        "max_attempts": 3,
        "attempts_used": 0,
        "retry_at": None,
        "best": None,
        "in_progress": None,
        "can_start": True,
        "reason": None,
    }


def test_a_whole_attempt_through_the_api(api_as, pharmacy, staff, every_kind):
    client = api_as(staff)
    play = client.post(url(pharmacy, f"quizzes/{every_kind.pk}/attempts/"), {}, format="json")
    attempt = Attempt.objects.get(pk=play.json()["id"])
    data = {row.pk: row.data for row in Question.objects.all()}
    for item in attempt.items:
        right = grading.right_answer(item["kind"], data[item["question"]], item["order"])
        saved = client.put(
            url(pharmacy, f"attempts/{attempt.pk}/answers/"),
            {"question": item["question"], "answer": right},
            format="json",
        )
        assert saved.status_code == 204
    resumed = client.get(url(pharmacy, f"attempts/{attempt.pk}/")).json()
    assert len(resumed["answers"]) == 7
    result = client.post(url(pharmacy, f"attempts/{attempt.pk}/finish/")).json()
    assert set(result) == RESULT_KEYS
    assert (result["state"], result["percent"], result["passed"]) == ("finished", 100, True)
    assert (result["score"], result["max_score"]) == (7.0, 7.0)
    assert len(result["review"]) == 7
    first = result["review"][0]
    assert set(first) == {"question", "answer", "correct", "share", "right_answer", "explanation"}
    assert first["correct"] is True and first["explanation"] == EXPLANATION
    again = client.get(url(pharmacy, f"attempts/{attempt.pk}/")).json()
    assert again["state"] == "finished"
    intro = client.get(url(pharmacy, f"quizzes/{every_kind.pk}/")).json()
    assert intro["best"] == {"percent": 100, "passed": True} and intro["attempts_used"] == 1


def test_a_bad_answer_is_400_and_after_the_time_limit_too(api_as, pharmacy, staff, every_kind):
    client = api_as(staff)
    play = client.post(url(pharmacy, f"quizzes/{every_kind.pk}/attempts/"), {}, format="json")
    attempt = Attempt.objects.get(pk=play.json()["id"])
    true_false = next(item for item in attempt.items if item["kind"] == "true_false")
    bad = client.put(
        url(pharmacy, f"attempts/{attempt.pk}/answers/"),
        {"question": true_false["question"], "answer": {"value": "yes"}},
        format="json",
    )
    assert bad.status_code == 400
    Attempt.objects.filter(pk=attempt.pk).update(deadline_at=timezone.now() - timedelta(seconds=1))
    late = client.put(
        url(pharmacy, f"attempts/{attempt.pk}/answers/"),
        {"question": true_false["question"], "answer": {"value": False}},
        format="json",
    )
    assert late.status_code == 400
    assert client.get(url(pharmacy, f"attempts/{attempt.pk}/")).json()["state"] == "expired"


def test_a_person_only_sees_their_own(api_as, pharmacy, staff, every_kind):
    play = api_as(staff).post(
        url(pharmacy, f"quizzes/{every_kind.pk}/attempts/"), {}, format="json"
    )
    colleague = api_as(person(pharmacy))
    attempt_id = play.json()["id"]
    assert colleague.get(url(pharmacy, f"attempts/{attempt_id}/")).status_code == 404
    assert colleague.post(url(pharmacy, f"attempts/{attempt_id}/finish/")).status_code == 404
    daily = DailyQuestion.objects.create(
        company=pharmacy,
        membership=staff,
        day=daily_service.today(pharmacy),
        question=Question.objects.get(kind="true_false"),
    )
    answer = colleague.post(
        url(pharmacy, f"daily/{daily.pk}/answer/"), {"answer": {"value": False}}, format="json"
    )
    assert answer.status_code == 404


def test_another_companys_quiz_and_a_draft_are_404(api_as, pharmacy, staff, other_company):
    theirs = quiz(other_company, [question(other_company, "true_false")])
    draft = quiz(pharmacy, [question(pharmacy, "true_false")], status="draft")
    client = api_as(staff)
    assert client.get(url(pharmacy, f"quizzes/{theirs.pk}/")).status_code == 404
    assert client.get(url(pharmacy, f"quizzes/{draft.pk}/")).status_code == 404
    started = client.post(url(pharmacy, f"quizzes/{draft.pk}/attempts/"), {}, format="json")
    assert started.status_code == 404


def test_everything_is_404_while_learning_is_off(api_as, pharmacy, staff, every_kind):
    pharmacy.features = [feature for feature in pharmacy.features if feature != "learning"]
    pharmacy.save(update_fields=["features"])
    client = api_as(staff)
    for path in (f"quizzes/{every_kind.pk}/", "daily/", "checks/"):
        assert client.get(url(pharmacy, path)).status_code == 404
    started = client.post(url(pharmacy, f"quizzes/{every_kind.pk}/attempts/"), {}, format="json")
    assert started.status_code == 404


def test_why_one_cant_start(api_as, pharmacy, staff, every_kind):
    every_kind.max_attempts = 1
    every_kind.save()
    client = api_as(staff)
    play = client.post(url(pharmacy, f"quizzes/{every_kind.pk}/attempts/"), {}, format="json")
    client.post(url(pharmacy, f"attempts/{play.json()['id']}/finish/"))
    intro = client.get(url(pharmacy, f"quizzes/{every_kind.pk}/")).json()
    assert (intro["can_start"], intro["reason"]) == (
        False,
        "You've used all your attempts at this quiz.",
    )
    again = client.post(url(pharmacy, f"quizzes/{every_kind.pk}/attempts/"), {}, format="json")
    assert again.status_code == 400


def test_the_question_of_the_day_answered_in_the_app(api_as, pharmacy, staff):
    single = question(pharmacy, "single", explanation="+2 dan +8 gacha.")
    daily = DailyQuestion.objects.create(
        company=pharmacy,
        membership=staff,
        day=daily_service.today(pharmacy),
        question=single,
        order=["c", "a", "b"],
    )
    client = api_as(staff)
    shown = client.get(url(pharmacy, "daily/")).json()
    assert shown["streak"] is None  # recognition isn't there yet
    card = shown["daily"]
    assert set(card) == {
        "id",
        "day",
        "question",
        "answered",
        "correct",
        "answer",
        "right_answer",
        "explanation",
    }
    assert [row["id"] for row in card["question"]["options"]] == ["c", "a", "b"]
    assert card["answered"] is False
    result = client.post(
        url(pharmacy, f"daily/{daily.pk}/answer/"), {"answer": {"option": "a"}}, format="json"
    ).json()
    assert result == {
        "correct": True,
        "share": 1.0,
        "right_answer": {"option": "a"},
        "explanation": "+2 dan +8 gacha.",
        "points": None,
        "streak": None,
    }
    card = client.get(url(pharmacy, "daily/")).json()["daily"]
    assert (card["answered"], card["correct"], card["answer"]) == (True, True, {"option": "a"})
    # Answering again gives the same result back and changes nothing.
    again = client.post(
        url(pharmacy, f"daily/{daily.pk}/answer/"), {"answer": {"option": "b"}}, format="json"
    ).json()
    assert again["correct"] is True
    single.refresh_from_db()
    assert (single.answered, single.correct) == (1, 1)


def test_yesterdays_question_cant_be_answered(api_as, pharmacy, staff):
    daily = DailyQuestion.objects.create(
        company=pharmacy,
        membership=staff,
        day=daily_service.today(pharmacy) - timedelta(days=1),
        question=question(pharmacy, "true_false"),
    )
    client = api_as(staff)
    assert client.get(url(pharmacy, "daily/")).json() == {"daily": None, "streak": None}
    late = client.post(
        url(pharmacy, f"daily/{daily.pk}/answer/"), {"answer": {"value": False}}, format="json"
    )
    assert late.status_code == 400


def test_my_checks_open_first_then_the_last_closed(api_as, pharmacy, staff, every_kind):
    check = RegularCheck.objects.create(
        company=pharmacy, quiz=every_kind, title="Dushanba tekshiruvi", weekday=0
    )
    now = timezone.now()
    closed = CheckRound.objects.create(
        company=pharmacy,
        regular_check=check,
        starts_at=now - timedelta(days=7),
        due_at=now - timedelta(days=5),
        closed_at=now - timedelta(days=5),
    )
    current = CheckRound.objects.create(
        company=pharmacy,
        regular_check=check,
        starts_at=now - timedelta(hours=2),
        due_at=now + timedelta(hours=46),
    )
    old_entry = CheckEntry.objects.create(company=pharmacy, check_round=closed, membership=staff)
    entry = CheckEntry.objects.create(company=pharmacy, check_round=current, membership=staff)
    CheckEntry.objects.create(company=pharmacy, check_round=current, membership=person(pharmacy))
    client = api_as(staff)
    rows = client.get(url(pharmacy, "checks/")).json()
    assert [row["entry_id"] for row in rows] == [entry.pk, old_entry.pk]
    assert rows[0] == {
        "entry_id": entry.pk,
        "title": "Dushanba tekshiruvi",
        "quiz_id": every_kind.pk,
        "due_at": rows[0]["due_at"],
        "done": False,
        "passed": None,
    }
    intro = client.get(url(pharmacy, f"quizzes/{every_kind.pk}/?entry={entry.pk}")).json()
    assert intro["max_attempts"] == 1
    play = client.post(
        url(pharmacy, f"quizzes/{every_kind.pk}/attempts/"), {"entry": entry.pk}, format="json"
    )
    client.post(url(pharmacy, f"attempts/{play.json()['id']}/finish/"))
    done = client.get(url(pharmacy, "checks/")).json()[0]
    assert (done["done"], done["passed"]) == (True, False)
    other = CheckEntry.objects.exclude(membership=staff).get()
    assert (
        client.get(url(pharmacy, f"quizzes/{every_kind.pk}/?entry={other.pk}")).status_code == 404
    )
