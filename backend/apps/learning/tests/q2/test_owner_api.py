"""The owner dashboard's endpoints of quizzes, checks, skills, suggestions and drafts
(docs/PLAN-LEARNING.md §13, rule 21): company scope, permissions, branch scope, hidden fields,
audit, and 404 while learning is off."""

import io
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from apps.audit.models import AuditLog
from apps.companies.tests.factories import BranchFactory
from apps.learning import attempts
from apps.learning.models import (
    AnswerLog,
    Attempt,
    Question,
    QuestionDraftJob,
    RegularCheck,
    TutorSuggestion,
)
from apps.learning.tests.q2.fixtures import (
    DATA,
    branch_viewer,
    person,
    question,
    quiz,
    topic,
)
from apps.members.permissions import Perm

pytestmark = pytest.mark.django_db

BASE = "/api/v1/owner/companies/{}/learning/"
PERSON_KEYS = {"id", "name", "photo_url", "position"}


def url(company, rest: str) -> str:
    return BASE.format(company.pk) + rest


@pytest.fixture
def admin(owner_api, manager):
    return owner_api(manager)


@pytest.fixture
def taken(pharmacy, staff):
    """A quiz Alisher took: two tries, the second passed."""
    cold = topic(pharmacy)
    asked = [question(pharmacy, "true_false", topic=cold) for _ in range(2)]
    test = quiz(pharmacy, asked, pass_percent=100)
    for answer in (True, False):
        attempt, _new = attempts.start(test, staff)
        for item in attempt.items:
            attempts.save_answer(attempt, item["question"], {"value": answer})
        attempts.finish(attempt)
    return test


# Questions ---------------------------------------------------------------------------------


def test_the_bank_lists_filters_and_writes(admin, pharmacy):
    cold = topic(pharmacy)
    question(pharmacy, "single", topic=cold)
    question(pharmacy, "number", state="draft")
    made = admin.post(
        url(pharmacy, "questions/"),
        {
            "kind": "true_false",
            "text": "Insulin muzlatgichda saqlanadimi?",
            "data": {"answer": True},
        },
        format="json",
    )
    assert made.status_code == 201
    row = made.json()
    assert (row["kind"], row["state"], row["source"], row["quizzes"]) == (
        "true_false",
        "active",
        "manual",
        0,
    )
    assert AuditLog.objects.filter(action="learning.question_created").exists()
    listed = admin.get(url(pharmacy, f"questions/?topic={cold.pk}")).json()
    assert listed["count"] == 1 and listed["results"][0]["topic"]["name"] == "Sovuq zanjir"
    drafts = admin.get(url(pharmacy, "questions/?state=draft")).json()
    assert [row["kind"] for row in drafts["results"]] == ["number"]
    changed = admin.patch(
        url(pharmacy, f"questions/{row['id']}/"),
        {"text": "Insulin qayerda saqlanadi?", "points": 3},
        format="json",
    ).json()
    assert (changed["text"], changed["points"]) == ("Insulin qayerda saqlanadi?", 3)


def test_a_question_that_doesnt_fit_its_kind_says_where(admin, pharmacy):
    response = admin.post(
        url(pharmacy, "questions/"),
        {"kind": "single", "text": "?", "data": {"options": [{"text": "A", "correct": True}]}},
        format="json",
    )
    assert response.status_code == 400
    assert response.json() == {"data.options": ["How many: 2–6."]}


def test_bulk_activate_and_delete_a_draft(admin, pharmacy):
    drafts = [question(pharmacy, "true_false", state="draft") for _ in range(2)]
    response = admin.post(
        url(pharmacy, "questions/bulk/"),
        {"ids": [row.pk for row in drafts], "state": "active"},
        format="json",
    )
    assert response.json() == {"changed": 2}
    unused = question(pharmacy, "true_false", state="draft")
    assert admin.delete(url(pharmacy, f"questions/{unused.pk}/")).status_code == 204
    assert not Question.objects.filter(pk=unused.pk).exists()


def test_a_picture_for_a_question(admin, pharmacy):
    out = io.BytesIO()
    Image.new("RGB", (30, 20), "white").save(out, "PNG")
    response = admin.post(
        url(pharmacy, "questions/images/"),
        {"file": SimpleUploadedFile("p.png", out.getvalue(), content_type="image/png")},
        format="multipart",
    )
    assert response.status_code == 201
    image = response.json()
    assert (image["width"], image["height"]) == (30, 20)
    made = admin.post(
        url(pharmacy, "questions/"),
        {"kind": "true_false", "text": "?", "data": {"answer": True}, "image_id": image["id"]},
        format="json",
    ).json()
    assert made["image"]["id"] == image["id"] and made["image"]["url"].startswith("/api/v1/files/")


