"""The owner endpoints of courses, lessons and videos (docs/PLAN-LEARNING.md §11, §13; rule 21):
company scope, permissions, branch scope, audit, the module switch, the upload protocol."""

from datetime import date, datetime, timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.companies.models import Branch
from apps.learning import courses, queries
from apps.learning.models import Assignment, Course, LessonProgress, Status, Video
from apps.learning.tests.factories import (
    AssignmentFactory,
    CourseFactory,
    CourseStepFactory,
    LessonFactory,
)
from apps.learning.tests.helpers_courses import manager, role, turn_on

pytestmark = pytest.mark.django_db

BASE = "/api/v1/owner/companies/{}/learning/"


@pytest.fixture
def boss(company, member):
    turn_on(company)
    return manager(company, member)


@pytest.fixture
def api(owner_api, boss):
    return owner_api(boss)


def url(company, rest=""):
    return BASE.format(company.pk) + rest


def viewer(company, member):
    """Reads training but changes nothing."""
    made = role(company, "Training viewer", "learning.view", branches_all=True)
    return member(company, made.name)


def test_the_module_switch_and_another_company(company, other_company, member, owner_api):
    turn_on(other_company)
    theirs = manager(other_company, member)
    mine = CourseFactory(company=company)
    client = owner_api(theirs)
    assert client.get(url(other_company, f"courses/{mine.pk}/")).status_code == 404
    assert client.get(url(company, "overview/")).status_code == 404  # not their company
    switched_off = manager(company, member)
    assert owner_api(switched_off).get(url(company, "overview/")).status_code == 404


def test_reading_needs_learning_view_and_changing_learning_manage(company, boss, member, owner_api):
    reader = owner_api(viewer(company, member))
    course = CourseFactory(company=company)
    assert reader.get(url(company, "courses/")).status_code == 200
    assert reader.get(url(company, f"courses/{course.pk}/")).status_code == 200
    assert reader.post(url(company, "courses/"), {"title": "X"}, format="json").status_code == 403
    assert reader.post(url(company, f"courses/{course.pk}/archive/")).status_code == 403
    assert reader.patch(url(company, "settings/"), {}, format="json").status_code == 403
    nobody = owner_api(member(company, role(company, "Dashboard only").name))
    assert nobody.get(url(company, "courses/")).status_code == 403


def test_a_course_from_draft_to_people(company, boss, api, member):
    lesson = LessonFactory(company=company, duration_seconds=600)
    made = api.post(
        url(company, "courses/"),
        {"title": "Sovuq zanjir", "mandatory": False, "due_days": 7, "color": "sky"},
        format="json",
    )
    assert made.status_code == 201, made.content
    course_id = made.json()["id"]
    assert made.json()["status"] == "draft" and made.json()["step_list"] == []
    added = api.post(
        url(company, f"courses/{course_id}/steps/"),
        {"kind": "lesson", "target_id": lesson.pk},
        format="json",
    )
    assert added.status_code == 201, added.content
    assert added.json()["minutes"] == 10
    step_id = added.json()["step_list"][0]["id"]
    assert (
        api.patch(
            url(company, f"courses/{course_id}/steps/{step_id}/"),
            {"required": False},
            format="json",
        ).json()["step_list"][0]["required"]
        is False
    )
    assert api.post(url(company, f"courses/{course_id}/publish/")).json()["status"] == "published"
    person = member(company)
    assigned = api.post(
        url(company, f"courses/{course_id}/assign/"),
        {"member_ids": [person.pk], "due_on": "2026-12-01"},
        format="json",
    )
    assert assigned.json() == {"count": 1}
    row = Assignment.objects.get(course_id=course_id, membership=person)
    local = timezone.localtime(row.due_at, queries.zone(company))
    assert local.strftime("%Y-%m-%d %H:%M:%S") == "2026-12-01 23:59:59"
    people = api.get(url(company, f"courses/{course_id}/people/")).json()
    assert people["counts"]["open"] == 1
    entry = people["results"][0]
    assert entry["member"]["id"] == person.pk
    assert "phone" not in entry["member"] and "salary" not in str(entry)
    assert api.post(url(company, f"courses/{course_id}/remind/"), {}, format="json").json() == {
        "count": 1
    }
    candidates = api.get(url(company, f"courses/{course_id}/candidates/")).json()
    assert any(item["id"] == person.pk and item["assigned"] for item in candidates)
    actions = set(AuditLog.objects.values_list("action", flat=True))
    assert {
        "learning.course_created",
        "learning.course_changed",
        "learning.course_published",
        "learning.assigned",
        "learning.reminded",
    } <= actions


