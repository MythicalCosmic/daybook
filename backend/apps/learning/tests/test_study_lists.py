"""Unchangeable lists ("O‘zgarmas ro‘yxat", apps.learning.study_lists): lines are only ever added,
a correction takes one back, used topics and students lock, sealing is final, the digest chain
notices a row changed behind the app's back; the owner endpoints' permissions and scope."""

from datetime import timedelta

import pytest
from django.db import connection

from apps.audit.models import AuditLog
from apps.companies.models import Branch
from apps.console.ranges import company_today
from apps.learning import study_lists
from apps.learning.models import StudyList, StudyMark, UnchangeableError
from apps.learning.tests.helpers_courses import manager, role, turn_on

pytestmark = pytest.mark.django_db

BASE = "/api/v1/owner/companies/{}/learning/lists/"


@pytest.fixture
def boss(company, member):
    turn_on(company)
    return manager(company, member, first_name="Malika", last_name="Usmonova")


@pytest.fixture
def api(owner_api, boss):
    return owner_api(boss)


def url(company, rest=""):
    return BASE.format(company.pk) + rest


def new_list(api, company, **body):
    response = api.post(url(company), {"title": "New staff, November", **body}, format="json")
    assert response.status_code == 201, response.data
    return response.data


def cell(data, topic_number, student_number):
    """The cell's standing "studied" line, as the dashboard reads it."""
    topic = next(t for t in data["topics"] if t["number"] == topic_number)
    student = next(s for s in data["students"] if s["number"] == student_number)
    return next(
        (
            m
            for m in data["marks"]
            if m["topic_id"] == topic["id"]
            and m["student_id"] == student["id"]
            and m["kind"] == "studied"
            and m["corrected_by_id"] is None
        ),
        None,
    )


def test_a_list_from_first_line_to_the_seal(company, boss, api, member):
    aziz = member(company, first_name="Aziz", last_name="Karimov")
    data = new_list(api, company, teacher="Provizor Kamola")
    lid = data["id"]
    assert data["state"] == "open" and data["created_by"] == "Malika Usmonova"
    assert data["intact"] is True and data["marks"] == []

    data = api.post(
        url(company, f"{lid}/topics/"),
        {"titles": ["Storing medicines", "  Cold   chain ", "Prescriptions"]},
        format="json",
    ).data
    assert [(t["number"], t["title"]) for t in data["topics"]] == [
        (1, "Storing medicines"),
        (2, "Cold chain"),
        (3, "Prescriptions"),
    ]
    data = api.post(
        url(company, f"{lid}/students/"),
        {"member_ids": [aziz.pk], "names": [{"name": "Kamola Ergasheva", "note": "intern"}]},
        format="json",
    ).data
    assert [(s["number"], s["name"], s["note"]) for s in data["students"]] == [
        (1, "Aziz Karimov", ""),
        (2, "Kamola Ergasheva", "intern"),
    ]
    assert data["students"][0]["member_id"] == aziz.pk
    assert data["students"][1]["member_id"] is None
    topic, student = data["topics"][0]["id"], data["students"][0]["id"]

    yesterday = company_today(company) - timedelta(days=1)
    response = api.post(
        url(company, f"{lid}/marks/"),
        {"topic_id": topic, "student_id": student, "studied_on": yesterday.isoformat()},
        format="json",
    )
    assert response.status_code == 200, response.data
    first = cell(response.data, 1, 1)
    assert first["number"] == 1 and first["studied_on"] == yesterday
    assert first["written_by"] == "Malika Usmonova" and len(first["digest"]) == 64

    # One standing line per cell: the second is refused until the first is corrected.
    again = api.post(
        url(company, f"{lid}/marks/"), {"topic_id": topic, "student_id": student}, format="json"
    )
    assert again.status_code == 400
    short = api.post(url(company, f"{lid}/marks/{first['id']}/correct/"), {"reason": "x"})
    assert short.status_code == 400
    data = api.post(
        url(company, f"{lid}/marks/{first['id']}/correct/"),
        {"reason": "Was absent that day"},
        format="json",
    ).data
    correction = data["marks"][1]
    assert correction["kind"] == "correction" and correction["corrects_id"] == first["id"]
    assert correction["note"] == "Was absent that day" and correction["number"] == 2
    assert data["marks"][0]["corrected_by_id"] == correction["id"]
    assert cell(data, 1, 1) is None  # the cell is empty again…
    twice = api.post(url(company, f"{lid}/marks/{first['id']}/correct/"), {"reason": "again"})
    assert twice.status_code == 400  # …and a line is taken back once

    data = api.post(
        url(company, f"{lid}/marks/"),
        {"topic_id": topic, "student_id": student, "note": "Retook it"},
        format="json",
    ).data
    assert cell(data, 1, 1)["number"] == 3 and cell(data, 1, 1)["studied_on"] == company_today(
        company
    )
    assert [m["number"] for m in data["marks"]] == [1, 2, 3]
    assert data["intact"] is True
    # Used topics and students lock; unused ones can still change.
    assert data["topics"][0]["locked"] is True and data["topics"][1]["locked"] is False
    assert api.patch(url(company, f"{lid}/topics/{topic}/"), {"title": "Y"}).status_code == 400
    assert api.delete(url(company, f"{lid}/students/{student}/")).status_code == 400
    renamed = api.patch(
        url(company, f"{lid}/topics/{data['topics'][1]['id']}/"), {"title": "Cold chain (2–8 °C)"}
    )
    assert renamed.status_code == 200
    assert renamed.data["topics"][1]["title"] == "Cold chain (2–8 °C)"

    data = api.post(url(company, f"{lid}/seal/")).data
    assert data["state"] == "sealed" and data["sealed_by"] == "Malika Usmonova"
    assert len(data["seal_digest"]) == 64 and data["intact"] is True
    for refused in (
        api.post(url(company, f"{lid}/topics/"), {"titles": ["More"]}, format="json"),
        api.post(url(company, f"{lid}/students/"), {"names": [{"name": "X"}]}, format="json"),
        api.post(
            url(company, f"{lid}/marks/"),
            {"topic_id": data["topics"][2]["id"], "student_id": student},
            format="json",
        ),
        api.post(url(company, f"{lid}/marks/3/correct/"), {"reason": "too late"}),
        api.patch(url(company, f"{lid}/"), {"title": "Other"}, format="json"),
        api.post(url(company, f"{lid}/seal/")),
        api.delete(url(company, f"{lid}/")),
    ):
        assert refused.status_code == 400
    actions = set(AuditLog.objects.filter(company=company).values_list("action", flat=True))
    assert {
        "learning.list_created",
        "learning.list_line_written",
        "learning.list_line_corrected",
        "learning.list_sealed",
    } <= actions