def test_the_bank_is_for_managers_of_learning(owner_api, pharmacy):
    viewer = branch_viewer(pharmacy, [pharmacy.branches.first()])
    response = owner_api(viewer).get(url(pharmacy, "questions/"))
    assert response.status_code == 403


def test_another_companys_question_is_404(admin, pharmacy, other_company):
    theirs = question(other_company, "true_false")
    assert admin.get(url(pharmacy, f"questions/{theirs.pk}/")).status_code == 404
    assert admin.delete(url(pharmacy, f"questions/{theirs.pk}/")).status_code == 404


# Quizzes -----------------------------------------------------------------------------------


def test_quizzes_with_their_pass_rate(admin, pharmacy, taken):
    [row] = admin.get(url(pharmacy, "quizzes/")).json()
    assert (row["attempts"], row["people"], row["pass_rate"], row["average"]) == (2, 1, 100, 50)
    detail = admin.get(url(pharmacy, f"quizzes/{taken.pk}/")).json()
    assert len(detail["question_ids"]) == 2 and detail["in_courses"] == 0


def test_write_publish_archive_and_restore_a_quiz(admin, pharmacy):
    asked = question(pharmacy, "true_false")
    made = admin.post(
        url(pharmacy, "quizzes/"),
        {"title": "Retsept testi", "question_ids": [asked.pk], "pass_percent": 80},
        format="json",
    ).json()
    assert (made["status"], made["question_ids"]) == ("draft", [asked.pk])
    published = admin.post(url(pharmacy, f"quizzes/{made['id']}/publish/")).json()
    assert published["status"] == "published"
    assert admin.post(url(pharmacy, f"quizzes/{made['id']}/archive/")).json()["status"] == (
        "archived"
    )
    assert admin.post(url(pharmacy, f"quizzes/{made['id']}/restore/")).json()["status"] == "draft"
    bad = admin.patch(url(pharmacy, f"quizzes/{made['id']}/"), {"pass_percent": 0}, format="json")
    assert bad.status_code == 400


def test_the_preview_draws_with_the_answers(admin, pharmacy):
    test = quiz(pharmacy, [question(pharmacy, kind) for kind in ("single", "match")])
    rows = admin.get(url(pharmacy, f"quizzes/{test.pk}/preview/")).json()["questions"]
    assert [row["question"]["kind"] for row in rows] == ["single", "match"]
    assert rows[0]["right_answer"] == {"option": "a"}
    assert not Attempt.objects.exists()  # nothing is saved


def test_the_results_attempts_distribution_and_hardest(admin, pharmacy, taken, staff):
    found = admin.get(url(pharmacy, f"quizzes/{taken.pk}/results/")).json()
    assert found["summary"] == {
        "attempts": 2,
        "people": 1,
        "passed_people": 1,
        "pass_rate": 100,
        "average": 50,
    }
    assert [row["percent"] for row in found["attempts"]] == [100, 0]
    assert set(found["attempts"][0]["member"]) == PERSON_KEYS  # no phone, no pay
    counts = {row["start"]: row["count"] for row in found["distribution"]}
    assert (counts[0], counts[90], len(counts)) == (1, 1, 10)
    assert [row["percent"] for row in found["hardest"]] == [50, 50]


def test_results_keep_to_the_viewers_branches(owner_api, pharmacy, taken, staff):
    yunusobod = BranchFactory(company=pharmacy, name="Yunusobod")
    viewer = branch_viewer(pharmacy, [yunusobod])
    found = owner_api(viewer).get(url(pharmacy, f"quizzes/{taken.pk}/results/")).json()
    assert found["attempts"] == [] and found["summary"]["attempts"] == 0
    attempt = Attempt.objects.filter(membership=staff).first()
    assert owner_api(viewer).get(url(pharmacy, f"attempts/{attempt.pk}/")).status_code == 404
    reset = owner_api(viewer).post(
        url(pharmacy, f"quizzes/{taken.pk}/reset/"), {"member": staff.pk}, format="json"
    )
    assert reset.status_code == 403  # learning.view only: no reset at all


def test_a_manager_resets_someones_attempts(admin, pharmacy, taken, staff):
    response = admin.post(
        url(pharmacy, f"quizzes/{taken.pk}/reset/"), {"member": staff.pk}, format="json"
    )
    assert response.json() == {"changed": 2}
    assert AuditLog.objects.filter(action="learning.attempt_reset").exists()


