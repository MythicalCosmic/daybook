"""The employee endpoints of courses and lessons (docs/PLAN-LEARNING.md §13 Q1): the exact shapes
the mini app codes against, 404 while the module is off, a person only ever sees their own."""

from datetime import timedelta

import pytest
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.core.storage import learning_storage
from apps.learning import courses
from apps.learning.models import Assignment, CourseStep, Lesson, LessonProgress, Status, Video
from apps.learning.tests.factories import (
    AssignmentFactory,
    CourseFactory,
    CourseStepFactory,
    LessonFactory,
    QuizFactory,
)
from apps.learning.tests.helpers_courses import turn_on
from apps.members.models import Position

pytestmark = pytest.mark.django_db

BASE = "/api/v1/companies/{}/learning/"
COURSE_CARD = {"id", "title", "emoji", "color", "description", "mandatory", "steps", "minutes"}
ASSIGNMENT_CARD = {
    "id",
    "state",
    "percent",
    "steps_done",
    "steps_total",
    "due_at",
    "late",
    "completed_at",
    "certificate_url",
    "course",
}
STEP = {
    "id",
    "kind",
    "title",
    "emoji",
    "required",
    "done",
    "locked",
    "done_at",
    "lesson_id",
    "page_id",
    "quiz_id",
    "minutes",
    "best_percent",
}
LESSON = {
    "id",
    "title",
    "emoji",
    "summary",
    "notes_html",
    "source",
    "video",
    "youtube_id",
    "duration_seconds",
    "processing",
    "topics",
    "completion_percent",
    "progress",
    "next",
}


@pytest.fixture
def staff(company, member):
    turn_on(company)
    return member(company)


@pytest.fixture
def app(api_as, staff):
    return api_as(staff)


def url(company, rest=""):
    return BASE.format(company.pk) + rest


def ready_video(company, seconds=120):
    name = learning_storage.save(f"videos/{company.pk}/v.mp4", ContentFile(b"\x00" * 64))
    poster = learning_storage.save(f"posters/{company.pk}/p.jpg", ContentFile(b"\xff\xd8\xff"))
    return Video.objects.create(
        company=company,
        state=Video.State.READY,
        file=name,
        poster=poster,
        duration_seconds=seconds,
        width=1280,
        height=720,
    )


def test_everything_answers_404_while_the_module_is_off(company, member, api_as):
    person = member(company)
    lesson = LessonFactory(company=company)
    course = CourseFactory(company=company)
    row = AssignmentFactory(course=course, membership=person)
    client = api_as(person)
    for method, rest in [
        ("get", ""),
        ("get", f"courses/{course.pk}/"),
        ("post", f"courses/{course.pk}/start/"),
        ("get", f"lessons/{lesson.pk}/"),
        ("post", f"lessons/{lesson.pk}/progress/"),
        ("get", f"assignments/{row.pk}/certificate/"),
    ]:
        response = getattr(client, method)(url(company, rest), {}, format="json")
        assert response.status_code == 404, (method, rest, response.status_code)


def test_home_lists_what_is_open_done_and_on_offer(company, staff, app):
    now = timezone.now()
    late = CourseFactory(company=company, mandatory=True, title="Sovuq zanjir")
    CourseStepFactory(course=late, lesson=LessonFactory(company=company, duration_seconds=125))
    soon = CourseFactory(company=company, title="Kassa")
    CourseStepFactory(course=soon)
    finished = CourseFactory(company=company, title="Yangi xodim")
    CourseStepFactory(course=finished)
    optional = CourseFactory(company=company, title="Retsept")
    CourseStepFactory(course=optional)
    hidden = CourseFactory(company=company, title="Kuryerlar", audience_all=False)
    hidden.positions.set([Position.objects.create(company=company, name="Courier")])
    CourseStepFactory(course=hidden)
    CourseFactory(company=company, title="Draft", status=Status.DRAFT)
    AssignmentFactory(course=late, membership=staff, due_at=now - timedelta(days=2))
    AssignmentFactory(course=soon, membership=staff, due_at=now + timedelta(days=3))
    AssignmentFactory(
        course=finished,
        membership=staff,
        state=Assignment.State.COMPLETED,
        completed_at=now,
        percent=100,
        certificate_no="SRT-2026-0001",
    )

    response = app.get(url(company))

    assert response.status_code == 200, response.content
    body = response.json()
    assert set(body) == {"todo", "done", "catalog", "certificates"}
    assert [card["course"]["title"] for card in body["todo"]] == ["Sovuq zanjir", "Kassa"]
    first = body["todo"][0]
    assert set(first) == ASSIGNMENT_CARD and set(first["course"]) == COURSE_CARD
    assert first["late"] is True and body["todo"][1]["late"] is False
    assert first["course"]["minutes"] == 3 and first["course"]["steps"] == 1
    assert first["course"]["mandatory"] is True
    done = body["done"][0]
    assert done["state"] == "completed" and done["certificate_url"].startswith("/api/v1/files/")
    assert [course["title"] for course in body["catalog"]] == ["Retsept"]
    assert body["certificates"] == 1


