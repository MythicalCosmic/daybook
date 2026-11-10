"""factory_boy factories for the models of insights."""

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.companies.tests.factories import CompanyFactory
from apps.insights.models import Insight


class InsightFactory(DjangoModelFactory):
    """An open warning that a supplier bill is late (finance), unless told otherwise."""

    class Meta:
        model = Insight

    company = factory.SubFactory(CompanyFactory)
    kind = Insight.Kind.OVERDUE_PAYABLES
    domain = Insight.Domain.FINANCE
    severity = Insight.Severity.WARNING
    status = Insight.Status.OPEN
    dedupe_key = factory.Sequence(lambda n: f"test:{n}")
    metrics = factory.LazyFunction(
        lambda: {
            "value": "4000000.00",
            "baseline": "9000000.00",
            "unit": "money",
            "currency": "UZS",
            "count": 2,
            "oldest_days": 3,
            "parties": [{"name": "Tolzor Farm", "amount": "4000000.00", "days": 3}],
        }
    )
    title = "Supplier bills overdue"
    detected_at = factory.LazyFunction(timezone.now)
    last_seen_at = factory.LazyFunction(timezone.now)