def test_branch_scope_on_people_and_assignments(company, member, owner_api):
    turn_on(company)
    north = company.branches.first()
    south = Branch.objects.create(company=company, name="Yunusobod")
    lead = manager(company, member, branches=[north])
    mine, theirs = member(company), member(company)
    mine.branches.set([north])
    theirs.branches.set([south])
    course = CourseFactory(company=company, mandatory=True)
    CourseStepFactory(course=course)
    rows = {row.membership_id: row for row in courses.assign(course, [mine, theirs], by=None)}
    client = owner_api(lead)
    people = client.get(url(company, f"courses/{course.pk}/people/")).json()["results"]
    assert [entry["member"]["id"] for entry in people] == [mine.pk]
    grid = client.get(url(company, "people/")).json()
    listed = {row["member"]["id"] for row in grid["rows"]}
    assert mine.pk in listed and theirs.pk not in listed
    assert client.get(url(company, f"people/{theirs.pk}/")).status_code == 404
    assert client.get(url(company, f"people/{mine.pk}/")).status_code == 200
    blocked = client.post(
        url(company, f"assignments/{rows[theirs.pk].pk}/cancel/"), {}, format="json"
    )
    assert blocked.status_code == 404
    refused = client.post(
        url(company, f"courses/{course.pk}/assign/"), {"member_ids": [theirs.pk]}, format="json"
    )
    assert refused.status_code == 404
    assert client.get(url(company, f"overview/?branch={south.pk}")).status_code == 404


def test_exempt_cancel_and_a_new_deadline(company, boss, api, member):
    course = CourseFactory(company=company)
    CourseStepFactory(course=course)
    a, b, c = (member(company) for _ in range(3))
    rows = courses.assign(course, [a, b, c], by=boss)
    excused = api.post(
        url(company, f"assignments/{rows[0].pk}/exempt/"), {"reason": "Ta’tilda"}, format="json"
    )
    assert excused.json()["state"] == "exempt" and excused.json()["exempt_reason"] == "Ta’tilda"
    assert api.post(url(company, f"assignments/{rows[1].pk}/cancel/")).json()["state"] == (
        "cancelled"
    )
    moved = api.post(
        url(company, f"assignments/{rows[2].pk}/due/"), {"due_on": "2026-12-24"}, format="json"
    )
    due = datetime.fromisoformat(moved.json()["due_at"])
    assert due == courses.end_of_day(company, date(2026, 12, 24))  # 23:59:59 in Tashkent
    assert (
        api.post(
            url(company, f"assignments/{rows[2].pk}/due/"), {"due_on": None}, format="json"
        ).json()["due_at"]
        is None
    )


def test_a_lesson_editor_and_who_watched(company, boss, api, member):
    made = api.post(
        url(company, "lessons/"),
        {"title": "Muzlatgich", "source": "youtube", "youtube": "https://youtu.be/dQw4w9WgXcQ"},
        format="json",
    )
    assert made.status_code == 201, made.content
    lesson_id = made.json()["id"]
    assert made.json()["youtube_id"] == "dQw4w9WgXcQ"
    assert api.post(url(company, f"lessons/{lesson_id}/publish/")).json()["status"] == "published"
    bad = api.patch(
        url(company, f"lessons/{lesson_id}/"), {"youtube": "https://vimeo.com/1"}, format="json"
    )
    assert bad.status_code == 400
    watcher, idle = member(company), member(company)
    LessonProgress.objects.create(
        company=company,
        lesson_id=lesson_id,
        membership=watcher,
        ranges=[[0, 40]],
        watched_seconds=40,
        percent=40,
        spent_seconds=45,
        sessions=1,
        first_at=timezone.now(),
        last_at=timezone.now(),
    )
    viewers = api.get(url(company, f"lessons/{lesson_id}/viewers/")).json()
    states = {row["member"]["id"]: row["state"] for row in viewers["results"]}
    assert states[watcher.pk] == "watching" and states[idle.pk] == "never"
    assert viewers["counts"]["watching"] == 1
    listed = api.get(url(company, "lessons/")).json()
    assert listed[0]["viewers"] == {"watched": 0, "watching": 1}
    assert api.delete(url(company, f"lessons/{lesson_id}/")).status_code == 204


