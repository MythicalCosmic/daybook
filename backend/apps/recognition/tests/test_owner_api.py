"""The owner endpoints (rule 21): company scope (404), permissions (403), branch scope, audit,
hidden fields, the module switch."""

import pytest

from apps.audit.models import AuditLog
from apps.members.models import AccessRole
from apps.members.permissions import Perm
from apps.recognition import conf, services
from apps.recognition.models import Kudos, PointsEntry
from apps.recognition.tests.conftest import DAY, at
from apps.recognition.tests.factories import BadgeAwardFactory, PointsEntryFactory

pytestmark = pytest.mark.django_db


def url(company, path):
    return f"/api/v1/owner/companies/{company.pk}/recognition/{path}"


@pytest.fixture
def viewer(shop, member):
    """Dashboard access only: no members.view, learning.view or recognition.manage."""
    role = AccessRole.objects.create(company=shop, name="Desk", permissions=[Perm.DASHBOARD_ACCESS])
    person = member(shop, "Employee")
    person.role = role
    person.save(update_fields=["role"])
    return person


def test_leaderboard_with_branch_scope(shop, owner, head, ali, nigora, owner_api, yunusobod):
    PointsEntryFactory(membership=ali, points=30, at=at(DAY))
    PointsEntryFactory(membership=nigora, points=50, at=at(DAY))
    BadgeAwardFactory(membership=nigora, badge="first_quiz")
    data = owner_api(owner).get(url(shop, "leaderboard/?period=week")).json()
    assert [row["member"]["id"] for row in data["rows"]] == [nigora.pk, ali.pk]
    assert data["rows"][0]["badges"] == 1 and data["kind"] == "all"
    assert set(data["rows"][0]) == {"place", "member", "points", "level", "badges", "streak"}
    yunus = owner_api(owner).get(url(shop, f"leaderboard/?branch={yunusobod.pk}")).json()
    assert [row["member"]["id"] for row in yunus["rows"]] == [nigora.pk]
    # The head sees Chilonzor only; another branch's filter is 404.
    head_rows = owner_api(head).get(url(shop, "leaderboard/")).json()["rows"]
    assert [row["member"]["id"] for row in head_rows] == [ali.pk]
    assert owner_api(head).get(url(shop, f"leaderboard/?branch={yunusobod.pk}")).status_code == 404
    assert owner_api(owner).get(url(shop, "leaderboard/?date=7-11")).status_code == 400


def test_permissions_and_other_companies(
    shop, owner, head, viewer, ali, owner_api, other_company, member
):
    assert owner_api(viewer).get(url(shop, "leaderboard/")).status_code == 403
    assert owner_api(viewer).get(url(shop, "badges/")).status_code == 403
    assert owner_api(head).get(url(shop, "settings/")).status_code == 200
    reply = owner_api(head).patch(url(shop, "settings/"), {"kudos_per_day": 5}, format="json")
    assert reply.status_code == 403
    reply = owner_api(head).post(
        url(shop, f"people/{ali.pk}/adjust/"), {"points": 5, "note": "x"}, format="json"
    )
    assert reply.status_code == 403
    stranger_owner = member(other_company, "Owner")
    other_company.features = ["recognition"]
    other_company.save(update_fields=["features"])
    assert owner_api(stranger_owner).get(url(shop, "leaderboard/")).status_code == 404
    stranger = member(other_company, "Employee")
    assert owner_api(owner).get(url(shop, f"people/{stranger.pk}/")).status_code == 404


def test_person_page_adjust_and_scope(shop, owner, head, ali, nigora, owner_api):
    PointsEntryFactory(membership=ali, points=40, reason="quiz", at=at(DAY, 8))
    reply = owner_api(owner).post(
        url(shop, f"people/{ali.pk}/adjust/"),
        {"points": -10, "note": "Counted twice"},
        format="json",
    )
    assert reply.status_code == 200, reply.content
    data = reply.json()
    assert data["points"] == 30 and data["history"][0]["detail"] == "Counted twice"
    assert data["history"][0]["label"] == "Correction"
    assert AuditLog.objects.filter(action="recognition.points_adjusted").count() == 1
    assert owner_api(head).get(url(shop, f"people/{ali.pk}/")).status_code == 200
    assert owner_api(head).get(url(shop, f"people/{nigora.pk}/")).status_code == 404
    reply = owner_api(owner).post(
        url(shop, f"people/{ali.pk}/adjust/"), {"points": 50000, "note": "x"}, format="json"
    )
    assert reply.status_code == 400


