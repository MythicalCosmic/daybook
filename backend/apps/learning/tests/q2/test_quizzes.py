"""The question bank, quizzes and the draw (docs/PLAN-LEARNING.md §4.3, §4.7)."""

import io
import random
from collections import Counter

import pytest
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.learning import quizzes
from apps.learning.grading import InvalidQuestion
from apps.learning.models import AnswerLog, Attempt, Question, Quiz, Status
from apps.learning.tests.q2.fixtures import DATA, person, question, quiz, topic

pytestmark = pytest.mark.django_db


def png(width=40, height=30) -> SimpleUploadedFile:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "teal").save(out, "PNG")
    return SimpleUploadedFile("photo.png", out.getvalue(), content_type="image/png")


# Questions -----------------------------------------------------------------------------------


def test_a_manager_writes_a_question_of_each_kind(pharmacy, manager):
    cold = topic(pharmacy)
    for kind, data in DATA.items():
        made = quizzes.create_question(
            pharmacy, by=manager, kind=kind, text=f"  {kind}?  ", data=data, topic_id=cold.pk
        )
        assert made.text == f"{kind}?"
        assert made.state == Question.State.ACTIVE
        assert made.topic == cold
    assert AuditLog.objects.filter(action="learning.question_created").count() == len(DATA)


def test_staff_cant_write_questions(pharmacy, staff):
    with pytest.raises(PermissionDenied):
        quizzes.create_question(
            pharmacy, by=staff, kind="true_false", text="?", data=DATA["true_false"]
        )


def test_a_question_must_fit_its_kind(pharmacy, manager):
    with pytest.raises(InvalidQuestion) as found:
        quizzes.create_question(
            pharmacy, by=manager, kind="single", text="?", data={"options": [{"text": "A"}]}
        )
    assert "data.options" in found.value.errors
    with pytest.raises(DomainError):
        quizzes.create_question(
            pharmacy, by=manager, kind="true_false", text="?", data=DATA["true_false"], points=11
        )


def test_a_topic_of_another_company_is_refused(pharmacy, manager, other_company):
    with pytest.raises(DomainError):
        quizzes.create_question(
            pharmacy,
            by=manager,
            kind="true_false",
            text="?",
            data=DATA["true_false"],
            topic_id=topic(other_company).pk,
        )


def test_the_kind_stays_once_answered(pharmacy, manager):
    made = question(pharmacy, "single", answered=3)
    with pytest.raises(DomainError):
        quizzes.update_question(made, by=manager, kind="true_false", data={"answer": True})
    fresh = question(pharmacy, "single")
    quizzes.update_question(fresh, by=manager, kind="true_false", data={"answer": True})
    fresh.refresh_from_db()
    assert (fresh.kind, fresh.data) == ("true_false", {"answer": True})
    log = AuditLog.objects.filter(action="learning.question_changed").latest("pk")
    assert log.details["fields"] == ["data", "kind"]


def test_a_draft_is_checked_again_when_put_into_use(pharmacy, manager):
    broken = question(pharmacy, "single", state="draft", data={"options": []})
    with pytest.raises(InvalidQuestion):
        quizzes.set_question_state(broken, "active", by=manager)
    good = question(pharmacy, "single", state="draft")
    assert quizzes.set_question_state(good, "active", by=manager).state == "active"


def test_bulk_archive(pharmacy, manager, other_company):
    mine = [question(pharmacy, "true_false") for _ in range(3)]
    theirs = question(other_company, "true_false")
    changed = quizzes.bulk_state(
        pharmacy, [row.pk for row in mine] + [theirs.pk], "archived", by=manager
    )
    assert changed == 3
    theirs.refresh_from_db()
    assert theirs.state == "active"


def test_only_a_question_nobody_was_asked_is_deleted(pharmacy, manager, staff):
    unused = question(pharmacy, "true_false", state="draft")
    quizzes.delete_question(unused, by=manager)
    assert not Question.objects.filter(pk=unused.pk).exists()
    asked = question(pharmacy, "true_false")
    test = quiz(pharmacy, [asked])
    Attempt.objects.create(
        company=pharmacy,
        quiz=test,
        membership=staff,
        started_at=test.created_at,
        items=[{"question": asked.pk, "kind": "true_false", "points": 1, "order": []}],
    )
    with pytest.raises(DomainError):
        quizzes.delete_question(asked, by=manager)


