"""Team reports from the owner console (docs/PLAN-OWNER.md §4.5): the analytics shape, groupings,
comparison, branch scope, permissions, the exporter and the AI tools."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.ai.tools.testing import call_tool
from apps.exports.registry import get_exporter
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory, TaskTemplateFactory, make_shop

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop(company, member):
    return make_shop(company, member)


@pytest.fixture
def history(shop):
    tz = ZoneInfo(shop.company.timezone)
    today = timezone.localdate(timezone=tz)
    routine = TaskTemplateFactory(
        company=shop.company, title="Close the till", assignees=[shop.worker]
    )
    for days_ago in range(1, 6):
        due = datetime.combine(today - timedelta(days=days_ago), time(10), tzinfo=tz)
        TaskFactory(
            assignee=shop.worker,
            created_by=shop.owner,
            kind=Task.Kind.DAILY,
            template=routine,
            branch=shop.here,
            due_at=due,
            status=Task.Status.DONE,
            completed_at=due - timedelta(minutes=10) if days_ago % 2 else due + timedelta(hours=1),
        )
        TaskFactory(
            assignee=shop.colleague,
            created_by=shop.owner,
            branch=shop.there,
            due_at=due,
            status=Task.Status.DONE,
            completed_at=due - timedelta(minutes=5),
        )
    return routine


def url(company, path):
    return f"/api/v1/owner/companies/{company.pk}/reports/{path}"


def test_team_report_in_the_analytics_shape(shop, history, owner_api):
    body = (
        owner_api(shop.owner)
        .get(url(shop.company, "team/"), {"preset": "last_30", "compare": "prev"})
        .json()
    )
    assert set(body) >= {"range", "compare", "totals", "previous", "series", "breakdown"}
    assert body["totals"]["total"] == 10 and body["totals"]["on_time"] == 8
    assert body["totals"]["on_time_percent"] == 80.0
    assert body["previous"]["total"] == 0
    assert len(body["series"]) == 30
    people = {row["member"]["id"]: row for row in body["breakdown"] if row.get("member")}
    assert people[shop.colleague.pk]["on_time_percent"] == 100.0


def test_groupings(shop, history, owner_api):
    client = owner_api(shop.owner)
    routines = client.get(
        url(shop.company, "team/"), {"preset": "last_30", "group_by": "routine"}
    ).json()["breakdown"]
    assert {row["label"] for row in routines} == {"Close the till", ""}
    branches = client.get(
        url(shop.company, "team/"), {"preset": "last_30", "group_by": "branch"}
    ).json()["breakdown"]
    assert {row["label"]: row["total"] for row in branches} == {shop.here.name: 5, "Yunusobod": 5}
    assert client.get(url(shop.company, "team/"), {"group_by": "galaxy"}).status_code == 400
    assert client.get(url(shop.company, "team/"), {"preset": "forever"}).status_code == 400


def test_branch_scope_and_the_branch_filter(shop, history, owner_api):
    lead = owner_api(shop.lead).get(url(shop.company, "team/"), {"preset": "last_30"}).json()
    assert lead["totals"]["total"] == 5
    assert all(row["member"]["id"] != shop.colleague.pk for row in lead["breakdown"])
    widened = (
        owner_api(shop.lead)
        .get(url(shop.company, "team/"), {"preset": "last_30", "branch": shop.there.pk})
        .json()
    )
    assert widened["totals"]["total"] == 0  # a filter only narrows
    narrowed = (
        owner_api(shop.owner)
        .get(url(shop.company, "team/"), {"preset": "last_30", "branch": shop.there.pk})
        .json()
    )
    assert narrowed["totals"]["total"] == 5


def test_the_mini_app_team_stats_follow_branch_scope_too(shop, history, api_as):
    body = (
        api_as(shop.lead)
        .get(f"/api/v1/companies/{shop.company.pk}/team-stats/", {"period": "month"})
        .json()
    )
    assert shop.colleague.pk not in {row["member"]["id"] for row in body["members"]}


def test_routine_report(shop, history, owner_api):
    TaskTemplateFactory(company=shop.company, title="Idle routine", assignees=[shop.worker])
    body = (
        owner_api(shop.owner)
        .get(url(shop.company, "routines/"), {"preset": "last_30", "compare": "prev"})
        .json()
    )
    rows = {row["label"]: row for row in body["breakdown"]}
    assert rows["Close the till"]["made"] == 5 and rows["Close the till"]["on_time"] == 3
    assert rows["Idle routine"]["made"] == 0
    assert body["totals"]["idle"] == 1


def test_reports_need_reports_view_and_stay_in_the_company(shop, owner_api, member, other_company):
    from apps.members.models import AccessRole

    AccessRole.objects.create(company=shop.company, name="Viewer", permissions=["dashboard.access"])
    viewer = member.registered(shop.company, "Viewer")
    assert owner_api(viewer).get(url(shop.company, "team/")).status_code == 403
    assert owner_api(shop.owner).get(url(other_company, "team/")).status_code == 404


def test_the_exporter_and_ai_tools(shop, history):
    rows = list(get_exporter("reports.team").rows(shop.lead, {"preset": "last_30"}))
    # People sharing the lead's branch: the lead, the worker, and the owner and manager who
    # work at both branches; never the colleague from the other branch.
    expected = {str(person) for person in (shop.owner, shop.manager, shop.lead, shop.worker)}
    assert {row["label"] for row in rows} == expected
    today = timezone.localdate(timezone=ZoneInfo(shop.company.timezone))
    start, end = (today - timedelta(days=10)).isoformat(), today.isoformat()
    performance = call_tool("reports_team_performance", shop.owner, start=start, end=end)
    assert performance["data"]["totals"]["total"] == 10
    scoped = call_tool("reports_team_performance", shop.lead, start=start, end=end)
    assert scoped["data"]["totals"]["total"] == 5
    trends = call_tool("reports_task_trends", shop.owner, start=start, end=end, group_by="week")
    assert trends["rows"] and all("id" in row for row in trends["rows"])
    compliance = call_tool("reports_routine_compliance", shop.owner, start=start, end=end)
    assert compliance["rows"][0]["title"] == "Close the till"
    assert call_tool("reports_team_performance", shop.worker, start=start, end=end) == {
        "error": "not_allowed"
    }
    assert (
        call_tool("reports_task_trends", shop.owner, start=end, end=start)["error"]
        == "invalid_input"
    )
