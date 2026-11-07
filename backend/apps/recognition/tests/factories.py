"""factory_boy factories for the models of recognition."""

import factory
from django.utils import timezone

from apps.members.tests.factories import MembershipFactory
from apps.recognition.models import BadgeAward, Kudos, PointsEntry, Streak


class PointsEntryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PointsEntry

    membership = factory.SubFactory(MembershipFactory)
    company = factory.SelfAttribute("membership.company")
    points = 10
    reason = PointsEntry.Reason.LESSON
    key = factory.Sequence(lambda n: f"test:{n}")
    at = factory.LazyFunction(timezone.now)


class BadgeAwardFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BadgeAward

    membership = factory.SubFactory(MembershipFactory)
    company = factory.SelfAttribute("membership.company")
    badge = "first_lesson"
    awarded_at = factory.LazyFunction(timezone.now)


class StreakFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Streak

    membership = factory.SubFactory(MembershipFactory)
    company = factory.SelfAttribute("membership.company")


class KudosFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Kudos

    from_member = factory.SubFactory(MembershipFactory)
    company = factory.SelfAttribute("from_member.company")
    to_member = factory.SubFactory(
        MembershipFactory, company=factory.SelfAttribute("..from_member.company")
    )
