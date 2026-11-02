"""The HR overview: headcount and its trend, what expires, birthdays and anniversaries of the
coming week, the settings, inside the branch scope."""

from datetime import date, timedelta

import pytest

from apps.hr import overview, services
from apps.hr.models import EmployeeProfile, RequiredDocument
from apps.hr.tests.conftest import DAY
from apps.hr.tests.factories import EmployeeDocumentFactory

pytestmark = pytest.mark.django_db


def path(company, tail="overview") -> str:
    return f"/api/v1/owner/companies/{company.pk}/hr/{tail}/"


def hire(member, day: date, **fields) -> EmployeeProfile:
    profile = services.ensure_profile(member)
    profile.hire_date = day
    for name, value in fields.items():
        setattr(profile, name, value)
    profile.save()
    return profile


def test_the_overview_counts_people_documents_and_celebrations(shop, staff, owner_api):
    for person in (staff.owner, staff.manager, staff.accountant, staff.lead, staff.vali):
        hire(person, date(2024, 1, 15))
    hire(staff.ali, date(2023, 10, 24), birth_date=date(1998, 10, 25))  # 3 years on Saturday
    hire(staff.sara, DAY - timedelta(days=5), birth_date=date(2000, 10, 21), show_birthday=False)
    EmployeeDocumentFactory(
        membership=staff.ali, kind="medical_book", expires_on=DAY + timedelta(3)
    )
    EmployeeDocumentFactory(
        membership=staff.vali, kind="medical_book", expires_on=DAY - timedelta(1)
    )
    EmployeeDocumentFactory(
        membership=staff.sara, kind="medical_book", expires_on=DAY + timedelta(200)
    )
    RequiredDocument.objects.create(company=shop, kind="medical_book")

    body = owner_api(staff.manager).get(path(shop)).json()

    assert body["as_of"] == "2026-10-21"
    assert body["headcount"] == {
        "current": 7,
        "active": 7,
        "suspended": 0,
        "joined_30d": 1,
        "left_30d": 0,
    }
    assert len(body["trend"]) == 12 and body["trend"][-1]["month"] == "2026-10"
    assert body["trend"][-1]["headcount"] == 7 and body["trend"][-1]["hired"] == 1
    assert body["trend"][0]["month"] == "2025-11"
    # Ali's book expires on Saturday, Vali's expired yesterday, Sara's isn't checked yet.
    assert body["documents"] == {"expired": 1, "expiring": 1, "missing": 4, "unverified": 1}
    assert [row["member"]["name"] for row in body["expiring_documents"]] == [
        "Vali Aliyev",
        "Ali Valiyev",
    ]
    assert body["expiring_documents"][0]["days_left"] == -1
    # Sara hides her birthday; Ali's is on Sunday.
    assert [(row["member"]["name"], row["days_until"]) for row in body["birthdays"]] == [
        ("Ali Valiyev", 4)
    ]
    assert [(row["member"]["name"], row["years"]) for row in body["anniversaries"]] == [
        ("Ali Valiyev", 3)
    ]
    assert body["contracts"]["active"] == 0


def test_the_overview_stays_in_the_branch_scope(shop, staff, owner_api):
    EmployeeDocumentFactory(membership=staff.sara, kind="medical_book", expires_on=DAY)

    lead = owner_api(staff.lead).get(path(shop)).json()

    assert lead["documents"]["expiring"] == 0
    assert lead["headcount"]["current"] == 6  # everyone but Sara of Yunusobod


def test_a_29_february_birthday_falls_on_the_28th(shop):
    assert overview.next_date(date(2000, 2, 29), date(2027, 2, 1)) == date(2027, 2, 28)
    assert overview.next_date(date(2000, 2, 29), date(2028, 2, 1)) == date(2028, 2, 29)
    assert overview.next_date(date(1990, 1, 3), date(2026, 12, 30)) == date(2027, 1, 3)


def test_settings_read_with_hr_view_and_change_with_hr_manage(shop, staff, owner_api):
    assert owner_api(staff.manager).get(path(shop, "settings")).json()["document_warn_days"] == 30
    denied = owner_api(staff.manager).patch(path(shop, "settings"), {"document_warn_days": 14})
    assert denied.status_code == 403

    changed = owner_api(staff.accountant).patch(
        path(shop, "settings"), {"document_warn_days": 14, "celebrate_anniversaries": False}
    )

    assert changed.status_code == 200
    assert changed.json()["document_warn_days"] == 14
    assert changed.json()["celebrate_anniversaries"] is False
    assert (
        owner_api(staff.accountant)
        .patch(path(shop, "settings"), {"document_warn_days": 400})
        .status_code
        == 400
    )
