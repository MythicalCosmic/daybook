"""Owner endpoints: permission 200/403, another company 404, branch isolation, hidden data,
audited writes and the shapes the dashboard reads."""

from datetime import timedelta

import pytest

from apps.attendance import services
from apps.attendance.models import AttendanceRecord, ShiftSwap, WorkSchedule, WorkShift
from apps.attendance.tests.conftest import DAY, local
from apps.attendance.tests.factories import shift_at
from apps.audit.models import AuditLog
from apps.members.models import AccessRole
from apps.members.permissions import Perm

pytestmark = pytest.mark.django_db

YESTERDAY = DAY - timedelta(days=1)
MONDAY = DAY + timedelta(days=5)


def url(company, path):
    return f"/api/v1/owner/companies/{company.pk}/attendance/{path}"


@pytest.fixture(autouse=True)
def morning(freeze, staff):
    freeze(local(DAY, 10, 0))
    services.update_settings(staff.ali.company, by=None, require_location=False)


@pytest.fixture
def reader(staff, member):
    """dashboard.access without any attendance permission."""
    AccessRole.objects.create(
        company=staff.ali.company, name="Reader", permissions=[Perm.DASHBOARD_ACCESS]
    )
    return member.registered(staff.ali.company, "Reader")


@pytest.mark.parametrize(
    "path",
    [
        "board/",
        "records/",
        "timesheet/",
        "summary/",
        "roster/",
        "staff/",
        "schedules/",
        "templates/",
        f"shifts/?from={DAY}&to={DAY}",
    ],
)
def test_view_endpoints_need_attendance_view(staff, owner_api, reader, path):
    company = staff.ali.company
    assert owner_api(staff.accountant).get(url(company, path)).status_code == 200
    assert owner_api(reader).get(url(company, path)).status_code == 403


@pytest.mark.parametrize("path", ["settings/", "swaps/", "corrections/"])
def test_manage_endpoints_need_attendance_manage(staff, owner_api, path):
    company = staff.ali.company
    assert owner_api(staff.manager).get(url(company, path)).status_code == 200
    assert owner_api(staff.accountant).get(url(company, path)).status_code == 403


def test_another_company_is_a_404(staff, owner_api, other_company):
    assert owner_api(staff.manager).get(url(other_company, "board/")).status_code == 404
    record = services.check_in(staff.ali, now=local(DAY, 9)).record
    response = owner_api(staff.manager).get(
        f"/api/v1/owner/companies/{other_company.pk}/attendance/records/{record.pk}/"
    )
    assert response.status_code == 404


def test_module_off_is_a_403_but_settings_stay_open(staff, owner_api):
    company = staff.ali.company
    company.features = []
    company.save()
    assert owner_api(staff.manager).get(url(company, "board/")).status_code == 403
    assert owner_api(staff.manager).get(url(company, "settings/")).status_code == 200


def test_settings_patch_is_audited(staff, owner_api):
    company = staff.ali.company
    response = owner_api(staff.manager).patch(
        url(company, "settings/"), {"grace_minutes": 15}, format="json"
    )
    assert response.status_code == 200 and response.json()["grace_minutes"] == 15
    log = AuditLog.objects.get(action="attendance.settings_changed", actor=staff.manager.user)
    assert log.details["changes"]["grace_minutes"] == [10, 15]
    bad = owner_api(staff.manager).patch(
        url(company, "settings/"), {"auto_close_after_hours": 0}, format="json"
    )
    assert bad.status_code == 400


def test_board_and_branch_isolation(staff, owner_api):
    company = staff.ali.company
    shift_at(staff.ali, DAY)
    shift_at(staff.sara, DAY)
    services.check_in(staff.ali, now=local(DAY, 8, 55))
    sara = services.check_in(staff.sara, now=local(DAY, 9, 5)).record
    everyone = owner_api(staff.manager).get(url(company, "board/")).json()
    names = {row["member"]["name"] for row in everyone["people"]}
    assert {"Ali", "Sara"} <= names
    mine = owner_api(staff.lead).get(url(company, "board/")).json()
    assert "Sara" not in {row["member"]["name"] for row in mine["people"]}
    assert [b["name"] for b in mine["branches"]] == ["Chilonzor"]
    # An id outside the scope answers like a missing one.
    assert owner_api(staff.lead).get(url(company, f"records/{sara.pk}/")).status_code == 404
    # Asking for a branch outside the scope gives nothing from it.
    other = owner_api(staff.lead).get(url(company, f"board/?branch={sara.branch_id}")).json()
    assert other["people"] == [] or all(
        row["branch"]["id"] != sara.branch_id for row in other["people"]
    )


