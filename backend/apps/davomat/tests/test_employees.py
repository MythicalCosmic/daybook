"""Employees (docs/DAVOMAT.md §1.4), the people who scan at the terminals: `employees/`."""

import io
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import load_workbook
from PIL import Image

from apps.attendance.models import AttendanceRecord
from apps.attendance.tests.factories import shift_at, weekly_schedule
from apps.audit.models import AuditLog
from apps.davomat import queries
from apps.davomat.audit_actions import DavomatAction
from apps.davomat.models import Employee
from apps.faceid.models import FaceLink
from apps.hr.models import EmployeeProfile
from apps.members.models import Department, Membership, Position
from apps.timeoff.models import TimeOff

pytestmark = pytest.mark.django_db

TZ = ZoneInfo("Asia/Tashkent")
TUESDAY = date(2026, 11, 10)


def at(hour, minute=0, day=TUESDAY) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=TZ)


@pytest.fixture
def frozen(monkeypatch):
    """Tuesday 10 November 2026, 10:00 in Tashkent."""
    moment = at(10)
    monkeypatch.setattr("django.utils.timezone.now", lambda: moment)
    return moment


def jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (900, 1200), (180, 150, 120)).save(out, "JPEG")
    return out.getvalue()


# Adding and changing -------------------------------------------------------------------------


def test_add_an_employee(org, owner_api):
    position = Position.objects.create(company=org.company, name="Sotuvchi")
    department = Department.objects.create(company=org.company, name="Savdo")

    response = owner_api(org.owner).post(
        org.url("employees/"),
        {
            "first_name": "Aziza",
            "last_name": "Rahimova",
            "phone": "90 123 45 67",
            "position_id": position.pk,
            "department_id": department.pk,
            "branch_ids": [org.second.pk],
            "hire_date": "2026-10-01",
            "face_numbers": ["00000002"],
        },
        format="json",
    )

    assert response.status_code == 201, response.content
    data = response.json()
    assert data["full_name"] == "Aziza Rahimova"
    assert data["phone"] == "+998901234567"
    assert data["position"] == {"id": position.pk, "name": "Sotuvchi"}
    assert data["department"] == {"id": department.pk, "name": "Savdo"}
    assert data["branch_ids"] == [org.second.pk]
    assert data["face_numbers"] == ["00000002"]
    assert data["status"] == "active" and data["hire_date"] == "2026-10-01"
    assert data["left_on"] is None and data["schedule"] is None
    assert data["telegram_linked"] is False and data["is_user"] is False
    assert data["source"] == "manual"
    assert data["today"]["state"] in ("not_in", "off")
    person = Membership.objects.select_related("user", "role").get(pk=data["id"])
    assert person.status == Membership.Status.APPROVED
    assert queries.role_kind(person.role) == "employee"
    assert not person.user.has_usable_password()  # employees never sign in
    assert person.home_branch == org.second
    assert FaceLink.objects.get(number_key="2").membership == person
    assert EmployeeProfile.objects.get(membership=person).hire_date == date(2026, 10, 1)
    assert AuditLog.objects.filter(action=DavomatAction.EMPLOYEE_CREATED).exists()


def test_a_first_name_is_all_it_takes(org, owner_api):
    response = owner_api(org.owner).post(org.url("employees/"), {"first_name": "Jasur"})

    assert response.status_code == 201
    data = response.json()
    assert data["branch_ids"] == [org.main.pk]  # the first branch, for someone who sees all
    assert data["hire_date"] == data["hire_date"]  # today, from the profile
    assert data["hire_date"] is not None


def test_a_number_someone_has_is_refused(org, owner_api):
    org.employee("Aziza", face_numbers=["7"])

    response = owner_api(org.owner).post(
        org.url("employees/"), {"first_name": "Bobur", "face_numbers": ["0007"]}, format="json"
    )

    assert response.status_code == 400
    assert not Membership.objects.filter(first_name="Bobur").exists()


