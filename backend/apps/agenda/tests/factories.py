"""factory_boy factories for the models of the company calendar."""

from datetime import timedelta

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.agenda.models import Event, EventAttendee
from apps.companies.tests.factories import CompanyFactory


class EventFactory(DjangoModelFactory):
    """A one-hour meeting tomorrow, open to the whole company."""

    class Meta:
        model = Event

    company = factory.SubFactory(CompanyFactory)
    title = factory.Sequence(lambda n: f"Meeting {n}")
    start = factory.LazyFunction(lambda: timezone.now() + timedelta(days=1))
    end = factory.LazyAttribute(lambda event: event.start + timedelta(hours=1))
    remind_before = 60


class AttendeeFactory(DjangoModelFactory):
    class Meta:
        model = EventAttendee

    event = factory.SubFactory(EventFactory)
    company = factory.SelfAttribute("event.company")
