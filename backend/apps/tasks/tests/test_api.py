import re
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.members.models import Membership
from apps.projects.tests.factories import card, project, team
from apps.tasks.models import Proof, Task, TaskTemplate
from apps.tasks.tests.factories import TaskFactory, jpeg_bytes

pytestmark = pytest.mark.django_db


def client_for(membership: Membership) -> APIClient:
    api = APIClient()
    token = RefreshToken.for_user(membership.user).access_token
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api


def tasks_url(company, *parts) -> str:
    return "/".join([f"/api/v1/companies/{company.pk}/tasks", *map(str, parts), ""])


@pytest.fixture
def worker(company, member):
    return member.registered(company)


@pytest.fixture
def manager(company, member):
    return member.registered(company, "Manager")


def test_member_sees_their_own_tasks_only(company, member, worker):
    mine = TaskFactory(assignee=worker)
    TaskFactory(assignee=member.registered(company))

    response = client_for(worker).get(tasks_url(company))

    assert response.status_code == 200
    assert [task["id"] for task in response.data["results"]] == [mine.pk]


def test_view_all_permission_sees_everything_but_others_personal_tasks(
    company, member, manager, worker
):
    owner = member.registered(company, "Owner")
    given = TaskFactory(assignee=worker, created_by=owner)
    daily = TaskFactory(assignee=member.registered(company), kind=Task.Kind.DAILY)
    TaskFactory(assignee=worker)  # the worker's personal task

    response = client_for(manager).get(tasks_url(company))

    assert {task["id"] for task in response.data["results"]} == {given.pk, daily.pk}


def test_a_manager_never_sees_another_persons_personal_task(company, manager, worker):
    personal = TaskFactory(assignee=worker, title="Dentist at 5")

    listed = client_for(manager).get(tasks_url(company))
    opened = client_for(manager).get(tasks_url(company, personal.pk))

    assert personal.kind == Task.Kind.PERSONAL
    assert listed.data["count"] == 0
    assert opened.status_code == 404


def test_owners_see_personal_tasks_while_the_company_allows_it(company, member, worker):
    owner = member.registered(company, "Owner")
    personal = TaskFactory(assignee=worker)

    assert client_for(owner).get(tasks_url(company, personal.pk)).status_code == 200

    company.owner_sees_personal_tasks = False
    company.save()

    assert client_for(owner).get(tasks_url(company, personal.pk)).status_code == 404
    assert client_for(worker).get(tasks_url(company, personal.pk)).status_code == 200


def test_a_task_on_a_project_board_names_its_card(company, member):
    """The mini app's task screen finds the card's project from the task itself (no board
    lookups); a plain task has no card."""
    people = team(company, member)
    reno = project(company, people["owner"], key="RENO")
    first = card(reno, people["owner"], title="Order tiles", assignee=people["aziz"])
    second = card(reno, people["owner"], title="Paint the wall", assignee=people["aziz"])
    plain = TaskFactory(
        assignee=people["aziz"], created_by=people["owner"], kind=Task.Kind.ASSIGNED
    )
    api = client_for(people["aziz"])

    listed = {row["id"]: row["card"] for row in api.get(tasks_url(company)).data["results"]}
    opened = api.get(tasks_url(company, second.pk)).data

    assert listed[first.pk] == {
        "project_id": reno.pk,
        "project_key": "RENO",
        "number": 1,
        "key": "RENO-1",
    }
    assert listed[plain.pk] is None
    assert opened["card"]["key"] == "RENO-2"


def test_cards_cost_no_extra_queries_in_lists(company, member, django_assert_max_num_queries):
    people = team(company, member)
    reno = project(company, people["owner"], key="RENO")
    card(reno, people["owner"], assignee=people["aziz"])
    api = client_for(people["aziz"])
    api.get(tasks_url(company))  # warm caches (company, membership)
    with CaptureQueriesContext(connection) as one:
        api.get(tasks_url(company))
    for title in ("Hang the sign", "Order shelves", "Fix the door"):
        card(reno, people["owner"], title=title, assignee=people["aziz"])

    with django_assert_max_num_queries(len(one.captured_queries)):
        response = api.get(tasks_url(company))

    assert len(response.data["results"]) == 4
    assert all(row["card"] for row in response.data["results"])


