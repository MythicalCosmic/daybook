"""factory_boy factories for the models of the owner console."""

import factory
from factory.django import DjangoModelFactory

from apps.console.models import SavedView
from apps.members.tests.factories import MembershipFactory


class SavedViewFactory(DjangoModelFactory):
    class Meta:
        model = SavedView

    membership = factory.SubFactory(MembershipFactory)
    company = factory.SelfAttribute("membership.company")
    module = "tasks"
    name = factory.Sequence(lambda n: f"View {n}")
    state = factory.LazyFunction(lambda: {"filters": {"status": "todo"}})
