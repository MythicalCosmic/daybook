"""Topics (docs/PLAN-LEARNING.md §3.1): kept by knowledge or learning managers, read by everyone
with the dashboard, one live name per company, the pharmacy set in the company's language."""

import pytest
from django.core.exceptions import PermissionDenied

from apps.core.exceptions import DomainError
from apps.knowledge import topics
from apps.knowledge.models import Topic
from apps.members.models import AccessRole

pytestmark = pytest.mark.django_db

URL = "/api/v1/owner/companies/{}/knowledge/topics/"


def holder(company, member, *codes):
    """A member whose role holds the dashboard and `codes`."""
    role = AccessRole.objects.create(
        company=company,
        name=f"Role {'+'.join(codes) or 'reader'}",
        permissions=["dashboard.access", *codes],
    )
    return member(company, role.name)


def test_names_are_unique_among_live_topics(company):
    first = topics.create_topic(company, by=None, name="  Sovuq   zanjir ", color="sky")
    assert first.name == "Sovuq zanjir"
    with pytest.raises(DomainError):
        topics.create_topic(company, by=None, name="sovuq zanjir")
    topics.archive_topic(first, by=None)
    again = topics.create_topic(company, by=None, name="Sovuq zanjir")  # the old one is archived
    assert again.pk != first.pk
    with pytest.raises(DomainError):
        topics.restore_topic(first, by=None)  # its name is taken again


def test_colours_are_palette_keys(company):
    with pytest.raises(DomainError):
        topics.create_topic(company, by=None, name="Kassa", color="#ff0000")


def test_only_knowledge_or_learning_managers_change_them(company, member):
    reader = holder(company, member)
    with pytest.raises(PermissionDenied):
        topics.create_topic(company, by=reader, name="Kassa")
    for code in ("knowledge.manage", "learning.manage"):
        manager = holder(company, member, code)
        assert topics.create_topic(company, by=manager, name=f"Kassa {code}").pk


def test_pharmacy_topics_once_in_the_company_language(company):
    company.default_language = "uz"
    company.save()
    made = topics.add_pharmacy_topics(company, by=None)
    assert len(made) == len(topics.PHARMACY_TOPICS)
    assert topics.add_pharmacy_topics(company, by=None) == []
    assert Topic.objects.filter(company=company).count() == len(topics.PHARMACY_TOPICS)


def test_live_ids_refuses_other_companies(company, other_company):
    mine = topics.create_topic(company, by=None, name="Kassa")
    theirs = topics.create_topic(other_company, by=None, name="Kassa")
    assert topics.live_ids(company.pk, [mine.pk, mine.pk]) == [mine.pk]
    with pytest.raises(DomainError):
        topics.live_ids(company.pk, [theirs.pk])


def test_the_endpoint(company, other_company, member, owner_api):
    manager = holder(company, member, "learning.manage")
    reader = holder(company, member)
    api = owner_api(manager)
    made = api.post(URL.format(company.pk), {"name": "Retseptli dorilar", "color": "violet"})
    assert made.status_code == 201, made.content
    assert made.json()["question_count"] == 0
    assert owner_api(reader).get(URL.format(company.pk)).json()[0]["name"] == "Retseptli dorilar"
    assert owner_api(reader).post(URL.format(company.pk), {"name": "X"}).status_code == 403
    other = topics.create_topic(other_company, by=None, name="Boshqa")
    assert api.post(f"{URL.format(company.pk)}{other.pk}/archive/").status_code == 404
    assert api.post(f"{URL.format(company.pk)}pharmacy/").status_code == 201