def test_today_scope(company, worker):
    late = TaskFactory(assignee=worker, due_at=timezone.now() - timedelta(hours=1))
    undated = TaskFactory(assignee=worker)
    TaskFactory(assignee=worker, due_at=timezone.now() + timedelta(days=3))
    TaskFactory(assignee=worker, status=Task.Status.DONE)

    response = client_for(worker).get(tasks_url(company), {"scope": "today"})

    ids = [task["id"] for task in response.data["results"]]
    assert ids == [late.pk, undated.pk]  # due first, undated last
    assert response.data["results"][0]["is_overdue"] is True


def test_review_scope_lists_what_waits_for_me(company, manager, worker):
    waiting = TaskFactory(assignee=worker, created_by=manager, status=Task.Status.REVIEW)
    TaskFactory(assignee=worker, created_by=manager)

    response = client_for(manager).get(tasks_url(company), {"scope": "review"})

    assert [task["id"] for task in response.data["results"]] == [waiting.pk]


def test_task_lists_the_actions_allowed_to_me(company, manager, worker):
    task = TaskFactory(assignee=worker, created_by=manager)

    as_worker = client_for(worker).get(tasks_url(company, task.pk)).data
    as_manager = client_for(manager).get(tasks_url(company, task.pk)).data

    assert as_worker["actions"] == ["start", "complete"]
    assert as_manager["actions"] == ["edit", "cancel"]
    assert as_worker["created_by"]["name"] == str(manager)


