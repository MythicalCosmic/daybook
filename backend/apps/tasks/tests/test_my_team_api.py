"""The mini app's My team: a head's people, their counts, and one person's work."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.members import departments
from apps.tasks import services
from apps.tasks.models import Proof, Task

pytestmark = pytest.mark.django_db


@pytest.fixture
def team(company, member):
    owner = member.registered(company, "Owner")
    head = member.registered(company, first_name="Bekzod")
    alisher = member.registered(company, first_name="Alisher")
    otabek = member.registered(company, first_name="Otabek")
    sales = departments.create_department(company, by=owner, name="Savdo", head=head)
    departments.place(sales, by=owner, people=[alisher])
    late = services.create_task(
        by=owner, assignee=alisher, title="Vitrina", due_at=timezone.now() + timedelta(hours=1)
    )
    Task.objects.filter(pk=late.pk).update(due_at=timezone.now() - timedelta(hours=1))
    done = services.create_task(by=owner, assignee=alisher, title="Hisobot", proof=Proof.TEXT)
    services.complete_task(done, by=alisher, proof_text="Hammasi joyida")
    return {"owner": owner, "head": head, "alisher": alisher, "otabek": otabek}


def url(company, suffix=""):
    return f"/api/v1/companies/{company.pk}/my-team/{suffix}"


def test_a_head_sees_their_people_with_counts(api_as, company, team):
    response = api_as(team["head"]).get(url(company))

    assert response.status_code == 200
    assert response.data["departments"] == ["Savdo"]
    [row] = response.data["people"]
    assert row["name"].startswith("Alisher")
    assert (row["open"], row["late"], row["done_week"]) == (1, 1, 1)


def test_a_head_opens_a_persons_work_with_its_proof(api_as, company, team):
    response = api_as(team["head"]).get(url(company, f"{team['alisher'].pk}/"))

    assert response.status_code == 200
    assert [task["title"] for task in response.data["open"]] == ["Vitrina"]
    [done] = response.data["done"]
    assert done["title"] == "Hisobot"
    assert done["proof_text"] == "Hammasi joyida"


def test_not_their_people_and_not_heads_get_nothing(api_as, company, team):
    assert api_as(team["head"]).get(url(company, f"{team['otabek'].pk}/")).status_code == 404
    assert api_as(team["alisher"]).get(url(company)).status_code == 403


def test_the_app_knows_which_departments_someone_heads(api_as, company, team):
    me = api_as(team["head"]).get("/api/v1/me/").data["memberships"][0]

    assert me["heads"] == ["Savdo"]
