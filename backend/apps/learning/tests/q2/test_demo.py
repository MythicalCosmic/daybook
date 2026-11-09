"""Package Q2's demo on Demo Dorixona, through the root `demo_people` fixture: on its own
(without Q1's courses) and after the knowledge base's demo, as seed_demo runs it."""

from collections import Counter

import pytest
from django.utils import timezone

from apps.companies.models import Feature
from apps.inbox.models import Notification
from apps.knowledge import demo as knowledge_demo
from apps.learning import demo_quizzes, skills
from apps.learning.models import (
    AnswerLog,
    Attempt,
    CheckRound,
    DailyQuestion,
    Question,
    QuestionDraftJob,
    Quiz,
    RegularCheck,
    TutorSuggestion,
)
from apps.learning.tests.q2.fixtures import ai_on, switch_on

pytestmark = pytest.mark.django_db


@pytest.fixture
def built(company, demo_people):
    switch_on(company, Feature.RECOGNITION)
    ai_on(company, tutor=False)
    company.default_language = "uz"
    company.save(update_fields=["default_language"])
    people = demo_people(company)
    now = timezone.now()
    knowledge_demo.seed(company, people, now)
    demo_quizzes.seed(company, people, now)
    return company, people, now


def test_the_bank_has_every_kind_of_pharmacy_question(built):
    company, _people, _now = built
    kinds = Counter(
        Question.objects.filter(company=company, source="manual").values_list("kind", flat=True)
    )
    assert sum(kinds.values()) >= 40
    assert set(kinds) == {"single", "multi", "true_false", "order", "match", "text", "number"}
    assert not Question.objects.filter(company=company, source="manual", topic=None).exists()
    assert set(Quiz.objects.filter(company=company).values_list("title", "status")) == {
        ("Sovuq zanjir testi", "published"),
        ("Retsept testi", "published"),
        ("Haftalik tekshiruv testi", "published"),
    }


def test_four_weeks_of_answers_tell_the_story(built):
    company, people, _now = built
    assert Attempt.objects.filter(company=company, trial=False).count() >= 10
    assert AnswerLog.objects.filter(company=company, source="daily").exists()
    found = skills.mastery(company)
    cold = Question.objects.filter(company=company, text__startswith="Insulin qaysi").get().topic
    madina = found[(people["madina"].pk, cold.pk)]
    alisher = found[(people["worker"].pk, cold.pk)]
    assert madina.score >= 85 and alisher.score is not None and alisher.score < 60


def test_the_weekly_check_has_closed_rounds_and_an_open_one(built):
    company, people, now = built
    check = RegularCheck.objects.get(company=company, title="Dushanba tekshiruvi")
    rounds = list(CheckRound.objects.filter(regular_check=check).order_by("starts_at"))
    assert len(rounds) >= 3
    assert rounds[-1].closed_at is None and rounds[-1].due_at > now
    assert all(row.closed_at is not None for row in rounds[:-1])
    open_entry = rounds[-1].entries.get(membership=people["worker"])
    assert open_entry.attempt is None  # Alisher still has to answer this week
    assert check.next_run_at > now


def test_the_daily_question_history_and_todays_question(built):
    company, people, _now = built
    assert DailyQuestion.objects.filter(company=company, answered_at__isnull=False).count() >= 10
    assert not DailyQuestion.objects.filter(
        membership=people["worker"], answered_at__isnull=False, day=timezone.localdate()
    ).exists()


def test_the_tutors_story(built):
    company, people, _now = built
    open_rows = TutorSuggestion.objects.filter(company=company, state="open")
    assert open_rows.filter(kind="mentor", membership=people["madina"]).exists()
    assert open_rows.filter(kind="lesson_needed").exists()
    reports = Notification.objects.filter(company=company, kind="learning.tutor_report")
    assert reports.filter(recipient=people["owner"]).exists()
    assert QuestionDraftJob.objects.filter(company=company, state="done").exists()
    assert Question.objects.filter(company=company, state="draft", source="rules").exists()