def test_the_upload_protocol(company, boss, api):
    started = api.post(url(company, "videos/"), {"name": "dars.mp4", "size": 20}, format="json")
    assert started.status_code == 201, started.content
    video = started.json()
    assert (video["state"], video["received_bytes"], video["chunk_bytes"]) == (
        "uploading",
        0,
        8 * 1024 * 1024,
    )
    chunk = url(company, f"videos/{video['id']}/chunk/")
    first = api.put(f"{chunk}?offset=0", b"0123456789", content_type="application/octet-stream")
    assert first.status_code == 200, first.content
    assert first.json()["received_bytes"] == 10
    gap = api.put(f"{chunk}?offset=15", b"xxxxx", content_type="application/octet-stream")
    assert gap.status_code == 409 and gap.json()["received_bytes"] == 10
    api.put(f"{chunk}?offset=10", b"abcdefghij", content_type="application/octet-stream")
    done = api.post(url(company, f"videos/{video['id']}/finish/"))
    assert done.status_code == 200 and done.json()["state"] in ("processing", "failed")
    big = api.post(url(company, "videos/"), {"size": 2 * 1024**3 + 1}, format="json")
    assert big.status_code == 400


def test_settings_overview_and_the_person_page(company, boss, api, member):
    settings = api.get(url(company, "settings/")).json()
    assert settings["completion_percent"] == 90 and settings["storage_used_bytes"] == 0
    changed = api.patch(
        url(company, "settings/"),
        {"completion_percent": 80, "certificate_prefix": "drx"},
        format="json",
    )
    assert (
        changed.json()["completion_percent"] == 80 and changed.json()["certificate_prefix"] == "DRX"
    )
    assert AuditLog.objects.filter(action="learning.settings_changed").exists()
    course = CourseFactory(company=company, mandatory=True, title="Yangi xodim kursi")
    CourseStepFactory(course=course)
    person = member(company)
    AssignmentFactory(course=course, membership=person, due_at=timezone.now() - timedelta(days=5))
    overview = api.get(url(company, "overview/")).json()
    assert overview["compliance"]["people"] == 1 and overview["compliance"]["overdue_people"] == 1
    assert overview["late"][0]["member"]["id"] == person.pk
    assert len(overview["activity"]) == 14
    page = api.get(url(company, f"people/{person.pk}/")).json()
    assert page["summary"]["late"] == 1 and page["assignments"][0]["course"]["title"] == (
        "Yangi xodim kursi"
    )
    grid = api.get(url(company, "people/?late=1")).json()
    assert grid["courses"][0]["title"] == "Yangi xodim kursi"
    assert [row["member"]["id"] for row in grid["rows"]] == [person.pk]


def test_step_targets_are_of_this_company_and_not_archived(company, other_company, boss, api):
    LessonFactory(company=company, title="Kassa")
    LessonFactory(company=company, title="Eski", status=Status.ARCHIVED)
    LessonFactory(company=other_company, title="Boshqa")
    found = api.get(url(company, "step-targets/?kind=lesson")).json()
    assert [row["title"] for row in found] == ["Kassa"]
    assert api.get(url(company, "step-targets/?kind=video")).status_code == 400
    course = CourseFactory(company=company)
    other = LessonFactory(company=other_company)
    refused = api.post(
        url(company, f"courses/{course.pk}/steps/"),
        {"kind": "lesson", "target_id": other.pk},
        format="json",
    )
    assert refused.status_code == 400
    assert Course.objects.get(pk=course.pk).steps.count() == 0
    assert not Video.objects.exists()