def test_record_list_detail_edit_excuse_overtime(staff, owner_api):
    company = staff.ali.company
    shift_at(staff.ali, YESTERDAY)
    services.check_in(staff.ali, now=local(YESTERDAY, 9, 0))
    services.check_out(staff.ali, now=local(YESTERDAY, 18, 0))
    record = AttendanceRecord.objects.get(membership=staff.ali)
    client = owner_api(staff.manager)
    rows = client.get(url(company, f"records/?from={YESTERDAY}&to={YESTERDAY}")).json()
    assert rows["count"] == 1 and rows["results"][0]["member"]["name"] == "Ali"
    detail = client.get(url(company, f"records/{record.pk}/")).json()
    assert detail["photo_url"] is None and detail["worked_minutes"] == 480
    edited = client.patch(
        url(company, f"records/{record.pk}/"),
        {"check_out_at": f"{YESTERDAY}T19:30", "reason": "Inventory"},
        format="json",
    )
    assert edited.status_code == 200
    assert (
        edited.json()["check_out_at"].startswith(f"{YESTERDAY}T19:30")
        and edited.json()["overtime_status"] == "pending"
    )
    assert client.get(url(company, "records/?overtime=pending")).json()["count"] == 1
    assert (
        owner_api(staff.accountant)
        .patch(url(company, f"records/{record.pk}/"), {"reason": "x"}, format="json")
        .status_code
        == 403
    )
    decided = client.post(
        url(company, f"records/{record.pk}/overtime/"), {"approve": True}, format="json"
    )
    assert decided.json()["overtime_status"] == "approved"
    missing = client.post(
        url(company, f"records/{record.pk}/overtime/"), {"approve": True}, format="json"
    )
    assert missing.status_code == 400


def test_manual_record_and_excuse(staff, owner_api):
    company = staff.ali.company
    shift = shift_at(staff.ali, YESTERDAY)
    client = owner_api(staff.manager)
    response = client.post(
        url(company, "records/"),
        {
            "member_id": staff.ali.pk,
            "date": str(YESTERDAY),
            "check_in_at": f"{YESTERDAY}T09:00",
            "check_out_at": f"{YESTERDAY}T18:00",
            "reason": "Forgot phone",
        },
        format="json",
    )
    assert response.status_code == 201 and response.json()["shift_id"] == shift.pk
    absent_shift = shift_at(staff.vali, YESTERDAY)
    absent = AttendanceRecord.objects.create(
        company=company,
        membership=staff.vali,
        shift=absent_shift,
        date=YESTERDAY,
        status="absent",
        branch=absent_shift.branch,
    )
    excused = client.post(
        url(company, f"records/{absent.pk}/excuse/"), {"reason": "Sick note"}, format="json"
    )
    assert excused.json()["status"] == "excused"
    lead_other = owner_api(staff.lead).post(
        url(company, "records/"),
        {
            "member_id": staff.sara.pk,
            "date": str(YESTERDAY),
            "check_in_at": f"{YESTERDAY}T09:00",
            "check_out_at": f"{YESTERDAY}T18:00",
            "reason": "x",
        },
        format="json",
    )
    assert lead_other.status_code == 404


