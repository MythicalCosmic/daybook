import factory
from factory.django import DjangoModelFactory

from apps.companies.tests.factories import CompanyFactory
from apps.groups.models import DEFAULT_EVENTS, TelegramGroup


class TelegramGroupFactory(DjangoModelFactory):
    class Meta:
        model = TelegramGroup

    company = factory.SubFactory(CompanyFactory)
    chat_id = factory.Sequence(lambda n: -1_001_000_000_000 - n)
    title = factory.Sequence(lambda n: f"Team chat {n}")
    events = factory.LazyFunction(lambda: list(DEFAULT_EVENTS))
