"""The knowledge base demo, through the root `demo_people` fixture."""

import pytest
from django.utils import timezone

from apps.knowledge import demo, queries
from apps.knowledge.models import Page, PageAck, PageVersion, Space

pytestmark = pytest.mark.django_db


def test_demo_builds_a_lived_in_knowledge_base(company, demo_people):
    people = demo_people(company)

    demo.seed(company, people, timezone.now())

    spaces = list(Space.objects.filter(company=company).values_list("name", flat=True))
    assert spaces[0] == "Kompaniya qo‘llanmasi" and "Kassa" in spaces
    assert Page.objects.filter(company=company, published=True).count() >= 10
    assert Page.objects.filter(company=company, published=False).exists()  # a draft
    assert (
        PageVersion.objects.filter(company=company).count()
        > Page.objects.filter(company=company).count()
    )
    assert PageAck.objects.filter(company=company).count() >= 10
    # Madina read the till page before it changed: she has to read it again.
    madina = people["madina"]
    assert "Kassani ochish tartibi" in {page.title for page in queries.to_read(madina)}
    # The courier doesn't read the till space.
    assert "Kassani ochish tartibi" not in {
        page.title for page in queries.reader_pages(people["nigora"])
    }