def test_create_personal_task(company, worker):
    due = timezone.now() + timedelta(hours=3)

    response = client_for(worker).post(
        tasks_url(company),
        {"title": "Order rolls", "due_at": due.isoformat(), "checklist": ["Paper", "Ink"]},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["kind"] == "personal"
    assert [item["text"] for item in response.data["checklist"]] == ["Paper", "Ink"]


def test_manager_assigns_and_employee_cannot(company, member, manager, worker):
    payload = {"title": "Call the supplier", "assignee_id": worker.pk, "proof": Proof.TEXT}

    response = client_for(manager).post(tasks_url(company), payload, format="json")
    assert response.status_code == 201
    assert response.data["assignee"]["id"] == worker.pk

    colleague = member.registered(company)
    response = client_for(colleague).post(tasks_url(company), payload, format="json")
    assert response.status_code == 403


def test_assigning_to_another_companys_member_is_rejected(company, other_company, member, manager):
    outsider = member.registered(other_company)

    response = client_for(manager).post(
        tasks_url(company), {"title": "Hi", "assignee_id": outsider.pk}, format="json"
    )

    assert response.status_code == 400


def test_complete_with_a_photo_and_confirm(company, manager, worker):
    task = TaskFactory(
        assignee=worker, created_by=manager, proof=Proof.PHOTO, needs_confirmation=True
    )
    upload = SimpleUploadedFile(
        "shelf.png", jpeg_bytes(exif_maker="Phone maker"), content_type="image/png"
    )

    response = client_for(worker).post(
        tasks_url(company, task.pk, "complete"), {"proof_photo": upload}, format="multipart"
    )

    assert response.status_code == 200
    assert response.data["status"] == "review"
    task.refresh_from_db()
    assert re.fullmatch(rf"proofs/{company.pk}/[0-9a-f]{{32}}\.jpg", task.proof_photo.name)
    assert b"Phone maker" not in task.proof_photo.read()
    assert response.data["proof_photo"].endswith(task.proof_photo.name)

    response = client_for(manager).post(tasks_url(company, task.pk, "confirm"))
    assert response.data["status"] == "done"


def test_completing_without_the_required_photo_explains_why(company, worker):
    task = TaskFactory(assignee=worker, proof=Proof.PHOTO)

    response = client_for(worker).post(tasks_url(company, task.pk, "complete"), {}, format="json")

    assert response.status_code == 400
    assert "photo" in response.data["detail"]


def test_proof_must_be_an_image(company, worker):
    task = TaskFactory(assignee=worker, proof=Proof.PHOTO)
    upload = SimpleUploadedFile("notes.txt", b"hello", content_type="text/plain")

    response = client_for(worker).post(
        tasks_url(company, task.pk, "complete"), {"proof_photo": upload}, format="multipart"
    )

    assert response.status_code == 400
    assert "proof_photo" in response.data


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("proof.svg", b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>'),
        ("proof.jpg", b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>'),
        ("proof.jpg", b"<!doctype html><script>alert(1)</script>"),
    ],
)
def test_a_crafted_svg_or_html_proof_is_refused(company, worker, name, data):
    task = TaskFactory(assignee=worker, proof=Proof.PHOTO)
    upload = SimpleUploadedFile(name, data, content_type="image/jpeg")

    response = client_for(worker).post(
        tasks_url(company, task.pk, "complete"), {"proof_photo": upload}, format="multipart"
    )

    assert response.status_code == 400
    assert "proof_photo" in response.data
    task.refresh_from_db()
    assert task.status == Task.Status.TODO
    assert not task.proof_photo


def test_send_back_and_comments(company, manager, worker):
    task = TaskFactory(assignee=worker, created_by=manager, status=Task.Status.REVIEW)

    response = client_for(manager).post(
        tasks_url(company, task.pk, "return"), {"reason": "Blurry photo"}, format="json"
    )
    assert response.data["status"] == "returned"

    client_for(worker).post(
        tasks_url(company, task.pk, "comments"), {"text": "Retaking now"}, format="json"
    )
    comments = client_for(manager).get(tasks_url(company, task.pk, "comments")).data
    assert [c["text"] for c in comments] == ["Blurry photo", "Retaking now"]
    assert comments[1]["author"]["id"] == worker.pk


def test_checklist_toggle(company, manager, worker):
    created = client_for(manager).post(
        tasks_url(company),
        {"title": "Open up", "assignee_id": worker.pk, "checklist": ["Lights"]},
        format="json",
    )
    task_id, item_id = created.data["id"], created.data["checklist"][0]["id"]

    response = client_for(worker).post(
        tasks_url(company, task_id, "checklist", item_id), {"is_done": True}, format="json"
    )

    assert response.status_code == 200
    assert response.data["checklist"][0]["is_done"] is True


def test_edit_is_for_the_creator(company, manager, worker):
    task = TaskFactory(assignee=worker, created_by=manager)

    assert (
        client_for(worker).patch(tasks_url(company, task.pk), {"title": "Mine now"}).status_code
        == 403
    )
    response = client_for(manager).patch(
        tasks_url(company, task.pk), {"title": "Clearer title"}, format="json"
    )
    assert response.data["title"] == "Clearer title"


def test_other_companies_tasks_are_invisible(company, other_company, member, worker):
    foreign = TaskFactory(assignee=member.registered(other_company))

    assert client_for(worker).get(tasks_url(company, foreign.pk)).status_code == 404
    assert client_for(worker).get(tasks_url(other_company)).status_code == 404


def test_templates_need_the_templates_permission(company, member, manager, worker):
    url = f"/api/v1/companies/{company.pk}/task-templates/"
    payload = {
        "title": "Opening checklist",
        "due_time": "09:00",
        "weekdays": [4, 0, 0],
        "assignee_ids": [worker.pk],
    }

    assert client_for(worker).post(url, payload, format="json").status_code == 403

    response = client_for(manager).post(url, payload, format="json")
    assert response.status_code == 201
    assert response.data["weekdays"] == [0, 4]
    template = TaskTemplate.objects.get()
    assert template.created_by == manager
    assert list(template.assignees.all()) == [worker]


def test_templates_cannot_name_people_from_another_company(company, other_company, member, manager):
    outsider = member.registered(other_company)

    response = client_for(manager).post(
        f"/api/v1/companies/{company.pk}/task-templates/",
        {"title": "Sneaky", "due_time": "09:00", "assignee_ids": [outsider.pk]},
        format="json",
    )

    assert response.status_code == 400


def test_members_list_for_assigning(company, member, manager, worker):
    member(company)  # not registered yet

    response = client_for(manager).get(f"/api/v1/companies/{company.pk}/members/")

    assert {m["id"] for m in response.data} == {manager.pk, worker.pk}
    assert client_for(worker).get(f"/api/v1/companies/{company.pk}/members/").status_code == 403
