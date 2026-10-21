"""Employee (mini app) endpoints: my day, check-in and out, my month and shifts, corrections,
swaps, open shifts and the managers' board."""

import io
from datetime import time, timedelta

import pytest
from PIL import Image

from apps.attendance import services
from apps.attendance.models import AttendanceRecord, ShiftSwap
from apps.attendance.tests.conftest import CHILONZOR, DAY, local
from apps.attendance.tests.factories import shift_at

pytestmark = pytest.mark.django_db

FRIDAY = DAY + timedelta(days=2)


def url(company, path=""):
    return f"/api/v1/companies/{company.pk}/attendance/{path}"


@pytest.fixture(autouse=True)
def morning(freeze):
    return freeze(local(DAY, 8, 55))


def test_my_day_before_and_after_checking_in(staff, api_as):
    company = staff.ali.company
    shift_at(staff.ali, DAY)
    client = api_as(staff.ali)
    day = client.get(url(company, "today/")).json()
    assert day["state"] == "due"
    assert day["shift"]["start"] == "09:00" and day["branch"]["name"] == "Chilonzor"
    assert day["branch"]["latitude"] == str(CHILONZOR[0])
    assert day["settings"]["require_location"] is True
    checked = client.post(
        url(company, "check-in/"),
        {"lat": "41.2858", "lng": "69.2034", "accuracy": 12},
        format="json",
    )
    assert checked.status_code == 201
    assert checked.json()["outside"] is False and checked.json()["record"]["status"] == "open"
    again = client.post(
        url(company, "check-in/"),
        {"lat": "41.2858", "lng": "69.2034", "accuracy": 12},
        format="json",
    )
    assert again.status_code == 200  # the same record
    assert client.get(url(company, "today/")).json()["state"] == "in"


def test_check_in_with_a_selfie_as_multipart(staff, api_as):
    company = staff.ali.company
    services.update_settings(company, by=None, require_photo=True)
    buffer = io.BytesIO()
    Image.new("RGB", (40, 40), "teal").save(buffer, "JPEG")
    buffer.seek(0)
    buffer.name = "selfie.jpg"
    response = api_as(staff.ali).post(
        url(company, "check-in/"),
        {"lat": "41.2858", "lng": "69.2034", "accuracy": "9", "photo": buffer},
        format="multipart",
    )
    assert response.status_code == 201
    assert response.json()["record"]["has_photo"] is True


def test_check_in_errors_are_readable(staff, api_as):
    company = staff.ali.company
    response = api_as(staff.ali).post(url(company, "check-in/"), {}, format="json")
    assert response.status_code == 400 and "location" in response.json()["detail"]
    response = api_as(staff.ali).post(
        url(company, "check-out/"), {"lat": "41.2", "lng": "69.2"}, format="json"
    )
    assert response.status_code == 400 and "haven't checked in" in response.json()["detail"]


