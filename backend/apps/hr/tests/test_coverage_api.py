"""The coverage endpoints (`hr/coverage/`, `hr/coverage/live/`, `hr/coverage/pharmacists/`),
the coverage settings, and the `hr_coverage` AI tool: company scope (404), permissions (403),
the module switch, hidden fields and branch scope."""

import json
from datetime import time, timedelta

import pytest

from apps.ai.tools.testing import call_tool
from apps.attendance.models import AttendanceRecord
from apps.attendance.tests.factories import shift_at
from apps.audit.models import AuditLog
from apps.hr import conf
from apps.hr.models import DocumentKind, EmployeeDocument, RequiredDocument
from apps.hr.tests.conftest import DAY, local
from apps.hr.tests.test_coverage import TOMORROW, YESTERDAY, credentials
from apps.members.models import AccessRole, Position
from apps.members.permissions import Perm

pytestmark = pytest.mark.django_db


def base(company) -> str:
    return f"/api/v1/owner/companies/{company.pk}/hr/"


@pytest.fixture
def rota(shop, staff, chilonzor, yunusobod, member):
    from apps.hr import services

    chilonzor.opens_at, chilonzor.closes_at = time(8), time(22)
    chilonzor.save()
    yunusobod.open_24h = True
    yunusobod.save()
    services.set_pharmacists(shop, by=staff.owner, roles={staff.pharmacist: services.PHARMACIST})
    for person in (staff.ali, staff.vali, staff.sara):
        credentials(person)
    EmployeeDocument.objects.filter(membership=staff.vali, kind="pharmacist_certificate").update(
        number="SRT-445566", expires_on=YESTERDAY
    )
    shift_at(staff.ali, DAY, time(8), time(17), branch=chilonzor)
    shift_at(staff.vali, DAY, time(14), time(22), branch=chilonzor)
    shift_at(staff.sara, DAY, time(8), time(20), branch=yunusobod)
    return staff


@pytest.fixture
def roster_reader(shop, member, chilonzor, yunusobod):
    """Someone who runs the roster without HR's permissions."""
    AccessRole.objects.create(
        company=shop,
        name="Roster",
        permissions=[Perm.DASHBOARD_ACCESS, Perm.ATTENDANCE_VIEW, Perm.BRANCHES_ALL],
    )
    person = member.registered(shop, "Roster", first_name="Rano")
    person.branches.add(chilonzor, yunusobod)
    return person


def get(client, company, path="coverage/", **params):
    return client.get(f"{base(company)}{path}", params)


# GET coverage/ ------------------------------------------------------------------------------


def test_the_week_of_each_pharmacy(shop, rota, owner_api, chilonzor, yunusobod):
    response = get(owner_api(rota.owner), shop, **{"from": DAY.isoformat(), "to": DAY.isoformat()})

    assert response.status_code == 200, response.content
    body = response.json()
    assert (body["state"], body["start"], body["end"], body["need"]) == (
        "ok",
        "2026-10-21",
        "2026-10-21",
        1,
    )
    names = [row["branch"]["name"] for row in body["branches"]]
    assert names == ["Chilonzor", "Yunusobod"]
    first = body["branches"][0]
    assert (first["opens_at"], first["closes_at"], first["open_24h"]) == ("08:00", "22:00", False)
    day = first["days"][0]
    assert day["opens"] == "2026-10-21T08:00:00+05:00" and day["closed"] is None
    assert [(row["member"]["name"], row["counts"], row["reason"]) for row in day["shifts"]] == [
        ("Ali Valiyev", True, None),
        ("Vali Aliyev", False, "expired"),
    ]
    assert day["shifts"][1]["kinds"] == ["pharmacist_certificate"]
    assert [(gap["start"], gap["end"], gap["have"]) for gap in first["gaps"]] == [
        ("2026-10-21T17:00:00+05:00", "2026-10-21T22:00:00+05:00", 0)
    ]
    assert first["gap_minutes"] == 300
    second = body["branches"][1]
    assert second["open_24h"] is True and [g["minutes"] for g in second["gaps"]] == [480, 240]
    # Never a document number, an ID or anything of HR's notes.
    assert "SRT-445566" not in response.content.decode()


def test_a_week_from_today_by_default_and_62_days_at_most(shop, rota, owner_api):
    client = owner_api(rota.owner)
    body = get(client, shop).json()
    assert (body["start"], body["end"]) == ("2026-10-21", "2026-10-27")

    too_long = get(client, shop, **{"from": "2026-10-01", "to": "2026-12-31"})
    assert too_long.status_code == 400
    assert get(client, shop, **{"from": "21.10.2026"}).status_code == 400


def test_whoever_runs_the_roster_reads_it_without_the_reasons(shop, rota, roster_reader, owner_api):
    response = get(
        owner_api(roster_reader), shop, **{"from": DAY.isoformat(), "to": DAY.isoformat()}
    )

    assert response.status_code == 200
    shifts = response.json()["branches"][0]["days"][0]["shifts"]
    assert [(row["counts"], row["reason"], row["kinds"]) for row in shifts] == [
        (True, None, []),
        (False, None, []),
    ]


