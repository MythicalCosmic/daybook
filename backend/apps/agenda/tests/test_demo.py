"""The calendar demo, through the root `demo_people` fixture."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.agenda import demo, queries
from apps.agenda.models import Event, EventAttendee

pytestmark = pytest.mark.django_db


def test_demo_fills_the_next_weeks(company, demo_people):
    people = demo_people(company)
    now = timezone.now()

    demo.seed(company, people, now)

    assert Event.objects.filter(company=company).count() >= 8
    assert Event.objects.filter(company=company, cancelled_at__isnull=False).count() == 1
    assert Event.objects.filter(company=company, repeat="weekly").exists()
    assert EventAttendee.objects.filter(company=company, response="going").count() >= 10
    assert EventAttendee.objects.filter(company=company, response="declined").exists()
    today = queries.local_day(now, company)
    items = queries.calendar_items(company, today, today + timedelta(days=14), people["owner"])
    assert len(items) >= 5
    # The supplier meeting is private: the courier doesn't see it.
    courier = {
        item.title
        for item in queries.calendar_items(
            company, today, today + timedelta(days=14), people["nigora"]
        )
    }
    assert not any("Coca-Cola" in title for title in courier)