def test_check_out(staff, api_as, freeze):
    company = staff.ali.company
    shift_at(staff.ali, DAY)
    client = api_as(staff.ali)
    client.post(url(company, "check-in/"), {"lat": "41.2858", "lng": "69.2034"}, format="json")
    freeze(local(DAY, 18, 5))
    response = client.post(
        url(company, "check-out/"),
        {"lat": "41.2858", "lng": "69.2034", "accuracy": 10},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["record"]["worked_minutes"] == 9 * 60 + 10 - 60
    assert client.get(url(company, "today/")).json()["state"] == "done"


def test_my_month_and_shifts(staff, api_as):
    company = staff.ali.company
    shift_at(staff.ali, DAY - timedelta(days=1))
    shift_at(staff.ali, FRIDAY)
    shift_at(staff.ali, FRIDAY + timedelta(days=1), published=False)
    client = api_as(staff.ali)
    month = client.get(url(company, "?month=2026-10")).json()
    assert month["cells"][str(DAY - timedelta(days=1))]["code"] == "absent"
    assert month["cells"][str(FRIDAY)]["code"] == "planned"
    shifts = client.get(url(company, "shifts/")).json()
    assert [row["date"] for row in shifts] == [str(FRIDAY)]  # drafts stay hidden


def test_corrections(staff, api_as):
    company = staff.ali.company
    client = api_as(staff.ali)
    yesterday = DAY - timedelta(days=1)
    response = client.post(
        url(company, "corrections/"),
        {
            "date": str(yesterday),
            "check_in_at": f"{yesterday}T09:00",
            "check_out_at": f"{yesterday}T18:00",
            "reason": "Forgot",
        },
        format="json",
    )
    assert response.status_code == 201 and response.json()["status"] == "pending"
    assert response.json()["check_in_at"].startswith(f"{yesterday}T09:00:00+05:00")
    listed = client.get(url(company, "corrections/")).json()
    assert len(listed) == 1
    other = AttendanceRecord.objects.create(
        company=company, membership=staff.vali, date=yesterday, status="absent"
    )
    response = client.post(
        url(company, "corrections/"),
        {
            "date": str(yesterday),
            "record_id": other.pk,
            "check_in_at": f"{yesterday}T09:00",
            "reason": "x",
        },
        format="json",
    )
    assert response.status_code == 404


def test_my_record_only(staff, api_as):
    company = staff.ali.company
    yesterday = DAY - timedelta(days=1)
    mine = AttendanceRecord.objects.create(
        company=company, membership=staff.ali, date=yesterday, status="absent"
    )
    theirs = AttendanceRecord.objects.create(
        company=company, membership=staff.vali, date=yesterday, status="absent"
    )
    client = api_as(staff.ali)
    found = client.get(url(company, f"records/{mine.pk}/"))
    assert found.status_code == 200
    assert found.json()["date"] == str(yesterday) and found.json()["status"] == "absent"
    assert client.get(url(company, f"records/{theirs.pk}/")).status_code == 404


def test_swaps_flow_through_the_app(staff, api_as):
    company = staff.ali.company
    mine = shift_at(staff.ali, FRIDAY)
    ali, vali = api_as(staff.ali), api_as(staff.vali)
    candidates = ali.get(url(company, f"swaps/candidates/?shift_id={mine.pk}")).json()
    assert [row["member"]["name"] for row in candidates] == ["Vali"]
    asked = ali.post(url(company, "swaps/"), {"shift_id": mine.pk, "kind": "cover"}, format="json")
    assert asked.status_code == 201
    swap_id = asked.json()["id"]
    waiting = vali.get(url(company, "swaps/")).json()
    assert [row["id"] for row in waiting["requests"]] == [swap_id]
    assert api_as(staff.bob).post(url(company, f"swaps/{swap_id}/accept/")).status_code == 400
    accepted = vali.post(url(company, f"swaps/{swap_id}/accept/"))
    assert accepted.json()["status"] == ShiftSwap.Status.ACCEPTED
    assert ali.get(url(company, "swaps/")).json()["mine"][0]["status"] == "accepted"
    assert vali.post(url(company, f"swaps/{swap_id}/cancel/")).status_code == 403
    assert ali.post(url(company, f"swaps/{swap_id}/cancel/")).json()["status"] == "cancelled"
    assert ali.post(url(company, f"swaps/{swap_id}/nope/")).status_code == 404


def test_swap_with_another_shift(staff, api_as):
    company = staff.ali.company
    mine = shift_at(staff.ali, FRIDAY)
    theirs = shift_at(staff.vali, FRIDAY + timedelta(days=1), time(14), time(22))
    candidates = api_as(staff.ali).get(url(company, f"swaps/candidates/?shift_id={mine.pk}")).json()
    assert candidates[0]["shifts"][0]["id"] == theirs.pk
    asked = api_as(staff.ali).post(
        url(company, "swaps/"),
        {"shift_id": mine.pk, "kind": "swap", "other_shift_id": theirs.pk},
        format="json",
    )
    assert asked.status_code == 201 and asked.json()["target"]["name"] == "Vali"
    assert (
        api_as(staff.vali)
        .post(url(company, "swaps/"), {"shift_id": mine.pk, "kind": "cover"}, format="json")
        .status_code
        == 400
    )


def test_open_shifts_and_claims(staff, api_as, chilonzor):
    company = staff.ali.company
    open_shift = shift_at(None, FRIDAY, company=company, branch=chilonzor, position=staff.cashier)
    listed = api_as(staff.ali).get(url(company, "open-shifts/")).json()
    assert [row["id"] for row in listed] == [open_shift.pk] and listed[0]["claimed"] is False
    assert api_as(staff.bob).get(url(company, "open-shifts/")).json() == []
    assert api_as(staff.ali).get(url(company, "today/")).json()["open_shifts"] == 1
    claimed = api_as(staff.ali).post(url(company, f"open-shifts/{open_shift.pk}/claim/"))
    assert claimed.status_code == 200 and claimed.json()["kind"] == "claim"
    assert api_as(staff.ali).get(url(company, "open-shifts/")).json()[0]["claimed"] is True
    # Asked for: no longer counted as one to take.
    assert api_as(staff.ali).get(url(company, "today/")).json()["open_shifts"] == 0


def test_board_for_managers_only(staff, api_as):
    company = staff.ali.company
    assert api_as(staff.ali).get(url(company, "board/")).status_code == 403
    assert api_as(staff.lead).get(url(company, "board/")).status_code == 200


def test_another_company_and_module_off(staff, api_as, other_company):
    assert (
        api_as(staff.ali).get(f"/api/v1/companies/{other_company.pk}/attendance/today/").status_code
        == 404
    )
    company = staff.ali.company
    company.features = []
    company.save()
    assert api_as(staff.ali).get(url(company, "today/")).status_code == 403


def test_suspended_people_get_the_suspended_answer(staff, api_as):
    from apps.members.models import Membership

    staff.ali.status = Membership.Status.SUSPENDED
    staff.ali.save()
    response = api_as(staff.ali).get(url(staff.ali.company, "today/"))
    assert response.status_code == 403 and response.json()["code"] == "suspended"
