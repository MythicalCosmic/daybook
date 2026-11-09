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
