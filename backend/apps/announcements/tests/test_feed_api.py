"""The employee announcements feed (`E announcements/`): pinned first, expired hidden, and
"I've read it" from the app."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.announcements import services
from apps.announcements.models import Announcement, Receipt
from apps.companies.tests.factories import BranchFactory
from apps.members.tests.factories import PositionFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop(company, member):
    chilonzor = company.branches.first()
    BranchFactory(company=company, name="Yunusobod")
    owner = member.registered(company, "Owner")
    a = member.registered(company, first_name="A", home_branch=chilonzor)
    a.branches.set([chilonzor])
    return {"owner": owner, "a": a}


def test_pinned_first_and_expired_hidden_in_the_feed(shop, api_as):
    now = timezone.now()
    old = services.publish(shop["owner"], "Old news")
    pinned = services.publish(shop["owner"], "House rules", pinned_until=now + timedelta(days=3))
    services.publish(shop["owner"], "Newest")
    gone = services.publish(shop["owner"], "Gone soon", expires_at=now + timedelta(days=1))
    Announcement.objects.filter(pk=gone.pk).update(expires_at=now - timedelta(minutes=1))
    Announcement.objects.filter(pk=old.pk).update(sent_at=now - timedelta(days=2))

    response = api_as(shop["a"]).get(f"/api/v1/companies/{shop['a'].company_id}/announcements/")

    assert response.status_code == 200
    titles = [row["title"] for row in response.data["results"]]
    assert titles[0] == "House rules"
    assert "Gone soon" not in titles
    assert titles.index("Newest") < titles.index("Old news")
    assert response.data["results"][0]["is_pinned"] is True
    assert pinned.pk == response.data["results"][0]["id"]


def test_reading_from_the_app(shop, api_as):
    announcement = services.publish(shop["owner"], "Read me")
    url = f"/api/v1/companies/{shop['a'].company_id}/announcements/{announcement.pk}/read/"

    response = api_as(shop["a"]).post(url)

    assert response.status_code == 200 and response.data["read_at"]
    assert Receipt.objects.get(announcement=announcement, membership=shop["a"]).read_at
    # Someone who didn't get it can't read it.
    other = services.publish(
        shop["owner"], "Cooks only", [PositionFactory(company=shop["a"].company).pk]
    )
    url = f"/api/v1/companies/{shop['a'].company_id}/announcements/{other.pk}/read/"
    assert api_as(shop["a"]).post(url).status_code == 404