def test_a_course_shows_my_steps_locked_and_done(company, staff, app):
    course = CourseFactory(company=company, sequential=True)
    lesson_step = CourseStepFactory(course=course)
    quiz = QuizFactory(company=company, time_limit_seconds=300)
    quiz_step = CourseStepFactory(course=course, kind=CourseStep.Kind.QUIZ, lesson=None, quiz=quiz)
    row = courses.assign(course, [staff], by=None)[0]

    body = app.get(url(company, f"courses/{course.pk}/")).json()

    assert set(body) == COURSE_CARD | {"sequential", "certificate", "assignment", "can_start"}
    assert body["can_start"] is False and body["assignment"]["id"] == row.pk
    assert [set(step) for step in body["steps"]] == [STEP, STEP]
    first, second = body["steps"]
    assert (first["kind"], first["lesson_id"], first["locked"], first["done"]) == (
        "lesson",
        lesson_step.lesson_id,
        False,
        False,
    )
    assert (second["kind"], second["quiz_id"], second["locked"], second["minutes"]) == (
        "quiz",
        quiz_step.quiz_id,
        True,
        5,
    )
    LessonProgress.objects.create(
        company=company,
        lesson=lesson_step.lesson,
        membership=staff,
        percent=95,
        first_at=timezone.now(),
        last_at=timezone.now(),
        completed_at=timezone.now(),
    )
    courses.refresh(row)
    first, second = app.get(url(company, f"courses/{course.pk}/")).json()["steps"]
    assert first["done"] and first["done_at"] and first["best_percent"] == 95
    assert not second["locked"]


def test_courses_not_meant_for_me_are_404_and_optional_ones_can_be_started(company, staff, app):
    other = CourseFactory(company=company, audience_all=False)
    other.positions.set([Position.objects.create(company=company, name="Courier")])
    assert app.get(url(company, f"courses/{other.pk}/")).status_code == 404
    draft = CourseFactory(company=company, status=Status.DRAFT)
    assert app.get(url(company, f"courses/{draft.pk}/")).status_code == 404
    optional = CourseFactory(company=company)
    CourseStepFactory(course=optional)
    assert app.get(url(company, f"courses/{optional.pk}/")).json()["can_start"] is True
    started = app.post(url(company, f"courses/{optional.pk}/start/"))
    assert started.status_code == 200, started.content
    assert set(started.json()) == ASSIGNMENT_CARD and started.json()["state"] == "assigned"
    again = app.post(url(company, f"courses/{optional.pk}/start/"))
    assert again.json()["id"] == started.json()["id"]