def test_the_hire_date_is_never_in_the_future(org, owner_api):
    response = owner_api(org.owner).post(
        org.url("employees/"), {"first_name": "Bobur", "hire_date": "2099-01-01"}, format="json"
    )

    assert response.status_code == 400 and "hire_date" in response.json()


def test_change_an_employee(org, owner_api):
    person = org.employee("Aziza", face_numbers=["2", "3"])
    schedule = weekly_schedule(org.company, name="Kunduzgi")

    response = owner_api(org.owner).patch(
        org.url(f"employees/{person.pk}/"),
        {
            "first_name": "Aziza",
            "last_name": "Karimova",
            "phone": "+998 93 555 11 22",
            "branch_ids": [org.main.pk, org.second.pk],
            "hire_date": "2025-03-01",
            "schedule_id": schedule.pk,
            "face_numbers": ["3", "00000009"],
        },
        format="json",
    )

    assert response.status_code == 200, response.content
    data = response.json()
    assert data["last_name"] == "Karimova" and data["phone"] == "+998935551122"
    assert data["branch_ids"] == sorted([org.main.pk, org.second.pk])
    assert data["hire_date"] == "2025-03-01"
    assert data["schedule"] == {"id": schedule.pk, "name": "Kunduzgi"}
    assert data["face_numbers"] == ["00000009", "3"]
    person.refresh_from_db()
    assert person.user.last_name == "Karimova"
    assert not FaceLink.objects.filter(number_key="2").exists()


def test_a_photo_is_re_encoded_and_shown(org, owner_api):
    person = org.employee("Aziza")
    api = owner_api(org.owner)

    upload = SimpleUploadedFile("me.png", jpeg(), content_type="image/png")
    response = api.post(org.url(f"employees/{person.pk}/photo/"), {"photo": upload})

    assert response.status_code == 200, response.content
    url = response.json()["photo_url"]
    assert url.endswith(".jpg") and "avatars/" in url and "me.png" not in url
    person.user.refresh_from_db()
    assert max(Image.open(person.user.photo).size) == 640
    removed = api.delete(org.url(f"employees/{person.pk}/photo/"))
    assert removed.json()["photo_url"] is None


def test_a_photo_must_be_a_picture(org, owner_api):
    person = org.employee("Aziza")
    upload = SimpleUploadedFile("x.jpg", b"<svg onload=alert(1)>", content_type="image/jpeg")

    response = owner_api(org.owner).post(
        org.url(f"employees/{person.pk}/photo/"), {"photo": upload}
    )

    assert response.status_code == 400


def test_leave_and_come_back(org, owner_api, frozen):
    person = org.employee("Aziza", hire_date=date(2025, 1, 15))
    api = owner_api(org.owner)

    left = api.post(org.url(f"employees/{person.pk}/leave/"), {"left_on": "2026-11-05"})

    assert left.status_code == 200, left.content
    assert left.json()["status"] == "left" and left.json()["left_on"] == "2026-11-05"
    assert left.json()["today"] is None
    person.refresh_from_db()
    assert person.status == Membership.Status.LEFT
    back = api.post(org.url(f"employees/{person.pk}/return/"), {})
    assert back.status_code == 200, back.content
    assert back.json()["status"] == "active" and back.json()["left_on"] is None
    assert back.json()["hire_date"] == "2026-11-10"
    assert AuditLog.objects.filter(action=DavomatAction.EMPLOYEE_RETURNED).exists()


def test_only_someone_who_left_comes_back(org, owner_api):
    person = org.employee("Aziza")

    response = owner_api(org.owner).post(org.url(f"employees/{person.pk}/return/"), {})

    assert response.status_code == 400


def test_leaving_in_the_future_is_refused(org, owner_api):
    person = org.employee("Aziza")

    response = owner_api(org.owner).post(
        org.url(f"employees/{person.pk}/leave/"), {"left_on": "2099-01-01"}
    )

    assert response.status_code == 400


