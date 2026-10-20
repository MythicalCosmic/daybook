from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.members.models import Membership
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory

pytestmark = pytest.mark.django_db


def client_for(membership: Membership) -> APIClient:
    api = APIClient()
    api.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(membership.user).access_token}"
    )
    return api


def url(company, **params) -> str:
    query = "&".join(f"{key}={value}" for key, value in params.items())
    return f"/api/v1/companies/{company.pk}/team-stats/" + (f"?{query}" if query else "")


def test_managers_see_how_the_team_did(company, member):
    manager = member.registered(company, "Manager", first_name="Mona")
    ali = member.registered(company, first_name="Ali")
    TaskFactory(
        assignee=ali,
        created_by=manager,
        due_at=timezone.now() - timedelta(minutes=5),
        status=Task.Status.DONE,
        completed_at=timezone.now() - timedelta(minutes=10),
    )

    response = client_for(manager).get(url(company, period="month"))

    assert response.status_code == 200
    assert response.data["period"] == "month"
    assert response.data["start"].endswith("-01")
    assert response.data["totals"]["on_time_percent"] == 100
    first = response.data["members"][0]
    assert first["member"]["name"] == "Ali"
    assert (first["total"], first["on_time"], first["late_now"]) == (1, 1, 0)
    assert [row["member"]["name"] for row in response.data["members"]] == ["Ali", "Mona"]


def test_the_week_is_the_default_and_ends_on_sunday(company, member):
    manager = member.registered(company, "Manager")

    response = client_for(manager).get(url(company))

    assert response.data["period"] == "week"
    start = timezone.datetime.fromisoformat(response.data["start"]).date()
    end = timezone.datetime.fromisoformat(response.data["end"]).date()
    assert (start.weekday(), end.weekday(), (end - start).days) == (0, 6, 6)


def test_team_stats_need_the_reports_permission(company, member):
    assert client_for(member.registered(company)).get(url(company)).status_code == 403


def test_an_unknown_period_is_refused(company, member):
    response = client_for(member.registered(company, "Manager")).get(url(company, period="year"))

    assert response.status_code == 400
    assert "period" in response.data