def test_another_company_a_missing_permission_or_hr_off(shop, rota, owner_api, outsider):
    assert get(owner_api(outsider), shop).status_code == 404
    assert get(owner_api(rota.ali), shop).status_code == 403  # no dashboard access
    rota.lead.role.permissions = [Perm.DASHBOARD_ACCESS]
    rota.lead.role.save()
    assert get(owner_api(rota.lead), shop).status_code == 403
    assert get(owner_api(rota.lead), shop, "coverage/live/").status_code == 403

    shop.features = ["payroll", "attendance"]
    shop.save()
    assert get(owner_api(rota.owner), shop).status_code == 403
    assert get(owner_api(rota.owner), shop, "coverage/live/").status_code == 403


def test_the_branch_scope(shop, rota, owner_api, chilonzor, yunusobod):
    client = owner_api(rota.lead)  # Chilonzor only

    body = get(client, shop).json()
    assert [row["branch"]["name"] for row in body["branches"]] == ["Chilonzor"]
    outside = get(client, shop, branch=[yunusobod.pk]).json()
    assert outside["branches"] == []
    mine = get(owner_api(rota.owner), shop, branch=[yunusobod.pk]).json()
    assert [row["branch"]["name"] for row in mine["branches"]] == ["Yunusobod"]


def test_drafts_count_only_for_attendance_managers(shop, rota, owner_api, chilonzor, roster_reader):
    shift_at(rota.ali, TOMORROW, time(8), time(22), branch=chilonzor, published=False)
    params = {"from": TOMORROW.isoformat(), "to": TOMORROW.isoformat(), "branch": [chilonzor.pk]}

    plain = get(owner_api(rota.owner), shop, **params).json()["branches"][0]["gaps"]
    drafts = get(owner_api(rota.owner), shop, drafts="true", **params).json()
    assert len(plain) == 1 and drafts["drafts"] is True and drafts["branches"][0]["gaps"] == []
    reader = get(owner_api(roster_reader), shop, drafts="true", **params).json()
    assert reader["drafts"] is False and len(reader["branches"][0]["gaps"]) == 1


def test_the_state_says_why_nothing_was_checked(shop, staff, owner_api):
    assert get(owner_api(staff.owner), shop).json()["state"] == "setup"
    settings = conf.get_settings(shop)
    settings.coverage_enabled = False
    settings.save()
    body = get(owner_api(staff.owner), shop).json()
    assert body["state"] == "off" and body["branches"] == []


# GET coverage/live/ ---------------------------------------------------------------------------


def test_live_lists_the_pharmacies_without_a_qualified_pharmacist_now(
    shop, rota, owner_api, yunusobod, freeze
):
    AttendanceRecord.objects.create(
        company=shop,
        membership=rota.vali,
        date=DAY,
        status="open",
        check_in_at=local(DAY, 9),
        branch=yunusobod,
    )
    freeze(local(DAY, 10))

    body = get(owner_api(rota.owner), shop, "coverage/live/").json()
    assert body["state"] == "ok"
    assert [(gap["branch"]["name"], gap["have"], gap["need"]) for gap in body["gaps"]] == [
        ("Yunusobod", 0, 1)
    ]
    assert body["gaps"][0]["checked_in"][0]["name"] == "Vali Aliyev"
    assert body["gaps"][0]["since"] == "2026-10-21T00:00:00+05:00"
    assert get(owner_api(rota.lead), shop, "coverage/live/").json()["gaps"] == []


# Who counts as a pharmacist ----------------------------------------------------------------------


def test_choosing_the_pharmacists(shop, staff, owner_api):
    head = Position.objects.create(company=shop, name="Head of pharmacy", order=0)
    client = owner_api(staff.owner)
    before = get(client, shop, "coverage/pharmacists/").json()
    assert {row["position"]["name"]: row["role"] for row in before["positions"]} == {
        "Head of pharmacy": None,
        "Pharmacist": None,
        "Office": None,
    }

    response = client.post(
        f"{base(shop)}coverage/pharmacists/",
        {
            "positions": [
                {"id": head.pk, "role": "head"},
                {"id": staff.pharmacist.pk, "role": "pharmacist"},
            ]
        },
        format="json",
    )

    assert response.status_code == 200, response.content
    rows = {row["position"]["name"]: row for row in response.json()["positions"]}
    assert rows["Head of pharmacy"]["role"] == "head" and rows["Pharmacist"]["role"] == "pharmacist"
    assert rows["Pharmacist"]["people"] == 3
    assert {(r["kind"], r["level"]) for r in rows["Head of pharmacy"]["required"]} == {
        ("pharmacy_diploma", "higher"),
        ("pharmacist_certificate", ""),
    }
    assert AuditLog.objects.filter(company=shop, action="hr.pharmacists_changed").count() == 1
    settings = get(client, shop, "settings/").json()
    assert {row["name"] for row in settings["pharmacist_positions"]} == {
        "Head of pharmacy",
        "Pharmacist",
    }

    # Documents changed by hand make it "custom"; the role then leaves them alone.
    RequiredDocument.objects.filter(position=head, kind="pharmacy_diploma").update(level="")
    assert {
        row["position"]["name"]: row["role"]
        for row in get(client, shop, "coverage/pharmacists/").json()["positions"]
    }["Head of pharmacy"] == "custom"