def test_face_numbers_one_by_one(org, owner_api):
    person = org.employee("Aziza")
    api = owner_api(org.owner)

    added = api.post(org.url(f"employees/{person.pk}/face-numbers/"), {"number": "00000012"})
    removed = api.delete(org.url(f"employees/{person.pk}/face-numbers/12/"))
    missing = api.delete(org.url(f"employees/{person.pk}/face-numbers/99/"))

    assert added.json()["face_numbers"] == ["00000012"]
    assert removed.json()["face_numbers"] == []
    assert missing.status_code == 400


# The list ---------------------------------------------------------------------------------------


def test_the_list_and_its_filters(org, owner_api):
    position = Position.objects.create(company=org.company, name="Haydovchi")
    aziza = org.employee("Aziza", "Karimova", face_numbers=["00000002"], phone="901112233")
    bobur = org.employee("Bobur", "Toshev", branches=[org.second], position=position)
    gone = org.employee("Dilshod", "Umarov")
    gone.status = Membership.Status.LEFT
    gone.save()
    bobur.user.telegram_id = 555
    bobur.user.save()
    api = owner_api(org.owner)

    def names(**params):
        rows = api.get(org.url("employees/"), params).json()["results"]
        return [row["first_name"] for row in rows]

    assert names() == ["Aziza", "Bobur", "Dilshod"]
    assert names(search="kari") == ["Aziza"]
    assert names(search="2") == ["Aziza"]  # the face number "00000002"
    assert names(search="1112233") == ["Aziza"]  # a phone
    assert names(branch=org.second.pk) == ["Bobur"]
    assert names(position=position.pk) == ["Bobur"]
    assert names(status="active") == ["Aziza", "Bobur"]
    assert names(status="left") == ["Dilshod"]
    assert names(linked="true") == ["Bobur"]
    assert names(face="true") == ["Aziza"]
    assert names(face="false") == ["Bobur", "Dilshod"]
    assert api.get(org.url("employees/"), {"branch": "x"}).status_code == 400
    assert aziza.pk  # (kept for readability)


def test_users_are_not_employees_unless_they_scan(org, owner_api):
    org.user("manager", "bekzod")

    rows = owner_api(org.owner).get(org.url("employees/")).json()["results"]

    assert rows == []


def test_today_says_who_is_in(org, owner_api, frozen):
    inside = org.employee("Aziza")
    went = org.employee("Bobur")
    away = org.employee("Gulnora")
    rostered = org.employee("Dilshod")
    absent = org.employee("Eldor")
    for person, check_in, check_out in ((inside, at(8, 52), None), (went, at(7), at(9, 30))):
        AttendanceRecord.objects.create(
            company=org.company,
            membership=person,
            date=TUESDAY,
            check_in_at=check_in,
            check_out_at=check_out,
            status=AttendanceRecord.Status.CLOSED if check_out else AttendanceRecord.Status.OPEN,
            branch=org.main,
        )
    TimeOff.objects.create(
        company=org.company,
        membership=away,
        first_day=TUESDAY,
        last_day=TUESDAY + timedelta(days=2),
        status=TimeOff.Status.APPROVED,
    )
    schedule = weekly_schedule(org.company, days=[0])  # Mondays only
    from apps.attendance.models import MemberSchedule

    MemberSchedule.objects.create(
        company=org.company, membership=rostered, schedule=schedule, effective_from=TUESDAY
    )
    shift_at(absent, TUESDAY, time(8, 0), time(17, 0))

    rows = owner_api(org.owner).get(org.url("employees/")).json()["results"]
    today = {row["first_name"]: row["today"] for row in rows}

    assert today["Aziza"] == {"state": "in", "since": "2026-11-10T03:52:00Z"}
    assert today["Bobur"] == {"state": "out", "since": "2026-11-10T04:30:00Z"}
    assert today["Gulnora"] == {"state": "leave", "since": None}
    assert today["Dilshod"] == {"state": "off", "since": None}  # a day off on their roster
    assert today["Eldor"] == {"state": "not_in", "since": None}  # a shift and no check-in


def test_without_a_roster_the_companys_workdays_decide(org, frozen):
    person = org.employee("Aziza")

    assert queries.today_states(org.company, [person])[person.pk]["state"] == "not_in"
    org.company.workdays = [0]  # Mondays only: Tuesday is a day off
    org.company.save()
    assert queries.today_states(org.company, [person])[person.pk]["state"] == "off"


