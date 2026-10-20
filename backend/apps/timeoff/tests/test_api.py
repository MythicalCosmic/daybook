from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.members.models import Membership
from apps.timeoff.models import Holiday, TimeOff

pytestmark = pytest.mark.django_db


@pytest.fixture
def today():
    return timezone.localdate(timezone=ZoneInfo("Asia/Tashkent"))


@pytest.fixture
def worker(company, member):
    return member.registered(company)


def client_for(membership: Membership) -> APIClient:
    api = APIClient()
    api.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(membership.user).access_token}"
    )
    return api


def url(company, *parts) -> str:
    return "/".join([f"/api/v1/companies/{company.pk}/time-off", *map(str, parts), ""])


def test_asking_for_time_off_and_cancelling_it(company, worker, today):
    api = client_for(worker)
    first = today + timedelta(days=3)

    created = api.post(
        url(company), {"first_day": first, "last_day": first + timedelta(days=1)}, format="json"
    )

    assert created.status_code == 201
    assert (created.data["status"], created.data["days"]) == ("pending", 2)
    assert [item["id"] for item in api.get(url(company)).data] == [created.data["id"]]

    cancelled = api.post(url(company, created.data["id"], "cancel"))

    assert cancelled.status_code == 200
    assert cancelled.data["status"] == "cancelled"


def test_an_impossible_request_says_why(company, worker, today):
    yesterday = today - timedelta(days=1)

    response = client_for(worker).post(
        url(company), {"first_day": yesterday, "last_day": yesterday}, format="json"
    )

    assert response.status_code == 400
    assert "past" in response.data["detail"]


def test_people_only_see_their_own_time_off(company, member, worker, today):
    other = member.registered(company)
    theirs = TimeOff.objects.create(
        company=company, membership=other, first_day=today, last_day=today
    )

    assert client_for(worker).get(url(company)).data == []
    assert client_for(worker).post(url(company, theirs.pk, "cancel")).status_code == 404


def test_old_time_off_drops_off_the_list(company, worker, today):
    long_ago = today - timedelta(days=60)
    TimeOff.objects.create(
        company=company, membership=worker, first_day=long_ago, last_day=long_ago
    )

    assert client_for(worker).get(url(company)).data == []


def test_coming_holidays(company, other_company, worker, today):
    Holiday.objects.create(company=company, date=today + timedelta(days=10), name="Navruz")
    Holiday.objects.create(company=company, date=today - timedelta(days=1), name="Gone")
    Holiday.objects.create(company=other_company, date=today + timedelta(days=5), name="Theirs")

    response = client_for(worker).get(f"/api/v1/companies/{company.pk}/holidays/")

    assert [holiday["name"] for holiday in response.data] == ["Navruz"]


def test_the_admin_approves_time_off(admin_client, company, worker, today, sent_messages):
    time_off = TimeOff.objects.create(
        company=company, membership=worker, first_day=today, last_day=today
    )

    response = admin_client.post(
        "/admin/timeoff/timeoff/",
        {"action": "approve_selected", "_selected_action": [time_off.pk]},
    )

    assert response.status_code == 302
    time_off.refresh_from_db()
    assert time_off.status == TimeOff.Status.APPROVED