def test_one_attempt_with_every_answer(admin, pharmacy, taken, staff):
    attempt = Attempt.objects.filter(membership=staff).order_by("pk").first()
    taken.show_answers = "never"
    taken.save()
    found = admin.get(url(pharmacy, f"attempts/{attempt.pk}/")).json()
    assert found["member"]["name"] == "Alisher Valiyev" and found["trial"] is False
    assert all(row["right_answer"] == {"value": False} for row in found["review"])


def test_a_viewer_without_manage_reads_but_never_writes(owner_api, pharmacy, taken):
    viewer = branch_viewer(pharmacy, [pharmacy.branches.first()])
    client = owner_api(viewer)
    assert client.get(url(pharmacy, "quizzes/")).status_code == 200
    assert client.post(url(pharmacy, "quizzes/"), {"title": "X"}, format="json").status_code == 403
    assert client.post(url(pharmacy, f"quizzes/{taken.pk}/publish/")).status_code == 403
    assert client.get(url(pharmacy, f"quizzes/{taken.pk}/preview/")).status_code == 403


def test_someone_without_dashboard_access_gets_403(owner_api, pharmacy, staff):
    assert owner_api(staff).get(url(pharmacy, "quizzes/")).status_code == 403


def test_everything_is_404_while_learning_is_off(admin, pharmacy, taken):
    pharmacy.features = [feature for feature in pharmacy.features if feature != "learning"]
    pharmacy.save(update_fields=["features"])
    for path in ("questions/", "quizzes/", "checks/", "skills/", "suggestions/", "drafts/"):
        assert admin.get(url(pharmacy, path)).status_code == 404, path
    assert admin.get(url(pharmacy, "questions/daily/")).status_code == 404


def test_another_companys_quiz_is_404(admin, pharmacy, other_company):
    theirs = quiz(other_company, [question(other_company, "true_false")])
    for path in (f"quizzes/{theirs.pk}/", f"quizzes/{theirs.pk}/results/"):
        assert admin.get(url(pharmacy, path)).status_code == 404


# Checks ------------------------------------------------------------------------------------


def test_checks_and_their_rounds(admin, pharmacy, taken, staff):
    made = admin.post(
        url(pharmacy, "checks/"),
        {
            "title": "Dushanba tekshiruvi",
            "quiz_id": taken.pk,
            "every": "week",
            "weekday": 0,
            "at": "10:00",
            "answer_within_hours": 48,
        },
        format="json",
    )
    assert made.status_code == 201
    check = made.json()
    assert (check["at"], check["state"], check["last_round"]) == ("10:00", "active", None)
    from apps.learning import checks

    row = RegularCheck.objects.get()
    starts = timezone.now() - timedelta(hours=1)
    round_ = checks.start_round(row, starts)
    rounds = admin.get(url(pharmacy, f"checks/{row.pk}/rounds/")).json()
    assert [r["people"] for r in rounds] == [2]
    detail = admin.get(url(pharmacy, f"checks/{row.pk}/rounds/{round_.pk}/")).json()
    assert {entry["member"]["name"] for entry in detail["entries"]} == {
        "Alisher Valiyev",
        "Bekzod Mirzayev",
    }
    paused = admin.post(url(pharmacy, f"checks/{row.pk}/pause/")).json()
    assert paused["state"] == "paused" and paused["next_run_at"] is None
    assert AuditLog.objects.filter(action="learning.check_paused").exists()


# Skills ------------------------------------------------------------------------------------


def test_the_skill_matrix_and_a_persons_skills(admin, pharmacy, taken, staff):
    found = admin.get(url(pharmacy, "skills/")).json()
    assert [column["name"] for column in found["topics"]] == ["Sovuq zanjir"]
    row = next(row for row in found["people"] if row["member"]["id"] == staff.pk)
    cold = str(found["topics"][0]["id"])
    assert row["cells"][cold]["answers"] == 4 and row["cells"][cold]["score"] is not None
    one = admin.get(url(pharmacy, f"skills/{staff.pk}/")).json()
    assert [row["percent"] for row in one["attempts"]] == [100, 0]
    assert one["topics"][0]["topic"]["name"] == "Sovuq zanjir"


def test_a_person_outside_the_viewers_branches_is_404(owner_api, pharmacy, staff, other_company):
    yunusobod = BranchFactory(company=pharmacy, name="Yunusobod")
    viewer = branch_viewer(pharmacy, [yunusobod])
    assert owner_api(viewer).get(url(pharmacy, f"skills/{staff.pk}/")).status_code == 404
    outsider = person(other_company)
    admin_viewer = branch_viewer(pharmacy, [pharmacy.branches.first()])
    response = owner_api(admin_viewer).get(url(pharmacy, f"skills/{outsider.pk}/"))
    assert response.status_code == 404


# Suggestions -------------------------------------------------------------------------------


