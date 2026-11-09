"""The managers' summary of the day, at the evening report time (jobs.evening_summaries)."""

import pytest

from apps.attendance import jobs, services
from apps.attendance.tests.conftest import DAY, local
from apps.attendance.tests.factories import shift_at
from apps.inbox.models import Notification

pytestmark = pytest.mark.django_db


@pytest.fixture
def day(staff, freeze, chilonzor, yunusobod):
    """Ali on time, Vali 25 minutes late and still in, Bob absent, Sara (Yunusobod) on time."""
    services.update_settings(staff.ali.company, by=None, require_location=False)
    for person, branch in ((staff.ali, chilonzor), (staff.vali, chilonzor), (staff.bob, chilonzor)):
        shift_at(person, DAY, branch=branch)
    shift_at(staff.sara, DAY, branch=yunusobod)
    freeze(local(DAY, 8, 55))
    services.check_in(staff.ali)
    services.check_in(staff.sara)
    freeze(local(DAY, 9, 25))
    services.check_in(staff.vali)
    freeze(local(DAY, 18, 5))
    services.check_out(staff.ali)
    services.check_out(staff.sara)
    return staff


def test_the_summary_goes_once_at_the_evening_report_time(
    day, freeze, django_capture_on_commit_callbacks
):
    company = day.ali.company
    assert jobs.summarise_company(company, local(DAY, 19, 0)) == 0  # not yet
    with django_capture_on_commit_callbacks(execute=True):
        assert jobs.summarise_company(company, local(DAY, 20, 5)) >= 2
        assert jobs.summarise_company(company, local(DAY, 20, 15)) == 0  # once a day
    manager = Notification.objects.get(kind="attendance.summary", recipient=day.manager)
    assert manager.title == "Attendance today: 3 of 4 came"
    assert "On time: 2" in manager.body
    assert "Late: Vali (25 min)" in manager.body
    assert "Absent without leave: Bob" in manager.body
    assert "Still in: 1" in manager.body
    # The Chilonzor lead hears about Chilonzor only.
    lead = Notification.objects.get(kind="attendance.summary", recipient=day.lead)
    assert lead.title == "Attendance today: 2 of 3 came"
    assert not Notification.objects.filter(kind="attendance.summary", recipient=day.ali).exists()


def test_a_day_nobody_worked_sends_nothing(staff, freeze):
    company = staff.ali.company
    assert jobs.summarise_company(company, local(DAY, 20, 5)) == 0
    assert not Notification.objects.filter(kind="attendance.summary").exists()
