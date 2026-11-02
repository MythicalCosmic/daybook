"""`hr_overview` as the assistant runs it: counts, names and dates, never an ID, card or
document number or HR's notes; hr.view only; the module on; the branch scope."""

import json
from datetime import date, timedelta

import pytest

from apps.ai.tools.testing import call_tool
from apps.hr import services
from apps.hr.tests.conftest import DAY, local
from apps.hr.tests.factories import EmployeeDocumentFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def filed(shop, staff):
    services.update_profile(
        staff.ali,
        by=staff.owner,
        pinfl="30101900123456",
        passport="AA1234567",
        payout_card="8600123456789012",
        payout_method="card",
        notes="Qarzi bor",
        birth_date=date(1998, 10, 23),
    )
    EmployeeDocumentFactory(
        membership=staff.ali, kind="passport", number="AB7654321", expires_on=DAY + timedelta(9)
    )
    EmployeeDocumentFactory(
        membership=staff.sara,
        kind="medical_book",
        number="TB-998877",
        expires_on=DAY - timedelta(2),
    )
    services.activate_contract(
        services.create_contract(
            staff.vali,
            by=staff.owner,
            kind="fixed_term",
            starts_on=DAY - timedelta(days=200),
            ends_on=DAY + timedelta(days=12),
            probation_until=DAY + timedelta(days=1),
        ),
        by=staff.owner,
    )


def test_the_overview_tool_gives_counts_and_dates_only(shop, staff, filed):
    result = call_tool("hr_overview", staff.owner, days=30, _now=local(DAY, 10))

    rows = [(row["type"], row["name"], row["date"], row["days_left"]) for row in result["rows"]]
    assert rows == [
        ("document", "Sara Tosheva", "2026-10-19", -2),
        ("probation_end", "Vali Aliyev", "2026-10-22", 1),
        ("document", "Ali Valiyev", "2026-10-30", 9),
        ("contract_end", "Vali Aliyev", "2026-11-02", 12),
    ]
    assert result["rows"][0]["what"] == "Medical book"
    data = result["data"]
    assert data["headcount"]["current"] == 7
    assert data["documents"]["expired"] == 1 and data["contracts"]["on_probation"] == 1
    assert data["this_week"]["birthdays"] == [
        {"member_id": staff.ali.pk, "name": "Ali Valiyev", "date": "2026-10-23"}
    ]
    text = json.dumps(result, ensure_ascii=False)
    for secret in (
        "30101900123456",
        "3456",
        "AA1234567",
        "AB7654321",
        "8600",
        "TB-998877",
        "Qarzi",
    ):
        assert secret not in text


def test_it_needs_hr_view_and_the_module(shop, staff, filed):
    assert call_tool("hr_overview", staff.ali) == {"error": "not_allowed"}
    shop.features = ["payroll"]
    shop.save()
    staff.manager.company.refresh_from_db()
    assert call_tool("hr_overview", staff.manager) == {"error": "not_allowed"}


def test_it_stays_in_the_branch_scope(shop, staff, filed):
    result = call_tool("hr_overview", staff.lead, days=30, _now=local(DAY, 10))

    assert "Sara Tosheva" not in json.dumps(result, ensure_ascii=False)
    assert result["data"]["headcount"]["current"] == 6


def test_it_answers_in_the_askers_language(shop, staff, filed):
    result = call_tool("hr_overview", staff.owner, _language="uz", _now=local(DAY, 10))

    assert {row["what"] for row in result["rows"] if row["type"] == "document"} == {
        "Tibbiy daftarcha",
        "Pasport",
    }
