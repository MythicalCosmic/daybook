"""The demo: Demo Dorixona's Chilonzor terminal and this morning's scans."""

import pytest
from django.utils import timezone

from apps.attendance import demo as attendance_demo
from apps.attendance.models import AttendanceRecord
from apps.companies.models import Feature
from apps.core.management.commands.ensure_company_defaults import ensure_company_defaults
from apps.core.management.commands.seed_demo import Command
from apps.faceid import demo
from apps.faceid.models import FaceDevice, FaceEvent, FaceLink
from apps.faceid.tests.conftest import DAY, local
from apps.timeoff import demo as timeoff_demo

pytestmark = pytest.mark.django_db


@pytest.fixture
def pharmacy(freeze):
    freeze(local(DAY, 14, 0))
    now = timezone.now()
    company, people = Command()._build_pharmacy(now)
    company.features = list(Feature.values)
    company.save()
    ensure_company_defaults(company)
    timeoff_demo.seed(company, people, now)
    attendance_demo.seed(company, people, now)
    demo.seed(company, people, now)
    return company, people


def test_the_chilonzor_terminal_and_its_morning(pharmacy):
    company, _people = pharmacy
    device = FaceDevice.objects.get(company=company)
    assert (device.name, device.model, device.branch.code) == (
        "Chilonzor kirish",
        "DS-K1T341AMF",
        "CHL",
    )
    assert device.last_event_at and device.last_seen_at
    links = FaceLink.objects.filter(company=company)
    assert links.count() >= 3 and all(len(link.employee_no) == 8 for link in links)
    events = FaceEvent.objects.filter(company=company)
    actions = set(events.values_list("action", flat=True))
    assert {"checked_in", "repeat", "not_linked", "stranger"} <= actions
    assert all(event.photo for event in events)
    unlinked = events.filter(action="not_linked")
    assert set(unlinked.values_list("employee_no", flat=True)) == {"00000037"}
    assert not FaceLink.objects.filter(company=company, number_key="37").exists()
    # Every check-in at Chilonzor today came from the terminal, without a location.
    today = AttendanceRecord.objects.filter(company=company, date=DAY, branch=device.branch)
    assert today.exists()
    assert set(today.values_list("in_source", flat=True)) == {"face"}
    assert not today.filter(in_lat__isnull=False).exists()
    for event in events.filter(action="checked_in"):
        assert AttendanceRecord.objects.get(pk=event.record_id).membership_id == event.membership_id
    # Each person's first scan of the day is an arrival (what "who came" would have sent).
    assert events.filter(flags__contains=["arrival"]).count() >= 3