def test_a_lesson_to_watch_with_signed_links_progress_and_the_next_step(company, staff, app):
    video = ready_video(company)
    lesson = LessonFactory(
        company=company,
        source=Lesson.Source.UPLOAD,
        video=video,
        youtube_id="",
        duration_seconds=120,
        notes="<p>Muzlatgich</p>",
    )
    course = CourseFactory(company=company)
    CourseStepFactory(course=course, lesson=lesson)
    quiz = QuizFactory(company=company, title="Sovuq zanjir testi")
    CourseStepFactory(course=course, kind=CourseStep.Kind.QUIZ, lesson=None, quiz=quiz)
    courses.assign(course, [staff], by=None)

    body = app.get(url(company, f"lessons/{lesson.pk}/?course={course.pk}")).json()

    assert set(body) == LESSON
    assert body["source"] == "upload" and body["youtube_id"] == ""
    assert set(body["video"]) == {"url", "poster_url", "duration_seconds", "width", "height"}
    assert body["video"]["url"].startswith("/api/v1/files/")
    assert body["video"]["poster_url"].startswith("/api/v1/files/")
    assert body["processing"] is False and body["progress"] is None
    assert body["completion_percent"] == 90 and body["notes_html"] == "<p>Muzlatgich</p>"
    assert body["next"] == {"kind": "quiz", "id": quiz.pk, "title": "Sovuq zanjir testi"}
    reported = app.post(
        url(company, f"lessons/{lesson.pk}/progress/"),
        {"session": "abc", "position": 10, "duration": 120, "ranges": [[0, 10]], "playing": True},
        format="json",
    )
    assert reported.status_code == 200, reported.content
    assert reported.json() == {
        "percent": 8,
        "position": 10,
        "completed": False,
        "completed_now": False,
        "points": None,
    }
    again = app.get(url(company, f"lessons/{lesson.pk}/")).json()
    assert again["progress"] == {
        "percent": 8,
        "position": 10,
        "completed_at": None,
        "ranges": [[0, 10]],
    }
    assert again["next"] is None


def test_youtube_and_processing_lessons(company, staff, app):
    link = LessonFactory(company=company, youtube_id="dQw4w9WgXcQ")
    body = app.get(url(company, f"lessons/{link.pk}/")).json()
    assert (body["source"], body["youtube_id"], body["video"]) == ("youtube", "dQw4w9WgXcQ", None)
    waiting = Video.objects.create(company=company, state=Video.State.PROCESSING)
    upload = LessonFactory(
        company=company, source=Lesson.Source.UPLOAD, video=waiting, youtube_id=""
    )
    body = app.get(url(company, f"lessons/{upload.pk}/")).json()
    assert body["processing"] is True and body["video"] is None
    refused = app.post(
        url(company, f"lessons/{upload.pk}/progress/"),
        {"session": "x", "position": 0, "ranges": [[0, 5]]},
        format="json",
    )
    assert refused.status_code == 400
    assert (
        app.post(url(company, f"lessons/{link.pk}/progress/"), {}, format="json").status_code == 400
    )


def test_lessons_i_cant_open_are_404(company, other_company, staff, app):
    turn_on(other_company)
    theirs = LessonFactory(company=other_company)
    assert app.get(url(company, f"lessons/{theirs.pk}/")).status_code == 404
    draft = LessonFactory(company=company, status=Status.DRAFT)
    assert app.get(url(company, f"lessons/{draft.pk}/")).status_code == 404
    narrow = LessonFactory(company=company, audience_all=False)
    assert app.get(url(company, f"lessons/{narrow.pk}/")).status_code == 404
    assert (
        app.post(
            url(company, f"lessons/{narrow.pk}/progress/"),
            {"session": "s", "position": 0},
            format="json",
        ).status_code
        == 404
    )


def test_my_certificate_as_a_pdf_and_nobody_elses(company, staff, app, member):
    course = CourseFactory(company=company, title="Sovuq zanjir")
    step = CourseStepFactory(course=course)
    LessonProgress.objects.create(
        company=company,
        lesson=step.lesson,
        membership=staff,
        percent=100,
        first_at=timezone.now(),
        last_at=timezone.now(),
        completed_at=timezone.now(),
    )
    mine = courses.assign(course, [staff], by=None)[0]
    assert mine.state == Assignment.State.COMPLETED and mine.certificate_no
    response = app.get(
        url(company, f"assignments/{mine.pk}/certificate/"), HTTP_ACCEPT="application/pdf"
    )
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert b"".join(response.streaming_content).startswith(b"%PDF")
    someone = member(company)
    theirs = AssignmentFactory(
        course=course,
        membership=someone,
        state=Assignment.State.COMPLETED,
        certificate_no="SRT-2026-0099",
    )
    assert app.get(url(company, f"assignments/{theirs.pk}/certificate/")).status_code == 404
    unfinished = CourseFactory(company=company)
    open_row = AssignmentFactory(course=unfinished, membership=staff)
    assert app.get(url(company, f"assignments/{open_row.pk}/certificate/")).status_code == 404