def test_timesheet_and_summary(staff, owner_api):
    company = staff.ali.company
    shift_at(staff.ali, YESTERDAY)
    services.check_in(staff.ali, now=local(YESTERDAY, 9, 20))
    services.check_out(staff.ali, now=local(YESTERDAY, 18, 0))
    sheet = owner_api(staff.manager).get(url(company, "timesheet/?month=2026-10")).json()
    assert len(sheet["days"]) == 31
    ali = next(row for row in sheet["people"] if row["member"]["name"] == "Ali")
    assert ali["cells"][str(YESTERDAY)]["code"] == "late"
    assert ali["totals"]["late_arrivals"] == 1
    summary = owner_api(staff.manager).get(url(company, "summary/?preset=week&compare=prev")).json()
    assert summary["compare"] is not None and "present" in summary["totals"]
    assert owner_api(staff.manager).get(url(company, "summary/?preset=nope")).status_code == 400
    assert owner_api(staff.manager).get(url(company, "timesheet/?month=13-2026")).status_code == 400


def test_schedules_crud_and_assign(staff, owner_api):
    company = staff.ali.company
    client = owner_api(staff.manager)
    created = client.post(
        url(company, "schedules/"),
        {
            "name": "Kassa 5/2",
            "kind": "weekly",
            "days": [{"weekday": d, "starts_at": "09:00", "ends_at": "18:00"} for d in range(5)],
        },
        format="json",
    )
    assert created.status_code == 201, created.json()
    schedule_id = created.json()["id"]
    assert created.json()["weekly_minutes"] == 5 * 8 * 60
    assigned = client.post(
        url(company, f"schedules/{schedule_id}/assign/"),
        {"member_ids": [staff.ali.pk]},
        format="json",
    )
    assert assigned.json() == {"count": 1}
    listed = client.get(url(company, "schedules/")).json()
    assert listed[0]["member_ids"] == [staff.ali.pk]
    assert WorkShift.objects.filter(membership=staff.ali, date=DAY).exists()
    patched = client.patch(
        url(company, f"schedules/{schedule_id}/"), {"name": "Kassa"}, format="json"
    )
    assert patched.json()["name"] == "Kassa"
    bad = client.post(
        url(company, "schedules/"), {"name": "Empty", "kind": "weekly", "days": []}, format="json"
    )
    assert bad.status_code == 400
    assert client.delete(url(company, f"schedules/{schedule_id}/")).status_code == 204
    assert not WorkSchedule.objects.get(pk=schedule_id).is_active
    assert (
        owner_api(staff.accountant)
        .post(url(company, "schedules/"), {"name": "x", "kind": "flexible"}, format="json")
        .status_code
        == 403
    )


def test_roster_shifts_bulk_and_publish(staff, owner_api, chilonzor):
    from apps.attendance import defaults

    company = staff.ali.company
    defaults.ensure(company)
    client = owner_api(staff.manager)
    created = client.post(
        url(company, "shifts/"),
        {"member_id": staff.ali.pk, "date": str(MONDAY), "start": "09:00", "end": "18:00"},
        format="json",
    )
    assert created.status_code == 201 and created.json()["published"] is False
    shift_id = created.json()["id"]
    open_shift = client.post(
        url(company, "shifts/"),
        {"date": str(MONDAY), "start": "12:00", "end": "21:00", "branch_id": chilonzor.pk},
        format="json",
    ).json()
    assert open_shift["status"] == "open" and open_shift["member_id"] is None
    moved = client.patch(
        url(company, f"shifts/{shift_id}/"),
        {"member_id": staff.vali.pk, "start": "10:00"},
        format="json",
    )
    assert moved.json()["member_id"] == staff.vali.pk and moved.json()["start"] == "10:00"
    roster = client.get(url(company, f"roster/?week={MONDAY}")).json()
    assert roster["unpublished"] == 2 and len(roster["days"]) == 7 and roster["templates"]
    published = client.post(
        url(company, "shifts/publish/"),
        {"start": str(MONDAY), "end": str(MONDAY + timedelta(days=6))},
        format="json",
    )
    assert published.json() == {"count": 2}
    copied = client.post(
        url(company, "shifts/bulk/"),
        {"action": "copy_week", "week": str(MONDAY + timedelta(days=7))},
        format="json",
    )
    assert copied.json() == {"count": 2}
    assert client.delete(url(company, f"shifts/{shift_id}/")).status_code == 204
    overlap = client.post(
        url(company, "shifts/"),
        {"member_id": staff.ali.pk, "date": str(MONDAY), "start": "09:00", "end": "18:00"},
        format="json",
    )
    assert overlap.status_code == 201
    clash = client.post(
        url(company, "shifts/"),
        {"member_id": staff.ali.pk, "date": str(MONDAY), "start": "17:00", "end": "22:00"},
        format="json",
    )
    assert clash.status_code == 400 and "already has a shift" in clash.json()["detail"]
    listed = client.get(url(company, f"shifts/?from={MONDAY}&to={MONDAY}")).json()
    assert {row["status"] for row in listed} == {"planned", "open"}


