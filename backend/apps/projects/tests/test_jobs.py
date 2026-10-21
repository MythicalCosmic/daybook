"""The health watch, missed milestones and the weekly nudge (`apps.projects.jobs`)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.inbox import services as inbox
from apps.inbox.models import Notification
from apps.projects import jobs, services
from apps.projects.models import Milestone, Project, ProjectUpdate
from apps.projects.tests.factories import project, team

pytestmark = pytest.mark.django_db


@pytest.fixture
def people(company, member):
    return team(company, member)


def test_a_project_going_off_track_is_told_once(company, people):
    today = timezone.localdate()
    reno = project(
        company,
        people["owner"],
        lead=people["manager"],
        status="active",
        due_on=today + timedelta(days=30),
    )
    services.create_milestone(
        reno, by=people["owner"], name="Fit-out", due_on=today - timedelta(days=2)
    )

    sent = jobs.watch_health()
    again = jobs.watch_health()

    notes = Notification.objects.filter(kind="projects.off_track")
    assert sent >= 1 and again == 0
    assert {n.recipient_id for n in notes} >= {people["manager"].pk, people["owner"].pk}
    assert all(reno.key in n.title for n in notes)
    reno.refresh_from_db()
    assert reno.health == "off_track"


def test_a_missed_milestone_is_told_once(company, people):
    today = timezone.localdate()
    reno = project(company, people["owner"], lead=people["manager"], status="active")
    services.create_milestone(
        reno, by=people["owner"], name="Fit-out", due_on=today - timedelta(days=1)
    )
    services.create_milestone(
        reno, by=people["owner"], name="Later", due_on=today + timedelta(days=3)
    )

    jobs.watch_health()
    jobs.watch_health()

    notes = Notification.objects.filter(kind="projects.milestone_missed")
    assert notes.filter(recipient=people["manager"]).count() == 1
    assert "Fit-out" in notes.first().title
    assert Milestone.objects.get(name="Fit-out").missed_notified_at is not None
    assert Milestone.objects.get(name="Later").missed_notified_at is None


def test_finished_projects_are_left_alone(company, people):
    today = timezone.localdate()
    reno = project(company, people["owner"], status="completed", due_on=today - timedelta(days=9))
    services.create_milestone(
        reno, by=people["owner"], name="Old", due_on=today - timedelta(days=20)
    )

    assert jobs.watch_health() == 0


def local(company, day_offset_to_monday=0, hour=11):
    tz = ZoneInfo(company.timezone)
    today = timezone.localtime(timezone.now(), tz).date()
    monday = today - timedelta(days=today.weekday()) + timedelta(days=day_offset_to_monday)
    return datetime(monday.year, monday.month, monday.day, hour, 0, tzinfo=tz)


def test_leads_are_nudged_on_the_nudge_day_after_ten_once(company, people):
    reno = project(company, people["owner"], lead=people["manager"], status="active")
    quiet = project(company, people["owner"], name="Quiet", lead=people["aziz"], status="active")
    ProjectUpdate.objects.create(
        project=quiet, author=people["aziz"], health="on_track", text="Fine"
    )

    assert jobs.nudge_leads(local(company, hour=9)) == 0  # too early
    assert jobs.nudge_leads(local(company, day_offset_to_monday=1)) == 0  # Tuesday
    assert jobs.nudge_leads(local(company)) == 1
    assert jobs.nudge_leads(local(company, hour=15)) == 0  # once a day

    note = Notification.objects.get(kind="projects.update_nudge")
    assert note.recipient == people["manager"] and reno.key in note.title
    assert [action["key"] for action in note.actions] == ["on_track", "at_risk", "off_track"]


def test_the_nudge_can_be_switched_off(company, people):
    project(company, people["owner"], lead=people["manager"], status="active")
    services.update_settings(company, by=people["owner"], weekly_nudge=False)
    assert jobs.nudge_leads(local(company)) == 0


def test_one_tap_on_the_nudge_posts_the_update(company, people):
    reno = project(company, people["owner"], lead=people["manager"], status="active")
    jobs.nudge_leads(local(company))
    note = Notification.objects.get(kind="projects.update_nudge")

    message = inbox.run_action(note.pk, "at_risk", by=people["manager"])

    update = ProjectUpdate.objects.get(project=reno)
    assert update.health == "at_risk" and update.author == people["manager"]
    assert "At risk" in message
    assert Project.objects.get(pk=reno.pk).update_nudged_on is not None
