"""Test helpers of Davomat. People are made through the services (`tests/conftest.py`'s `Org`
helpers), the way the endpoints make them; only the link codes have a factory."""

from datetime import timedelta

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.davomat.models import TelegramLink


class TelegramLinkFactory(DjangoModelFactory):
    class Meta:
        model = TelegramLink

    code_hash = factory.Sequence(lambda n: f"{n:064x}")
    expires_at = factory.LazyFunction(lambda: timezone.now() + timedelta(hours=24))