def test_a_picture_is_re_encoded_and_opened_by_whoever_was_asked(pharmacy, manager, staff):
    image = quizzes.save_image(pharmacy, png(), by=manager)
    assert image.file.name.endswith(".jpg") and (image.width, image.height) == (40, 30)
    asked = question(pharmacy, "true_false", image=image)
    assert quizzes.may_open_image(manager.user, pharmacy.pk, image.pk)
    assert not quizzes.may_open_image(staff.user, pharmacy.pk, image.pk)
    test = quiz(pharmacy, [asked])
    Attempt.objects.create(
        company=pharmacy,
        quiz=test,
        membership=staff,
        started_at=test.created_at,
        items=[{"question": asked.pk, "kind": "true_false", "points": 1, "order": []}],
    )
    assert quizzes.may_open_image(staff.user, pharmacy.pk, image.pk)
    assert quizzes.image_url(image, staff.user).startswith("/api/v1/files/")


def test_a_file_that_isnt_a_picture_is_refused(pharmacy, manager):
    fake = SimpleUploadedFile("photo.jpg", b"<svg onload=alert(1)>", content_type="image/jpeg")
    with pytest.raises(DomainError):
        quizzes.save_image(pharmacy, fake, by=manager)


# Quizzes ---------------------------------------------------------------------------------------


def test_a_fixed_quiz_keeps_its_list_in_order(pharmacy, manager):
    first, second, third = (question(pharmacy, "true_false") for _ in range(3))
    made = quizzes.create_quiz(
        pharmacy, by=manager, title="Retsept testi", question_ids=[third.pk, first.pk, second.pk]
    )
    assert made.status == Status.DRAFT
    assert [row.pk for row in quizzes.fixed_list(made)] == [third.pk, first.pk, second.pk]
    quizzes.set_questions(made, [second.pk, third.pk], by=manager)
    assert [row.pk for row in quizzes.fixed_list(made)] == [second.pk, third.pk]


def test_publishing_needs_questions_in_use(pharmacy, manager):
    empty = quizzes.create_quiz(pharmacy, by=manager, title="Bo‘sh")
    with pytest.raises(DomainError):
        quizzes.publish_quiz(empty, by=manager)
    draft_only = question(pharmacy, "true_false", state="draft")
    quizzes.set_questions(empty, [draft_only.pk], by=manager)
    with pytest.raises(DomainError):
        quizzes.publish_quiz(empty, by=manager)
    cold = topic(pharmacy)
    question(pharmacy, "single", topic=cold)
    random_quiz = quizzes.create_quiz(
        pharmacy, by=manager, title="Tasodifiy", mode="random", topic_ids=[cold.pk]
    )
    assert quizzes.publish_quiz(random_quiz, by=manager).status == Status.PUBLISHED


def test_quiz_settings_are_checked(pharmacy, manager):
    for bad in (
        {"pass_percent": 0},
        {"time_limit_seconds": 5},
        {"max_attempts": 0},
        {"mode": "exam"},
        {"question_count": 99},
        {"show_answers": "always"},
    ):
        with pytest.raises(DomainError):
            quizzes.create_quiz(pharmacy, by=manager, title="Test", **bad)
    made = quizzes.create_quiz(
        pharmacy, by=manager, title="Test", time_limit_seconds=None, max_attempts=None
    )
    assert made.time_limit_seconds is None and made.max_attempts is None