def test_kudos_feed_hide_and_say_thanks(shop, owner, head, madina, ali, nigora, owner_api):
    first = services.send_kudos(madina, to=ali, badge="careful", message="Rahmat")
    services.send_kudos(nigora, to=madina)
    data = owner_api(owner).get(url(shop, "kudos/")).json()
    assert len(data) == 2 and data[-1]["id"] == first.pk
    assert {"id", "from", "to", "badge", "badge_label", "message", "task", "at"} <= set(data[0])
    assert owner_api(owner).get(url(shop, f"kudos/?member={ali.pk}")).json()[0]["id"] == first.pk
    assert owner_api(head).post(url(shop, f"kudos/{first.pk}/hide/")).status_code == 403
    assert owner_api(owner).post(url(shop, f"kudos/{first.pk}/hide/")).status_code == 204
    assert owner_api(owner).post(url(shop, f"kudos/{first.pk}/hide/")).status_code == 404
    assert [row["id"] for row in owner_api(owner).get(url(shop, "kudos/")).json()] != [first.pk]
    assert not PointsEntry.objects.filter(key=f"kudos:{first.pk}").exists()
    # "Say thanks" from a profile: the dashboard user thanks someone they see.
    reply = owner_api(head).post(
        url(shop, "kudos/"), {"to": ali.pk, "badge": "star"}, format="json"
    )
    assert reply.status_code == 201 and reply.json()["from"]["id"] == head.pk
    assert (
        owner_api(head).post(url(shop, "kudos/"), {"to": nigora.pk}, format="json").status_code
        == 404
    )
    assert Kudos.objects.filter(from_member=head).count() == 1


def test_badges_catalogue_with_holders(shop, owner, head, ali, nigora, owner_api):
    BadgeAwardFactory(membership=ali, badge="first_lesson")
    BadgeAwardFactory(membership=nigora, badge="first_lesson")
    BadgeAwardFactory(membership=nigora, badge="top3_month", ref="2026-10")
    data = owner_api(owner).get(url(shop, "badges/")).json()
    assert len(data) == 15
    first = next(entry for entry in data if entry["key"] == "first_lesson")
    assert first["count"] == 2 and first["tier"] == "bronze"
    top = next(entry for entry in data if entry["key"] == "top3_month")
    assert top["holders"][0]["name"] == "Top three of the month: October 2026"
    head_view = owner_api(head).get(url(shop, "badges/")).json()
    assert next(entry for entry in head_view if entry["key"] == "first_lesson")["count"] == 1


def test_settings_read_and_change(shop, owner, owner_api):
    data = owner_api(owner).get(url(shop, "settings/")).json()
    assert data["kudos_per_day"] == 3 and data["points_table"] == {}
    rows = {row["key"]: row for row in data["points"]}
    assert rows["quiz"] == {
        "key": "quiz",
        "label": "Quiz passed (first time)",
        "default": 20,
        "points": 20,
    }
    assert len(data["levels"]) == 10
    reply = owner_api(owner).patch(
        url(shop, "settings/"),
        {
            "kudos_per_day": 5,
            "points_table": {"quiz": 25, "lesson": 10},
            "leaderboard_scope": "branch",
        },
        format="json",
    )
    assert reply.status_code == 200, reply.content
    data = reply.json()
    assert data["points_table"] == {"quiz": 25} and data["kudos_per_day"] == 5
    assert {row["key"]: row["points"] for row in data["points"]}["quiz"] == 25
    assert conf.get_settings(shop).leaderboard_scope == "branch"
    log = AuditLog.objects.get(action="recognition.settings_changed")
    assert log.details["changed"]["kudos_per_day"] == {"from": 3, "to": 5}
    bad = owner_api(owner).patch(
        url(shop, "settings/"), {"points_table": {"quiz": 5000}}, format="json"
    )
    assert bad.status_code == 400
    bad = owner_api(owner).patch(url(shop, "settings/"), {"kudos_per_day": 0}, format="json")
    assert bad.status_code == 400


def test_everything_is_404_while_the_module_is_off(shop, owner, ali, owner_api):
    shop.features = ["learning"]
    shop.save(update_fields=["features"])
    client = owner_api(owner)
    for path in ("leaderboard/", "kudos/", "badges/", "settings/", f"people/{ali.pk}/"):
        assert client.get(url(shop, path)).status_code == 404, path