def test_suggestions_are_worded_accepted_and_dismissed(admin, pharmacy, staff, monkeypatch):
    from apps.learning.tests.factories import CourseFactory

    cold = topic(pharmacy)
    course = CourseFactory(company=pharmacy, title="Sovuq zanjir")
    assign = TutorSuggestion.objects.create(
        company=pharmacy,
        membership=staff,
        kind="assign",
        topic=cold,
        course=course,
        score=40,
        params={"score": 40, "answers": 6},
    )
    praise = TutorSuggestion.objects.create(
        company=pharmacy, membership=staff, kind="praise", params={"points": 45}
    )
    rows = admin.get(url(pharmacy, "suggestions/")).json()
    assert {row["text"] for row in rows} == {
        "Alisher Valiyev is weak in this topic: Sovuq zanjir (40 %). Assign «Sovuq zanjir».",
        "Alisher Valiyev earned 45 points this week: say thanks.",
    }
    given = []
    monkeypatch.setattr(
        "apps.learning.courses.assign",
        lambda course, members, *, by, source="manual", due_at=None: given.append(
            (course.pk, [m.pk for m in members], source)
        ),
    )
    accepted = admin.post(url(pharmacy, f"suggestions/{assign.pk}/accept/")).json()
    assert accepted["state"] == "accepted" and given == [(course.pk, [staff.pk], "tutor")]
    dismissed = admin.post(url(pharmacy, f"suggestions/{praise.pk}/dismiss/")).json()
    assert dismissed["state"] == "dismissed"
    again = admin.post(url(pharmacy, f"suggestions/{praise.pk}/dismiss/"))
    assert again.status_code == 400
    assert AuditLog.objects.filter(action="learning.suggestion_accepted").exists()


def test_suggestions_keep_to_the_viewers_branches(owner_api, pharmacy, staff):
    TutorSuggestion.objects.create(company=pharmacy, membership=staff, kind="praise")
    TutorSuggestion.objects.create(company=pharmacy, kind="lesson_needed", topic=topic(pharmacy))
    yunusobod = BranchFactory(company=pharmacy, name="Yunusobod")
    viewer = branch_viewer(pharmacy, [yunusobod])
    assert owner_api(viewer).get(url(pharmacy, "suggestions/")).json() == []


# Drafts and the daily question ---------------------------------------------------------------


def test_a_drafting_job_from_a_page(admin, pharmacy):
    from apps.knowledge.tests.factories import PageFactory, SpaceFactory

    page = PageFactory(
        space=SpaceFactory(company=pharmacy), body_text="Insulin +2 °C dan +8 °C gacha."
    )
    response = admin.post(
        url(pharmacy, "drafts/"), {"page_id": page.pk, "count": 3, "engine": "rules"}, format="json"
    )
    assert response.status_code == 201
    job = QuestionDraftJob.objects.get()
    assert (job.page, job.count, job.engine) == (page, 3, "rules")
    detail = admin.get(url(pharmacy, f"drafts/{job.pk}/")).json()
    assert detail["page"] == {"id": page.pk, "title": page.title} and "questions" in detail
    both = admin.post(url(pharmacy, "drafts/"), {"count": 3}, format="json")
    assert both.status_code == 400


def test_the_question_of_the_days_settings(admin, owner_api, pharmacy):
    shown = admin.get(url(pharmacy, "questions/daily/")).json()
    assert (shown["daily_question"], shown["daily_at"]) == (False, "11:00")
    changed = admin.patch(
        url(pharmacy, "questions/daily/"),
        {"daily_question": True, "daily_at": "09:30"},
        format="json",
    ).json()
    assert (changed["daily_question"], changed["daily_at"]) == (True, "09:30")
    assert AuditLog.objects.filter(action="learning.daily_changed").exists()
    viewer = branch_viewer(pharmacy, [pharmacy.branches.first()])
    blocked = owner_api(viewer).patch(
        url(pharmacy, "questions/daily/"), {"daily_question": False}, format="json"
    )
    assert blocked.status_code == 403


def test_answer_logs_never_leak_into_another_company(admin, pharmacy, other_company):
    outsider = person(other_company)
    theirs = question(other_company, "true_false", topic=topic(other_company))
    AnswerLog.objects.create(
        company=other_company,
        membership=outsider,
        question=theirs,
        topic=theirs.topic,
        source="daily",
        correct=True,
        share=1,
        at=timezone.now(),
    )
    found = admin.get(url(pharmacy, "skills/")).json()
    assert found["topics"] == [] and all(
        row["member"]["id"] != outsider.pk for row in found["people"]
    )
    assert DATA  # the shared data stays importable for the other tests
    assert Perm.LEARNING_MANAGE
