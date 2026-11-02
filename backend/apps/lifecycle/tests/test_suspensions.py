"""Suspensions through the lifecycle API: the existing `members.services.suspend/reinstate`,
rules and all (hr.suspend; never the last owner; never oneself), listed with why and until."""

from datetime import timedelta

import pytest

from apps.hr.tests.conftest import DAY
from apps.members import services as members
from apps.members.models import Membership

pytestmark = pytest.mark.django_db


def path(company, tail="") -> str:
    return f"/api/v1/owner/companies/{company.pk}/lifecycle/suspensions/{tail}"


def test_suspend_list_and_reinstate(shop, staff, owner_api, django_capture_on_commit_callbacks):
    client = owner_api(staff.owner)

    with django_capture_on_commit_callbacks(execute=True):
        created = client.post(
            path(shop),
            {"member_id": staff.ali.pk, "until": "2026-10-26", "reason": "Kamomad tekshirilmoqda"},
            format="json",
        )

    assert created.status_code == 201, created.content
    row = created.json()
    assert row["member"]["name"] == "Ali Valiyev"
    assert row["until"] == "2026-10-26" and row["reason"] == "Kamomad tekshirilmoqda"
    assert row["by"] == "Dilnoza Karimova" and row["can_reinstate"] is True
    assert Membership.objects.get(pk=staff.ali.pk).status == "suspended"
    listed = owner_api(staff.accountant).get(path(shop)).json()  # hr.view reads
    assert [item["member"]["id"] for item in listed] == [staff.ali.pk]
    assert listed[0]["can_reinstate"] is False

    assert client.post(path(shop, f"{staff.ali.pk}/reinstate/")).status_code == 204
    assert Membership.objects.get(pk=staff.ali.pk).status == "approved"
    assert client.get(path(shop)).json() == []


def test_only_hr_suspend_holders_suspend(shop, staff, owner_api):
    response = owner_api(staff.manager).post(
        path(shop), {"member_id": staff.ali.pk, "reason": "x"}, format="json"
    )

    assert response.status_code == 403
    assert owner_api(staff.vali).get(path(shop)).status_code == 403


def test_the_members_rules_hold(shop, staff, owner_api, outsider):
    client = owner_api(staff.owner)

    no_reason = client.post(path(shop), {"member_id": staff.ali.pk, "reason": " "}, format="json")
    themselves = client.post(
        path(shop), {"member_id": staff.owner.pk, "reason": "x"}, format="json"
    )
    past = client.post(
        path(shop),
        {"member_id": staff.ali.pk, "reason": "x", "until": str(DAY - timedelta(days=1))},
        format="json",
    )
    foreign = client.post(path(shop), {"member_id": outsider.pk, "reason": "x"}, format="json")

    assert no_reason.status_code == 400
    assert themselves.status_code == 400
    assert past.status_code == 400
    assert foreign.status_code == 404
    assert client.post(path(shop, f"{staff.vali.pk}/reinstate/")).status_code == 400


def test_the_list_stays_in_the_branch_scope(shop, staff, owner_api):
    members.suspend(staff.sara, by=staff.owner, until=None, reason="Yunusobod")
    members.suspend(staff.ali, by=staff.owner, until=None, reason="Chilonzor")

    rows = owner_api(staff.lead).get(path(shop)).json()

    assert [row["member"]["name"] for row in rows] == ["Ali Valiyev"]
    assert rows[0]["until"] is None
