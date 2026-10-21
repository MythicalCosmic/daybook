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
    assert EventAttendee.objects.filter(company=company, response="going").count() >= 8
    assert EventAttendee.objects.filter(company=company, response="declined").exists()
    today = queries.local_day(now, company)
    items = queries.calendar_items(company, today, today + timedelta(days=14), people["owner"])
    assert len(items) >= 5
    # The distributor meeting is private: the courier doesn't see it.
    courier = {
        item.title
        for item in queries.calendar_items(
            company, today, today + timedelta(days=14), people["jasur"]
        )
    }
    assert not any("Distribyutor" in title for title in courier)
    # Nobody away that day is invited (Madina is on leave today and tomorrow).
    madina_days = {today, today + timedelta(days=1)}
    invites = EventAttendee.objects.filter(membership=people["madina"]).select_related("event")
    for invite in invites:
        assert timezone.localtime(invite.event.start).date() not in madina_days