def test_only_hr_managers_choose_and_only_this_companys_positions(
    shop, staff, owner_api, other_company
):
    payload = {"positions": [{"id": staff.pharmacist.pk, "role": "pharmacist"}]}
    url = f"{base(shop)}coverage/pharmacists/"
    assert owner_api(staff.manager).post(url, payload, format="json").status_code == 403
    assert owner_api(staff.manager).get(url).status_code == 200
    foreign = Position.objects.create(company=other_company, name="Pharmacist")
    bad = owner_api(staff.owner).post(
        url, {"positions": [{"id": foreign.pk, "role": "head"}]}, format="json"
    )
    assert bad.status_code == 400
    odd = owner_api(staff.owner).post(
        url, {"positions": [{"id": staff.pharmacist.pk, "role": "doctor"}]}, format="json"
    )
    assert odd.status_code == 400


def test_the_coverage_settings(shop, staff, owner_api):
    client = owner_api(staff.owner)
    body = client.get(f"{base(shop)}settings/").json()
    assert {
        key: body[key]
        for key in (
            "coverage_enabled",
            "coverage_min",
            "coverage_needs_documents",
            "coverage_alert_minutes",
            "coverage_days",
            "unqualified_seller_alert",
        )
    } == {
        "coverage_enabled": True,
        "coverage_min": 1,
        "coverage_needs_documents": True,
        "coverage_alert_minutes": 15,
        "coverage_days": 14,
        "unqualified_seller_alert": True,
    }

    changed = client.patch(
        f"{base(shop)}settings/",
        {"coverage_min": 2, "unqualified_seller_alert": False},
        format="json",
    )
    assert changed.status_code == 200 and changed.json()["coverage_min"] == 2
    row = AuditLog.objects.filter(company=shop, action="hr.settings_changed").latest("pk")
    assert row.details["changes"]["coverage_min"] == [1, 2]
    assert (
        client.patch(f"{base(shop)}settings/", {"coverage_min": 0}, format="json").status_code
        == 400
    )
    assert (
        client.patch(f"{base(shop)}settings/", {"coverage_days": 90}, format="json").status_code
        == 400
    )
    assert (
        owner_api(staff.manager)
        .patch(f"{base(shop)}settings/", {"coverage_min": 3}, format="json")
        .status_code
        == 403
    )


# The AI tool ------------------------------------------------------------------------------------


def test_the_ai_tool_tells_the_gaps_and_who_doesnt_count(shop, rota):
    result = call_tool("hr_coverage", rota.owner, days=1, _now=local(DAY, 10))

    kinds = [row["type"] for row in result["rows"]]
    assert kinds.count("roster_gap") == 2  # Chilonzor 17:00 to 22:00, Yunusobod 20:00 to 24:00
    gap = next(row for row in result["rows"] if row["type"] == "roster_gap")
    assert (gap["branch"], gap["start"], gap["end"], gap["hours"]) == (
        "Chilonzor",
        "2026-10-21T17:00:00+05:00",
        "2026-10-21T22:00:00+05:00",
        5.0,
    )
    person = next(row for row in result["rows"] if row["type"] == "pharmacist_not_counted")
    assert (person["name"], person["documents"]) == ("Vali Aliyev", ["Specialist certificate"])
    assert result["data"]["state"] == "ok"
    assert [row["name"] for row in result["data"]["pharmacies"]] == ["Chilonzor", "Yunusobod"]
    assert "SRT-445566" not in json.dumps(result, ensure_ascii=False)


def test_the_ai_tool_needs_hr_view_and_keeps_to_the_branch_scope(shop, rota, yunusobod):
    assert call_tool("hr_coverage", rota.ali) == {"error": "not_allowed"}
    scoped = call_tool("hr_coverage", rota.lead, days=1, _now=local(DAY, 10))
    assert {row["branch"] for row in scoped["rows"] if "branch" in row} == {"Chilonzor"}
    assert call_tool("hr_coverage", rota.lead, branch_id=yunusobod.pk) == {"error": "not_found"}


def test_the_ai_tool_in_the_askers_language(shop, rota):
    result = call_tool("hr_coverage", rota.owner, days=1, _language="ru", _now=local(DAY, 10))
    person = next(row for row in result["rows"] if row["type"] == "pharmacist_not_counted")
    assert person["documents"] != ["Specialist certificate"]


def test_unused_documents_dont_change_the_numbers(shop, rota):
    # A diploma of another kind adds nothing (sanity for the counts above).
    EmployeeDocument.objects.create(
        company=shop,
        membership=rota.ali,
        kind=DocumentKind.DIPLOMA,
        issued_on=DAY - timedelta(days=900),
    )
    result = call_tool("hr_coverage", rota.owner, days=1, _now=local(DAY, 10))
    assert [row["type"] for row in result["rows"]].count("roster_gap") == 2