def test_a_line_is_never_changed_or_deleted_even_from_code(company, boss, api):
    data = new_list(api, company)
    lid = data["id"]
    api.post(url(company, f"{lid}/topics/"), {"titles": ["A"]}, format="json")
    data = api.post(
        url(company, f"{lid}/students/"), {"names": [{"name": "B"}]}, format="json"
    ).data
    api.post(
        url(company, f"{lid}/marks/"),
        {"topic_id": data["topics"][0]["id"], "student_id": data["students"][0]["id"]},
        format="json",
    )
    mark = StudyMark.objects.get(study_list_id=lid)
    mark.note = "changed"
    with pytest.raises(UnchangeableError):
        mark.save()
    with pytest.raises(UnchangeableError):
        mark.delete()
    with pytest.raises(UnchangeableError):
        StudyMark.objects.filter(pk=mark.pk).update(note="changed")
    with pytest.raises(UnchangeableError):
        StudyMark.objects.filter(pk=mark.pk).delete()
    assert StudyMark.objects.get(pk=mark.pk).note == ""
    # A list with lines can only be sealed, never deleted.
    assert api.delete(url(company, f"{lid}/")).status_code == 400
    empty = new_list(api, company, title="Empty")
    api.post(url(company, f"{empty['id']}/topics/"), {"titles": ["A"]}, format="json")
    assert api.delete(url(company, f"{empty['id']}/")).status_code == 204
    assert not StudyList.objects.filter(pk=empty["id"]).exists()


def test_a_row_changed_behind_the_apps_back_shows(company, boss, api):
    data = new_list(api, company)
    lid = data["id"]
    api.post(url(company, f"{lid}/topics/"), {"titles": ["A", "B"]}, format="json")
    data = api.post(
        url(company, f"{lid}/students/"), {"names": [{"name": "C"}]}, format="json"
    ).data
    for topic in data["topics"]:
        data = api.post(
            url(company, f"{lid}/marks/"),
            {"topic_id": topic["id"], "student_id": data["students"][0]["id"]},
            format="json",
        ).data
    sealed = api.post(url(company, f"{lid}/seal/")).data
    assert sealed["intact"] is True
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE learning_studymark SET studied_on = studied_on - 1 WHERE id = %s",
            [data["marks"][0]["id"]],
        )
    assert api.get(url(company, f"{lid}/")).data["intact"] is False