# Rights and scope ------------------------------------------------------------------------------


def test_a_manager_sees_and_adds_only_their_branches(org, owner_api):
    manager = org.user("manager", "bekzod", branches=[org.second])
    ours = org.employee("Aziza", branches=[org.second])
    theirs = org.employee("Bobur", branches=[org.main])
    api = owner_api(manager)

    rows = api.get(org.url("employees/")).json()["results"]

    assert [row["id"] for row in rows] == [ours.pk]
    assert api.get(org.url(f"employees/{theirs.pk}/")).status_code == 404
    assert api.patch(org.url(f"employees/{theirs.pk}/"), {"first_name": "X"}).status_code == 404
    elsewhere = api.post(
        org.url("employees/"), {"first_name": "Nodir", "branch_ids": [org.main.pk]}, format="json"
    )
    assert elsewhere.status_code == 403
    nowhere = api.post(org.url("employees/"), {"first_name": "Nodir"}, format="json")
    assert nowhere.status_code == 400 and "branch_ids" in nowhere.json()
    here = api.post(
        org.url("employees/"), {"first_name": "Nodir", "branch_ids": [org.second.pk]}, format="json"
    )
    assert here.status_code == 201


def test_a_viewer_reads_but_never_writes(org, owner_api):
    viewer = org.user("viewer", "madina", branches=[org.main])
    person = org.employee("Aziza")
    api = owner_api(viewer)

    assert api.get(org.url("employees/")).status_code == 200
    assert api.get(org.url(f"employees/{person.pk}/")).status_code == 200
    assert api.post(org.url("employees/"), {"first_name": "X"}).status_code == 403
    assert api.patch(org.url(f"employees/{person.pk}/"), {"first_name": "X"}).status_code == 403
    assert api.post(org.url(f"employees/{person.pk}/leave/"), {}).status_code == 403
    assert api.post(org.url(f"employees/{person.pk}/telegram-link/")).status_code == 403


def test_another_companys_people_are_missing(org, owner_api, other_company, member):
    stranger = member(other_company, "Employee")
    api = owner_api(org.owner)

    assert api.get(org.url(f"employees/{stranger.pk}/")).status_code == 404
    assert api.post(org.url(f"employees/{stranger.pk}/leave/"), {}).status_code == 404
    assert api.get(f"/api/v1/owner/companies/{other_company.pk}/employees/").status_code == 404


def test_someone_elses_branch_or_position_is_refused(org, owner_api, other_company):
    foreign = other_company.branches.first()
    position = Position.objects.create(company=other_company, name="Begona")
    api = owner_api(org.owner)

    branch = api.post(
        org.url("employees/"), {"first_name": "X", "branch_ids": [foreign.pk]}, format="json"
    )
    title = api.post(
        org.url("employees/"), {"first_name": "X", "position_id": position.pk}, format="json"
    )

    assert branch.status_code == 400 and title.status_code == 400


def test_daybook_has_no_employees_page(org, owner_api, settings):
    settings.EDITION = "daybook"

    assert owner_api(org.owner).get(org.url("employees/")).status_code == 404


# Import and export ---------------------------------------------------------------------------


def csv_file(text: str, name="people.csv") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, text.encode("utf-8-sig"), content_type="text/csv")