def test_archive_restore_and_delete(pharmacy, manager, staff):
    made = quiz(pharmacy, [question(pharmacy, "true_false")])
    quizzes.archive_quiz(made, by=manager)
    made.refresh_from_db()
    assert made.status == Status.ARCHIVED and made.archived_at is not None
    quizzes.restore_quiz(made, by=manager)
    made.refresh_from_db()
    assert made.status == Status.DRAFT
    Attempt.objects.create(
        company=pharmacy, quiz=made, membership=staff, started_at=made.created_at
    )
    with pytest.raises(DomainError):
        quizzes.delete_quiz(made, by=manager)
    unused = quiz(pharmacy, [question(pharmacy, "true_false")], status=Status.DRAFT)
    quizzes.delete_quiz(unused, by=manager)
    assert not Quiz.objects.filter(pk=unused.pk).exists()


# The draw --------------------------------------------------------------------------------------


def test_a_fixed_quiz_asks_its_list_and_never_a_draft_or_an_archived_question(pharmacy, staff):
    asked = [question(pharmacy, "true_false") for _ in range(3)]
    draft = question(pharmacy, "true_false", state="draft")
    archived = question(pharmacy, "true_false", state="archived")
    made = quiz(pharmacy, [asked[0], draft, asked[1], archived, asked[2]])
    assert quizzes.draw(made, staff) == asked
    made.shuffle_questions = True
    shuffled = quizzes.draw(made, staff, rng=random.Random(3))
    assert sorted(row.pk for row in shuffled) == sorted(row.pk for row in asked)


def test_a_random_draw_spreads_over_the_topics(pharmacy, staff):
    names = ("Sovuq zanjir", "Retsept", "Kassa")
    for name in names:
        for _ in range(4):
            question(pharmacy, "true_false", topic=topic(pharmacy, name))
    made = quiz(pharmacy, mode="random", question_count=6)
    made.topics.set([topic(pharmacy, name) for name in names])
    for seed in range(10):
        drawn = quizzes.draw(made, staff, rng=random.Random(seed))
        assert len(drawn) == 6
        assert set(Counter(row.topic.name for row in drawn).values()) == {2}


def test_a_random_draw_mixes_the_kinds(pharmacy, staff):
    cold = topic(pharmacy)
    for kind in ("single", "true_false", "number"):
        for _ in range(3):
            question(pharmacy, kind, topic=cold)
    made = quiz(pharmacy, mode="random", question_count=3)
    made.topics.set([cold])
    for seed in range(10):
        drawn = quizzes.draw(made, staff, rng=random.Random(seed))
        assert sorted(row.kind for row in drawn) == ["number", "single", "true_false"]


def test_a_random_draw_takes_the_list_too_and_all_when_fewer_are_left(pharmacy, staff):
    cold = topic(pharmacy)
    in_topic = question(pharmacy, "single", topic=cold)
    listed = question(pharmacy, "true_false")
    question(pharmacy, "true_false", topic=cold, state="draft")
    made = quiz(pharmacy, [listed], mode="random", question_count=10)
    made.topics.set([cold])
    assert {row.pk for row in quizzes.draw(made, staff)} == {in_topic.pk, listed.pk}
    assert quizzes.available(made) == 2


def test_a_random_draw_asks_first_what_was_not_answered_right_lately(pharmacy, staff):
    cold = topic(pharmacy)
    known = [question(pharmacy, "true_false", topic=cold) for _ in range(3)]
    unknown = [question(pharmacy, "true_false", topic=cold) for _ in range(3)]
    made = quiz(pharmacy, mode="random", question_count=3)
    made.topics.set([cold])
    attempt = Attempt.objects.create(
        company=pharmacy,
        quiz=made,
        membership=staff,
        started_at=made.created_at,
        finished_at=made.created_at,
        state=Attempt.State.FINISHED,
    )
    for row in known:
        AnswerLog.objects.create(
            company=pharmacy,
            membership=staff,
            question=row,
            topic=cold,
            source="attempt",
            attempt=attempt,
            correct=True,
            share=1,
            at=made.created_at,
        )
    for seed in range(10):
        drawn = quizzes.draw(made, staff, rng=random.Random(seed))
        assert {row.pk for row in drawn} == {row.pk for row in unknown}
    # Somebody else answered nothing yet: anything goes.
    other = person(pharmacy)
    assert len(quizzes.draw(made, other)) == 3