def test_the_day_cant_be_in_the_future_and_cells_belong_to_the_list(company, boss, api):
    data = new_list(api, company)
    other = new_list(api, company, title="Other")
    lid = data["id"]
    api.post(url(company, f"{lid}/topics/"), {"titles": ["A"]}, format="json")
    data = api.post(
        url(company, f"{lid}/students/"), {"names": [{"name": "B"}]}, format="json"
    ).data
    tomorrow = company_today(company) + timedelta(days=1)
    body = {"topic_id": data["topics"][0]["id"], "student_id": data["students"][0]["id"]}
    future = api.post(
        url(company, f"{lid}/marks/"), {**body, "studied_on": tomorrow.isoformat()}, format="json"
    )
    assert future.status_code == 400
    elsewhere = api.post(url(company, f"{other['id']}/marks/"), body, format="json")
    assert elsewhere.status_code == 400


def test_candidates_are_staff_in_scope_not_on_the_list_yet(company, boss, api, member):
    aziz = member(company, first_name="Aziz", last_name="Karimov")
    member(company, first_name="Dilnoza", last_name="Rahimova")
    data = new_list(api, company)
    lid = data["id"]
    names = {row["name"] for row in api.get(url(company, f"{lid}/candidates/")).data}
    assert {"Aziz Karimov", "Dilnoza Rahimova"} <= names
    api.post(url(company, f"{lid}/students/"), {"member_ids": [aziz.pk]}, format="json")
    names = {row["name"] for row in api.get(url(company, f"{lid}/candidates/?q=a")).data}
    assert "Aziz Karimov" not in names and "Dilnoza Rahimova" in names
    # The same person twice stays one student.
    data = api.post(url(company, f"{lid}/students/"), {"member_ids": [aziz.pk]}, format="json").data
    assert len(data["students"]) == 1


def test_permissions_module_switch_company_and_branch_scope(
    company, other_company, boss, api, member, owner_api
):
    data = new_list(api, company)
    lid = data["id"]
    reader = owner_api(
        member(company, role(company, "Training viewer", "learning.view", branches_all=True).name)
    )
    assert reader.get(url(company)).status_code == 200
    assert reader.get(url(company, f"{lid}/")).status_code == 200
    assert reader.post(url(company), {"title": "X"}, format="json").status_code == 403
    assert reader.post(url(company, f"{lid}/seal/")).status_code == 403
    nobody = owner_api(member(company, role(company, "Dashboard only").name))
    assert nobody.get(url(company)).status_code == 403

    turn_on(other_company)
    theirs = owner_api(manager(other_company, member))
    assert theirs.get(url(other_company, f"{lid}/")).status_code == 404

    north = Branch.objects.create(company=company, name="North")
    south = Branch.objects.create(company=company, name="South")
    north_list = new_list(api, company, title="North list", branch_id=north.pk)
    local = owner_api(manager(company, member, branches=[south]))
    seen = {row["id"] for row in local.get(url(company)).data}
    assert lid in seen and north_list["id"] not in seen  # whole-company lists are everyone's
    assert local.get(url(company, f"{north_list['id']}/")).status_code == 404
    refused = local.post(url(company), {"title": "X", "branch_id": north.pk}, format="json")
    assert refused.status_code == 400

    company.features = [f for f in company.features if f != "learning"]
    company.save(update_fields=["features"])
    assert api.get(url(company)).status_code == 404


def test_the_index_counts_standing_lines(company, boss, api):
    data = new_list(api, company)
    lid = data["id"]
    api.post(url(company, f"{lid}/topics/"), {"titles": ["A", "B"]}, format="json")
    data = api.post(
        url(company, f"{lid}/students/"), {"names": [{"name": "C"}, {"name": "D"}]}, format="json"
    ).data
    data = api.post(
        url(company, f"{lid}/marks/"),
        {"topic_id": data["topics"][0]["id"], "student_id": data["students"][0]["id"]},
        format="json",
    ).data
    api.post(
        url(company, f"{lid}/marks/{data['marks'][0]['id']}/correct/"), {"reason": "wrong one"}
    )
    data = api.post(
        url(company, f"{lid}/marks/"),
        {"topic_id": data["topics"][1]["id"], "student_id": data["students"][1]["id"]},
        format="json",
    ).data
    row = next(r for r in api.get(url(company)).data if r["id"] == lid)
    assert (row["topics"], row["students"], row["cells"], row["studied"]) == (2, 2, 4, 1)
    assert [r["id"] for r in api.get(url(company, "?state=sealed")).data] == []
    assert [r["id"] for r in api.get(url(company, "?q=november")).data] == [lid]
    assert study_lists.standing(StudyList.objects.get(pk=lid), 0, 0) is None
