"""Who read what (docs/PLAN-LEARNING.md §4.1): the reader's reports, capped by real time, the
deepest scroll kept, a new visit after 30 minutes; always on, also without learning."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.knowledge import page_views
from apps.knowledge.models import PageView
from apps.knowledge.tests.factories import PageFactory, SpaceFactory
from apps.members.models import Position

pytestmark = pytest.mark.django_db

T0 = timezone.now().replace(microsecond=0)


@pytest.fixture
def page(company):
    return PageFactory(space__company=company)


def report(page, person, *, at, session="s1", seconds=15, scrolled=0):
    return page_views.record(
        page,
        person,
        session=session,
        seconds=seconds,
        scrolled=scrolled,
        now=T0 + timedelta(seconds=at),
    )


def test_reports_count_real_time_only(page, member, company):
    person = member(company)
    report(page, person, at=0, seconds=60)  # a session's first report: at most 5 s
    report(page, person, at=15, seconds=15)
    report(page, person, at=20, seconds=30)  # 5 s after the last one: at most 10
    report(page, person, at=200, seconds=500)  # never more than 30 at once
    row = PageView.objects.get(page=page, membership=person)
    assert row.seconds == 5 + 15 + 10 + 30
    assert row.visits == 1


def test_the_deepest_scroll_and_the_newest_version_stay(page, member, company):
    person = member(company)
    report(page, person, at=0, scrolled=70)
    page.version = 3
    page.save()
    report(page, person, at=15, scrolled=20)
    row = PageView.objects.get(page=page, membership=person)
    assert (row.scrolled, row.version) == (70, 3)


def test_a_new_visit_after_half_an_hour(page, member, company):
    person = member(company)
    report(page, person, at=0)
    report(page, person, at=60, session="s2")
    report(page, person, at=60 + 31 * 60, session="s3")
    row = PageView.objects.get(page=page, membership=person)
    assert row.visits == 2
    assert row.first_at == T0 and row.last_at == T0 + timedelta(seconds=60 + 31 * 60)


def test_the_endpoint_answers_204_and_404_for_pages_i_cant_read(company, member, api_as):
    person = member(company)
    page = PageFactory(space__company=company)
    client = api_as(person)
    base = f"/api/v1/companies/{company.pk}/knowledge/pages/"
    response = client.post(
        f"{base}{page.pk}/view/", {"session": "x", "seconds": 3, "scrolled": 40}, format="json"
    )
    assert response.status_code == 204, response.content
    assert PageView.objects.get(page=page, membership=person).scrolled == 40
    closed = SpaceFactory(company=company, audience_all=False)
    closed.positions.set([Position.objects.create(company=company, name="Cashier")])
    hidden = PageFactory(space=closed)
    assert (
        client.post(f"{base}{hidden.pk}/view/", {"session": "x"}, format="json").status_code == 404
    )
    draft = PageFactory(space__company=company, published=False)
    assert (
        client.post(f"{base}{draft.pk}/view/", {"session": "x"}, format="json").status_code == 404
    )
    assert client.post(f"{base}{page.pk}/view/", {}, format="json").status_code == 400


# The dashboard: readers, page topics ------------------------------------------------------


def knowledge_manager(company, member):
    from apps.members.models import AccessRole

    made = AccessRole.objects.create(
        company=company,
        name="Knowledge lead",
        permissions=["dashboard.access", "knowledge.manage", "branches.all"],
    )
    return member(company, made.name)


def test_readers_show_who_opened_the_page_and_how_far_they_read(company, member, owner_api):
    lead = knowledge_manager(company, member)
    page = PageFactory(space__company=company)
    reader, idle = member(company, first_name="Madina"), member(company, first_name="Jasur")
    report(page, reader, at=0, scrolled=80)
    report(page, reader, at=15, seconds=15, scrolled=40)
    base = f"/api/v1/owner/companies/{company.pk}/knowledge/pages/{page.pk}/"
    body = owner_api(lead).get(f"{base}readers/").json()
    assert body["counts"]["opened"] == 1
    views = {row["member"]["id"]: row["view"] for row in body["results"]}
    assert views[reader.pk]["opened"] is True and views[reader.pk]["scrolled"] == 80
    assert views[reader.pk]["seconds"] == 20 and views[reader.pk]["visits"] == 1
    assert views[idle.pk] == {
        "opened": False,
        "visits": 0,
        "seconds": 0,
        "scrolled": 0,
        "version": None,
        "first_at": None,
        "last_at": None,
    }
    listed = owner_api(lead).get(f"/api/v1/owner/companies/{company.pk}/knowledge/pages/").json()
    row = next(item for item in listed["results"] if item["id"] == page.pk)
    assert row["opened"] == 1
    reported = owner_api(lead).post(f"{base}view/", {"session": "d", "seconds": 4}, format="json")
    assert reported.status_code == 204
    assert PageView.objects.filter(page=page, membership=lead).exists()


def test_pages_carry_topics_from_the_editor_and_filter_by_them(
    company, other_company, member, owner_api
):
    from apps.knowledge import topics

    lead = knowledge_manager(company, member)
    cold = topics.create_topic(company, by=None, name="Sovuq zanjir")
    till = topics.create_topic(company, by=None, name="Kassa")
    space = SpaceFactory(company=company)
    client = owner_api(lead)
    base = f"/api/v1/owner/companies/{company.pk}/knowledge/pages/"
    made = client.post(
        base,
        {"space": space.pk, "title": "Muzlatgich", "body": "<p>+2…+8</p>", "topic_ids": [cold.pk]},
        format="json",
    )
    assert made.status_code == 201, made.content
    assert made.json()["topics"] == [{"id": cold.pk, "name": "Sovuq zanjir", "color": ""}]
    page_id = made.json()["id"]
    saved = client.patch(f"{base}{page_id}/", {"topic_ids": [till.pk, cold.pk]}, format="json")
    assert {topic["id"] for topic in saved.json()["topics"]} == {till.pk, cold.pk}
    other = PageFactory(space=space)
    filtered = client.get(f"{base}?topic={till.pk}").json()["results"]
    assert [row["id"] for row in filtered] == [page_id]
    assert other.pk not in [row["id"] for row in filtered]
    theirs = topics.create_topic(other_company, by=None, name="Boshqa")
    refused = client.patch(f"{base}{page_id}/", {"topic_ids": [theirs.pk]}, format="json")
    assert refused.status_code == 400
