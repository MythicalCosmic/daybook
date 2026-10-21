"""factory_boy factories for the models of the knowledge base."""

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.companies.tests.factories import CompanyFactory
from apps.knowledge import sanitize
from apps.knowledge.models import Page, PageAck, Space


class SpaceFactory(DjangoModelFactory):
    class Meta:
        model = Space
        skip_postgeneration_save = True

    company = factory.SubFactory(CompanyFactory)
    name = factory.Sequence(lambda n: f"Space {n}")
    icon = "📘"
    audience_all = True

    @factory.post_generation
    def positions(self, create, extracted, **kwargs):
        if create and extracted:
            self.positions.set(extracted)


class PageFactory(DjangoModelFactory):
    """A published page with a body (`published=False` for a draft)."""

    class Meta:
        model = Page

    space = factory.SubFactory(SpaceFactory)
    company = factory.SelfAttribute("space.company")
    title = factory.Sequence(lambda n: f"Page {n}")
    body = "<p>How we open the till: count the float, then open the shift.</p>"
    body_text = factory.LazyAttribute(lambda page: sanitize.to_text(page.body))
    published = True
    published_at = factory.LazyFunction(timezone.now)
    ack_since = factory.LazyAttribute(lambda page: page.published_at)


class PageAckFactory(DjangoModelFactory):
    class Meta:
        model = PageAck

    page = factory.SubFactory(PageFactory)
    company = factory.SelfAttribute("page.company")
    version = factory.SelfAttribute("page.version")
    at = factory.LazyFunction(timezone.now)