def test_import_a_list_after_a_dry_run(org, owner_api):
    Position.objects.create(company=org.company, name="Sotuvchi")
    org.employee("Terminal", face_numbers=["00000005"])  # made by a terminal, named by it
    text = (
        "Ism;Familiya;Telefon;Lavozim;Bo‘lim;Filial;Face ID raqami\n"
        "Aziza;Karimova;901234567;Sotuvchi;Savdo;Chilonzor;00000002\n"
        "Bobur;Toshev;;Haydovchi;;Main;5\n"
        ";Nobody;;;;;\n"
        "Gulnora;Saidova;;;;Yunusobod;\n"
    )
    api = owner_api(org.owner)

    dry = api.post(org.url("employees/import/?dry_run=1"), {"file": csv_file(text)})

    assert dry.status_code == 200, dry.content
    result = dry.json()
    assert result["dry_run"] is True
    assert (result["created"], result["updated"], result["skipped"]) == (1, 1, 2)
    assert [row["action"] for row in result["rows"]] == ["create", "update", "skip", "skip"]
    assert result["mapping"]["Face ID raqami"] == "face_number"
    assert not Membership.objects.filter(first_name="Aziza").exists()

    real = api.post(org.url("employees/import/"), {"file": csv_file(text)}).json()

    assert (real["created"], real["updated"]) == (1, 1)
    aziza = Membership.objects.get(first_name="Aziza")
    assert aziza.position.name == "Sotuvchi" and aziza.department.name == "Savdo"
    assert list(aziza.branches.all()) == [org.second]
    assert aziza.user.phone == "+998901234567"
    assert Employee.objects.get(membership=aziza).source == "import"
    bobur = FaceLink.objects.get(number_key="5").membership
    assert (bobur.first_name, bobur.last_name, bobur.position.name) == (
        "Bobur",
        "Toshev",
        "Haydovchi",
    )
    assert AuditLog.objects.filter(action=DavomatAction.EMPLOYEES_IMPORTED).exists()


def test_import_needs_a_first_name_column(org, owner_api):
    response = owner_api(org.owner).post(
        org.url("employees/import/"), {"file": csv_file("Telefon\n901234567\n")}
    )

    assert response.status_code == 400


def test_import_refuses_what_isnt_a_spreadsheet(org, owner_api):
    upload = SimpleUploadedFile("x.csv", b"\x89PNG\r\n\x1a\n" + b"0" * 64, content_type="text/csv")

    response = owner_api(org.owner).post(org.url("employees/import/"), {"file": upload})

    assert response.status_code == 400


def test_a_manager_imports_only_into_their_branches(org, owner_api):
    manager = org.user("manager", "bekzod", branches=[org.second])
    text = "First name,Branch\nAziza,Chilonzor\nBobur,Main\nGulnora,\n"

    result = owner_api(manager).post(org.url("employees/import/"), {"file": csv_file(text)}).json()

    assert [row["action"] for row in result["rows"]] == ["create", "skip", "skip"]
    assert Membership.objects.filter(first_name="Aziza").exists()
    assert not Membership.objects.filter(first_name__in=["Bobur", "Gulnora"]).exists()


def test_export_reimports_as_is(org, owner_api):
    org.employee("Aziza", "Karimova", face_numbers=["00000002"], phone="901234567")
    org.employee("=HYPERLINK(1)", "Sly")
    api = owner_api(org.owner)

    xlsx = api.get(org.url("employees/export/"), {"format": "xlsx"})
    csv = api.get(org.url("employees/export/"), {"format": "csv", "search": "aziza"})

    assert xlsx.status_code == 200, xlsx.content[:200]
    assert xlsx["Content-Type"].startswith("application/vnd.openxmlformats")
    assert "attachment" in xlsx["Content-Disposition"]
    sheet = load_workbook(io.BytesIO(xlsx.content)).worksheets[0]
    rows = list(sheet.iter_rows(values_only=True))
    assert rows[0][:7] == (
        "First name",
        "Last name",
        "Phone",
        "Position",
        "Department",
        "Branch",
        "Face ID number",
    )
    assert ("Aziza", "Karimova", "+998901234567") in [row[:3] for row in rows]
    sly = next(row for row in sheet.iter_rows() if row[1].value == "Sly")
    assert sly[0].value == "=HYPERLINK(1)" and sly[0].data_type == "s"  # never a formula
    body = csv.content.decode("utf-8-sig")
    assert "Aziza" in body and "HYPERLINK" not in body
    again = api.post(
        org.url("employees/import/?dry_run=1"),
        {"file": SimpleUploadedFile("back.xlsx", xlsx.content)},
    ).json()
    assert again["updated"] == 1 and again["created"] == 1  # the number updates Aziza
