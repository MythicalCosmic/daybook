"""The insights demo runs on a pharmacy's demo people and stores what the rules find."""

from datetime import date

import pytest
from django.utils import timezone

from apps.finance import conf as finance_conf
from apps.finance import defaults as finance_defaults
from apps.insights import demo
from apps.insights.models import Insight

pytestmark = pytest.mark.django_db


def test_the_demo_seeds_and_finishes(company, demo_people):
    company.features = ["finance"]
    company.save(update_fields=["features"])
    finance_defaults.ensure(company)
    people = demo_people(company)
    now = timezone.now()
    demo.seed(company, people, now)
    demo.finish(company, people, now)
    assert str(finance_conf.get_settings(company).cash_buffer) == "150000000.00"
    # Without the other demos' books the cash is under the buffer at once.
    assert Insight.objects.filter(company=company, kind=Insight.Kind.CASH_LOW).exists()


def test_the_demo_without_finance(company, demo_people):
    company.features = []
    company.save(update_fields=["features"])
    people = demo_people(company)
    demo.seed(company, people, timezone.now())
    demo.finish(company, people, timezone.now())
    assert not Insight.objects.filter(company=company).exists()


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 11, 10), date(2026, 11, 23)),
        (date(2026, 11, 21), date(2026, 11, 23)),
        (date(2026, 11, 22), date(2026, 12, 21)),  # next month's 23rd is past the 30 days
        (date(2026, 1, 30), date(2026, 2, 23)),
    ],
)
def test_the_low_point_lands_on_the_23rd(today, expected):
    assert demo.target_day(today) == expected
