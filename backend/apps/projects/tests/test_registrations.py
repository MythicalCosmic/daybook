"""What projects registers: search, stream, calendar, file check, the time export, the task
visibility filter, the History target, the AI tools and the demo."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.ai.tools.testing import call_tool
from apps.console import registry
from apps.core import files
from apps.exports.registry import get_exporter
from apps.inbox.registry import get_kind
from apps.projects import providers, services
from apps.projects.models import Project, ProjectUpdate, TimeEntry
from apps.projects.tests.factories import card, project, team
from apps.tasks import visibility
from apps.tasks.tests.factories import jpeg

pytestmark = pytest.mark.django_db


@pytest.fixture
def people(company, member):
    return team(company, member)


def test_keys_are_registered_with_the_app_prefix():
    assert "projects.project" in registry.SEARCH
    assert "projects.updates" in registry.STREAM
    assert "projects.milestones" in registry.CALENDAR_SOURCES
    assert {"projects.projects", "projects.time"} <= set(registry.PULSE.keys())
    assert "projects.members" in visibility.registered_keys()
    assert get_exporter("projects.time") is not None
    for kind in (
        "projects.added",
        "projects.update_nudge",
        "projects.off_track",
        "projects.milestone_missed",
    ):
        assert get_kind(kind) is not None
    assert "projects.file" in files.registered_kinds()


def test_search_finds_visible_projects_only(company, people):
    reno = project(company, people["owner"], name="Chilonzor branch opening", key="OPEN")

    hits = providers.search(people["owner"], "chilonzor", 5)
    hidden = providers.search(people["madina"], "chilonzor", 5)

    assert [hit.id for hit in hits] == [reno.pk]
    assert hits[0].url == f"/c/{company.pk}/projects/{reno.pk}"
    assert hidden == []


def test_stream_shows_updates_and_milestones(company, people):
    reno = project(company, people["owner"])
    services.post_update(reno, by=people["owner"], health="on_track", text="Fine")
    launch = services.create_milestone(reno, by=people["owner"], name="Launch")
    services.update_milestone(launch, by=people["owner"], status="done")

    items = providers.stream(people["owner"], None, 10)

    assert {item.kind for item in items} == {"projects.update", "projects.milestone"}
    assert providers.stream(people["madina"], None, 10) == []


def test_calendar_has_milestones_of_visible_projects(company, people):
    reno = project(company, people["owner"], key="RENO")
    day = timezone.localdate() + timedelta(days=4)
    services.create_milestone(reno, by=people["owner"], name="Launch", due_on=day)

    items = providers.milestones_calendar(company, day - timedelta(days=1), day, people["owner"])

    assert [(i.title, i.start, i.all_day) for i in items] == [("RENO · Launch", day, True)]
    assert providers.milestones_calendar(company, day, day, people["madina"]) == []


def test_file_check_follows_the_project(company, people):
    reno = project(company, people["owner"])
    row = services.add_file(reno, by=people["owner"], upload=jpeg())

    assert providers.file_check(people["owner"].user, company.pk, row.pk) is True
    assert providers.file_check(people["madina"].user, company.pk, row.pk) is False


def test_time_export_rows(company, people):
    reno = project(company, people["owner"], key="RENO")
    services.log_time(
        people["owner"], day=timezone.localdate(), minutes=90, project=reno, note="Calls"
    )

    rows = list(providers.time_rows(people["owner"], {}))

    assert rows == [
        {
            "day": timezone.localdate(),
            "person": str(people["owner"]),
            "project": "RENO",
            "task": "",
            "minutes": 90,
            "hours": 1.5,
            "note": "Calls",
            "billable": False,
            "source": "Logged by hand",
        }
    ]
    assert list(providers.time_rows(people["madina"], {})) == []


def test_history_is_open_to_people_who_see_the_project(company, people):
    reno = project(company, people["owner"])
    assert providers.history_check(people["owner"], reno.pk) is True
    assert providers.history_check(people["madina"], reno.pk) is False


def test_ai_overview_and_detail(company, people):
    from apps.finance import defaults as finance_defaults

    finance_defaults.ensure(company)
    reno = project(company, people["owner"], key="RENO", status="active", budget="1000000")
    card(reno, people["owner"], assignee=people["aziz"])

    overview = call_tool("projects_overview", people["owner"])
    detail = call_tool("projects_detail", people["owner"], key="reno")
    hidden = call_tool("projects_detail", people["madina"], project_id=reno.pk)
    no_money = call_tool("projects_overview", people["owner"], _switches=frozenset())

    assert overview["rows"][0]["key"] == "RENO" and overview["rows"][0]["budget"] == "1000000.00"
    assert detail["data"]["progress"]["total"] == 1
    assert detail["data"]["money"]["budget"] == "1000000.00"
    assert hidden == {"error": "not_allowed"}  # employees have no dashboard
    assert "budget" not in no_money["rows"][0]


def test_the_demo(company, demo_people):
    from apps.finance import defaults as finance_defaults
    from apps.projects import demo

    finance_defaults.ensure(company)
    now = timezone.now()

    demo.seed(company, demo_people(company), now)

    projects = {p.key: p for p in Project.objects.filter(company=company)}
    assert set(projects) == {"OPEN", "WEB", "AUDIT", "PROMO"}
    opening = projects["OPEN"]
    assert opening.status == "active" and opening.health == "at_risk"
    assert opening.budget == Decimal("120000000.00")
    assert opening.tasks.count() == 30 and projects["WEB"].tasks.count() == 30
    assert projects["AUDIT"].tasks.count() == 30 and projects["AUDIT"].status == "planning"
    assert projects["WEB"].health == "on_track"
    assert opening.finance_transactions.filter(kind="expense").count() == 9
    assert TimeEntry.objects.filter(company=company).count() > 20
    assert ProjectUpdate.objects.filter(project=opening).count() == 3
    assert opening.files.count() == 1 and opening.links.count() == 3
