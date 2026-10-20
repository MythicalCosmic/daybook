"""Mini app endpoints of projects: my projects, the board, moving my own cards, my time and
timer, the updates feed."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.projects import services
from apps.projects.models import RunningTimer
from apps.projects.tests.factories import card, lists, project, team

pytestmark = pytest.mark.django_db


@pytest.fixture
def people(company, member):
    return team(company, member)


@pytest.fixture
def reno(company, people):
    reno = project(company, people["owner"], lead=people["manager"], key="RENO", status="active")
    services.add_member(reno, people["aziz"], by=people["owner"])
    return reno


def url(company, tail=""):
    return f"/api/v1/companies/{company.pk}/projects/{tail}"


def test_my_projects_are_the_ones_i_work_on(company, people, reno, api_as):
    project(company, people["owner"], name="Not mine", visibility="company")
    card(reno, people["owner"], assignee=people["aziz"])

    rows = api_as(people["aziz"]).get(url(company)).json()

    assert [row["key"] for row in rows] == ["RENO"]
    assert rows[0]["my_role"] == "member" and rows[0]["my_open"] == 1
    assert "spent" not in rows[0]  # an employee doesn't see the project's money


def test_the_board_reads_for_members_and_404s_for_others(company, people, reno, api_as):
    mine = card(reno, people["owner"], assignee=people["aziz"])
    card(reno, people["owner"], assignee=people["manager"], title="Theirs")

    board = api_as(people["aziz"]).get(url(company, f"{reno.pk}/board/"))

    assert board.status_code == 200
    cards = {row["id"]: row for row in board.json()["cards"]}
    assert len(cards) == 2
    assert cards[mine.pk]["can_move"] is True
    assert board.json()["capabilities"]["manage"] is False
    assert api_as(people["madina"]).get(url(company, f"{reno.pk}/board/")).status_code == 404


def test_i_move_my_own_card_but_not_someone_elses(company, people, reno, api_as, member):
    viewer = member.registered(company)
    services.add_member(reno, viewer, by=people["owner"], role="viewer")
    mine = card(reno, people["owner"], assignee=viewer)
    theirs = card(reno, people["owner"], assignee=people["aziz"], title="Theirs")
    client = api_as(viewer)
    doing = lists(reno)["In progress"].pk

    ok = client.post(
        url(company, f"{reno.pk}/cards/{mine.pk}/move/"),
        {"list": doing, "position": 5},
        format="json",
    )
    denied = client.post(
        url(company, f"{reno.pk}/cards/{theirs.pk}/move/"),
        {"list": doing, "position": 5},
        format="json",
    )
    done = client.post(
        url(company, f"{reno.pk}/cards/{mine.pk}/move/"),
        {"list": lists(reno)["Done"].pk, "position": 1},
        format="json",
    )

    assert ok.status_code == 200 and ok.json()["card"]["list_id"] == doing
    assert denied.status_code == 403
    assert done.status_code == 200 and done.json()["card"]["status"] == "done"
    assert done.json()["message"]


def test_my_time_and_timer(company, people, reno, api_as):
    work = card(reno, people["owner"], assignee=people["aziz"])
    client = api_as(people["aziz"])

    logged = client.post(
        url(company, "time/"),
        {"day": str(timezone.localdate()), "minutes": 45, "task": work.pk, "note": "Primer"},
        format="json",
    )
    started = client.post(url(company, "timer/"), {"task": work.pk}, format="json")
    current = client.get(url(company, "timer/")).json()["timer"]
    RunningTimer.objects.filter(membership=people["aziz"]).update(
        started_at=timezone.now() - timedelta(minutes=20)
    )
    stopped = client.post(url(company, "timer/stop/"))
    week = client.get(url(company, "time/")).json()

    assert logged.status_code == 201 and logged.json()["project_key"] == "RENO"
    assert started.status_code == 201 and current["task_key"] == "RENO-1"
    assert stopped.status_code == 200 and stopped.json()["minutes"] == 20
    assert week["total"] == 65
    assert client.get(url(company, "timer/")).json() == {"timer": None}


def test_i_cant_track_time_on_someone_elses_task_or_delete_their_time(
    company, people, reno, api_as
):
    theirs = card(reno, people["owner"], assignee=people["manager"])
    viewer_client = api_as(people["madina"])  # not on the project
    entry = services.log_time(people["aziz"], day=timezone.localdate(), minutes=30, project=reno)

    tracked = viewer_client.post(url(company, "timer/"), {"task": theirs.pk}, format="json")
    deleted = viewer_client.delete(url(company, f"time/{entry.pk}/"))

    assert tracked.status_code == 403
    assert deleted.status_code == 404


def test_updates_feed_and_posting(company, people, reno, api_as):
    services.post_update(reno, by=people["manager"], health="on_track", text="All good")

    feed = api_as(people["aziz"]).get(url(company, f"{reno.pk}/updates/")).json()
    posted = api_as(people["manager"]).post(
        url(company, f"{reno.pk}/updates/"),
        {"health": "at_risk", "text": "Tiles late"},
        format="json",
    )

    assert feed[0]["text"] == "All good"
    assert posted.status_code == 201


def test_an_owner_token_cant_use_the_mini_app_api(company, people, reno, owner_api):
    assert owner_api(people["owner"]).get(url(company)).status_code == 401


def test_a_mini_app_token_cant_use_the_owner_api(company, people, reno, api_as):
    response = api_as(people["owner"]).get(f"/api/v1/owner/companies/{company.pk}/projects/")
    assert response.status_code == 401