def test_templates(staff, owner_api):
    company = staff.ali.company
    client = owner_api(staff.manager)
    made = client.post(
        url(company, "templates/"),
        {"name": "Late", "starts_at": "15:00", "ends_at": "23:30", "break_minutes": 30, "color": 2},
        format="json",
    )
    assert made.status_code == 201
    assert client.delete(url(company, f"templates/{made.json()['id']}/")).status_code == 204
    names = [row["name"] for row in client.get(url(company, "templates/")).json()]
    assert "Late" not in names


def test_swaps_and_corrections_queues(staff, owner_api):
    company = staff.ali.company
    shift = shift_at(staff.ali, MONDAY)
    swap = services.request_swap(staff.ali, shift=shift, kind="cover", target=staff.vali)
    services.accept_swap(swap, by=staff.vali)
    client = owner_api(staff.manager)
    rows = client.get(url(company, "swaps/")).json()
    assert rows["count"] == 1 and rows["results"][0]["accepted_by"]["name"] == "Vali"
    rejected = client.post(url(company, f"swaps/{swap.pk}/reject/"), {}, format="json")
    assert rejected.status_code == 400
    approved = client.post(url(company, f"swaps/{swap.pk}/approve/"))
    assert approved.json()["status"] == ShiftSwap.Status.APPROVED

    services.request_correction(
        staff.ali,
        date=YESTERDAY,
        check_in_at=local(YESTERDAY, 9),
        check_out_at=local(YESTERDAY, 18),
        reason="forgot",
    )
    pending = client.get(url(company, "corrections/")).json()
    assert pending["count"] == 1
    correction_id = pending["results"][0]["id"]
    decided = client.post(
        url(company, f"corrections/{correction_id}/decide/"),
        {"approve": False, "reason": "No"},
        format="json",
    )
    assert decided.json()["status"] == "rejected"
    assert owner_api(staff.lead).get(url(company, "swaps/?status=all")).status_code == 200


def test_staff_and_member_month(staff, owner_api):
    company = staff.ali.company
    shift_at(staff.ali, YESTERDAY)
    people = owner_api(staff.lead).get(url(company, "staff/")).json()
    assert "Sara" not in {row["name"] for row in people}
    month = (
        owner_api(staff.manager).get(url(company, f"members/{staff.ali.pk}/?month=2026-10")).json()
    )
    assert month["member"]["name"] == "Ali" and month["cells"][str(YESTERDAY)]["code"] == "absent"
    assert "present" in month["summary"]
    assert owner_api(staff.lead).get(url(company, f"members/{staff.sara.pk}/")).status_code == 404


def test_pulse_and_queue_show_attendance(staff, owner_api):
    company = staff.ali.company
    services.request_correction(
        staff.ali,
        date=YESTERDAY,
        check_in_at=local(YESTERDAY, 9),
        check_out_at=local(YESTERDAY, 18),
        reason="forgot",
    )
    pulse = owner_api(staff.manager).get(f"/api/v1/owner/companies/{company.pk}/pulse/").json()
    assert pulse["counters"]["attendance.corrections"] == 1
    assert "attendance.roster" in pulse["versions"]
    queue = (
        owner_api(staff.manager)
        .get(f"/api/v1/owner/companies/{company.pk}/queue/?kind=attendance.corrections")
        .json()
    )
    item = queue["items"][0]
    response = owner_api(staff.manager).post(
        f"/api/v1/owner/companies/{company.pk}/{item['actions'][0]['endpoint']}",
        item["actions"][0]["body"],
        format="json",
    )
    assert response.status_code == 200
