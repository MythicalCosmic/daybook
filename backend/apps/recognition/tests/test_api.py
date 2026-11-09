"""The employee endpoints (PLAN-LEARNING §13 R): the contract shapes, only one's own, 404 while
the module is off."""

from datetime import timedelta

import pytest

from apps.recognition import conf
from apps.recognition.models import BadgeAward, Kudos, LevelUp
from apps.recognition.tests.conftest import DAY, at
from apps.recognition.tests.factories import BadgeAwardFactory, PointsEntryFactory, StreakFactory

pytestmark = pytest.mark.django_db


def url(company, path):
    return f"/api/v1/companies/{company.pk}/recognition/{path}"


def test_me_has_the_contract_shape(shop, ali, api_as):
    PointsEntryFactory(membership=ali, points=120, reason="quiz", at=at(DAY - timedelta(days=9)))
    PointsEntryFactory(membership=ali, points=15, reason="lesson", at=at(DAY))
    StreakFactory(membership=ali, current=3, best=5, last_day=DAY)
    BadgeAwardFactory(membership=ali, badge="first_lesson", awarded_at=at(DAY))
    LevelUp.objects.create(company=shop, membership=ali, number=2, reached_at=at(DAY))
    reply = api_as(ali).get(url(shop, "me/"))
    assert reply.status_code == 200, reply.content
    data = reply.json()
    assert {
        "enabled",
        "points",
        "week_points",
        "level",
        "streak",
        "best_streak",
        "badges",
        "locked",
        "recent",
        "unseen",
    } <= set(data)
    assert (data["points"], data["week_points"], data["streak"], data["best_streak"]) == (
        135,
        15,
        3,
        5,
    )
    assert data["level"] == {
        "number": 2,
        "name": "Learner",
        "starts_at": 100,
        "next_at": 250,
        "next_name": "Active",
    }
    assert data["badges"][0]["key"] == "first_lesson" and data["badges"][0]["tier"] == "bronze"
    assert data["badges"][0]["icon"] == "circle-play"
    assert "first_lesson" not in {badge["key"] for badge in data["locked"]}
    assert len(data["locked"]) == 14
    assert data["recent"][0]["label"] == "Lesson watched" and data["recent"][0]["points"] == 15
    assert [item["type"] for item in data["unseen"]] == ["level", "badge"]
    assert data["unseen"][0] == {
        "type": "level",
        "number": 2,
        "name": "Learner",
        "starts_at": 100,
        "next_at": 250,
    }
    assert data["kudos_left"] == 3 and data["leaderboard"] is True


def test_seen_ends_the_celebration(shop, ali, madina, api_as):
    BadgeAwardFactory(membership=ali, badge="first_quiz")
    Kudos.objects.create(company=shop, from_member=madina, to_member=ali)
    client = api_as(ali)
    assert client.post(url(shop, "seen/"), {}, format="json").status_code == 204
    assert client.get(url(shop, "me/")).json()["unseen"] == []
    assert not BadgeAward.objects.filter(seen_at__isnull=True).exists()
    assert Kudos.objects.get().seen_at is None
    assert client.post(url(shop, "seen/"), {"kudos": True}, format="json").status_code == 204
    assert Kudos.objects.get().seen_at is not None


def test_everything_is_404_while_the_module_is_off(shop, ali, api_as):
    shop.features = ["learning"]
    shop.save(update_fields=["features"])
    client = api_as(ali)
    for path in ("me/", "leaderboard/", "kudos/", "kudos/colleagues/"):
        assert client.get(url(shop, path)).status_code == 404
    assert client.post(url(shop, "seen/"), {}, format="json").status_code == 404


def test_another_company_is_404(shop, ali, api_as, other_company):
    other_company.features = ["recognition"]
    other_company.save(update_fields=["features"])
    assert api_as(ali).get(url(other_company, "me/")).status_code == 404


def test_leaderboard_params_and_shape(shop, ali, madina, api_as):
    PointsEntryFactory(membership=madina, points=30, at=at(DAY))
    PointsEntryFactory(membership=ali, points=10, at=at(DAY))
    client = api_as(ali)
    reply = client.get(url(shop, "leaderboard/?period=month&scope=branch"))
    assert reply.status_code == 200
    data = reply.json()
    assert data["visible"] and data["period"] == "month" and data["scope"] == "branch"
    assert [row["place"] for row in data["rows"]] == [1, 2]
    assert data["rows"][0]["member"]["name"] == "Madina Saidova"
    assert data["rows"][0]["level"] == {"number": 1, "name": "Newcomer"}
    assert set(data["rows"][0]["member"]) == {"id", "name", "avatar_url", "position"}
    assert data["me"] == {"place": 2, "points": 10}
    assert client.get(url(shop, "leaderboard/?period=year")).status_code == 400


def test_send_kudos_and_the_feeds(shop, ali, madina, api_as, django_capture_on_commit_callbacks):
    client = api_as(madina)
    with django_capture_on_commit_callbacks(execute=True):
        reply = client.post(
            url(shop, "kudos/"),
            {"to": ali.pk, "badge": "helpful", "message": "  Navbatchilikda  yordam berding "},
            format="json",
        )
    assert reply.status_code == 201, reply.content
    data = reply.json()
    assert data["from"]["id"] == madina.pk and data["to"]["id"] == ali.pk
    assert data["badge"] == "helpful" and data["badge_label"] == "Helped a customer"
    assert data["message"] == "Navbatchilikda yordam berding" and data["mine"] is True
    received = api_as(ali).get(url(shop, "kudos/?box=received")).json()
    assert [row["id"] for row in received] == [data["id"]] and received[0]["mine"] is False
    assert api_as(ali).get(url(shop, "kudos/?box=given")).json() == []
    me = api_as(ali).get(url(shop, "me/")).json()
    assert [row["id"] for row in me["kudos_today"]] == [data["id"]]
    assert me["points"] == 5


def test_send_kudos_refusals(shop, ali, madina, api_as, member, other_company):
    client = api_as(madina)
    reply = client.post(url(shop, "kudos/"), {"to": madina.pk}, format="json")
    assert reply.status_code == 400 and "yourself" in reply.json()["detail"]
    stranger = member(other_company, "Employee")
    assert client.post(url(shop, "kudos/"), {"to": stranger.pk}, format="json").status_code == 400
    reply = client.post(url(shop, "kudos/"), {"to": ali.pk, "task": 999999}, format="json")
    assert reply.status_code == 400 and "task" in reply.json()
    for _ in range(3):
        assert client.post(url(shop, "kudos/"), {"to": ali.pk}, format="json").status_code == 201
    reply = client.post(url(shop, "kudos/"), {"to": ali.pk}, format="json")
    assert reply.status_code == 400 and "a day" in reply.json()["detail"]


def test_colleagues_in_my_scope_and_not_me(shop, ali, madina, nigora, api_as):
    reply = api_as(ali).get(url(shop, "kudos/colleagues/"))
    assert reply.status_code == 200
    data = reply.json()
    assert data["per_day"] == 3 and data["left"] == 3
    ids = [row["id"] for row in data["results"]]
    assert madina.pk in ids and ali.pk not in ids and nigora.pk not in ids  # other branch
    assert data["results"][0]["branch"] == "Chilonzor"
    found = api_as(ali).get(url(shop, "kudos/colleagues/?q=madi")).json()["results"]
    assert [row["id"] for row in found] == [madina.pk]
    settings = conf.get_settings(shop)
    settings.kudos_enabled = False
    settings.save()
    assert api_as(ali).get(url(shop, "kudos/colleagues/")).json()["left"] == 0
