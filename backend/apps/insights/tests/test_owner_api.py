"""Owner endpoints (rule 21): company scope (404), permissions (403), hidden fields, branch and
domain isolation, audit and pulse on every change."""

import pytest
from django.core.cache import cache

from apps.audit.models import AuditLog
from apps.console import pulse
from apps.insights.models import Insight, InsightSettings
from apps.insights.tests.factories import InsightFactory
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def fresh_cache():
    cache.clear()


def url(company, path: str) -> str:
    return f"/api/v1/owner/companies/{company.pk}/{path}"


@pytest.fixture
def insight(shop, branches):
    return InsightFactory(company=shop, branch=branches[0])


# The cockpit ----------------------------------------------------------------------------------


def test_cockpit_for_the_owner(shop, owner, owner_api, branches):
    response = owner_api(owner).get(url(shop, "cockpit/"))
    assert response.status_code == 200, response.content
    data = response.json()
    assert {"today", "currency", "can", "money", "cash", "decisions", "insights"} <= set(data)
    assert [row["name"] for row in data["money"]["branches"]] == ["Chilonzor", "Yunusobod"]
    assert isinstance(data["cash"]["now"], str)  # money as strings


def test_cockpit_without_finance_view_hides_money(shop, manager, owner_api):
    data = owner_api(manager).get(url(shop, "cockpit/")).json()
    assert "money" not in data and "cash" not in data
    assert "profit" not in str(data)


def test_cockpit_needs_finance_or_reports(shop, member, owner_api, role):
    from apps.members.permissions import Perm

    clerk = member.registered(shop, "Employee")
    clerk.role = role(shop, "Clerk", [Perm.DASHBOARD_ACCESS, Perm.TASKS_VIEW_ALL])
    clerk.save(update_fields=["role"])
    assert owner_api(clerk).get(url(shop, "cockpit/")).status_code == 403


def test_another_companys_cockpit_is_404(shop, owner, other_company, owner_api):
    assert owner_api(owner).get(url(other_company, "cockpit/")).status_code == 404


# The list -------------------------------------------------------------------------------------


def test_list_and_filters(shop, owner, owner_api, insight, branches):
    InsightFactory(company=shop, kind=Insight.Kind.CASH_LOW, severity="critical")
    InsightFactory(company=shop, status=Insight.Status.RESOLVED)
    client = owner_api(owner)
    data = client.get(url(shop, "insights/")).json()
    assert data["count"] == 2  # live only
    assert data["results"][0]["severity"] == "critical"  # urgent first
    assert client.get(url(shop, "insights/?status=all")).json()["count"] == 3
    assert client.get(url(shop, "insights/?severity=warning")).json()["count"] == 1
    assert client.get(url(shop, f"insights/?branch={branches[0].pk}")).json()["count"] == 1
    assert client.get(url(shop, "insights/?kind=nonsense")).status_code == 400


def test_the_list_needs_reports_view(shop, member, owner_api, role, insight):
    from apps.members.permissions import Perm

    bookkeeper = member.registered(shop, "Employee")
    bookkeeper.role = role(shop, "Bookkeeper", [Perm.DASHBOARD_ACCESS, Perm.FINANCE_VIEW])
    bookkeeper.save(update_fields=["role"])
    assert owner_api(bookkeeper).get(url(shop, "insights/")).status_code == 403


def test_finance_insights_hidden_without_finance_view(shop, manager, owner_api, insight):
    # The manager reads reports, not money: a finance insight answers 404 for them.
    client = owner_api(manager)
    assert client.get(url(shop, "insights/")).json()["count"] == 0
    assert client.get(url(shop, f"insights/{insight.pk}/")).status_code == 404
    assert client.post(url(shop, f"insights/{insight.pk}/acknowledge/")).status_code == 404


def test_payroll_insights_need_payroll_view(shop, branch_accountant, owner_api):
    staff = InsightFactory(company=shop, kind=Insight.Kind.STAFF_COST, domain="payroll")
    client = owner_api(branch_accountant)
    assert client.get(url(shop, f"insights/{staff.pk}/")).status_code == 404


def test_branch_isolation(shop, branch_accountant, owner_api, branches):
    theirs = InsightFactory(company=shop, branch=branches[1])
    company_wide = InsightFactory(company=shop, branch=None)
    mine = InsightFactory(company=shop, branch=branches[0])
    client = owner_api(branch_accountant)
    assert [row["id"] for row in client.get(url(shop, "insights/")).json()["results"]] == [mine.pk]
    assert client.get(url(shop, f"insights/{theirs.pk}/")).status_code == 404
    assert client.get(url(shop, f"insights/{company_wide.pk}/")).status_code == 404


def test_another_companys_insight_is_404(shop, owner, owner_api, other_company):
    foreign = InsightFactory(company=other_company)
    client = owner_api(owner)
    assert client.get(url(shop, f"insights/{foreign.pk}/")).status_code == 404
    assert client.post(url(shop, f"insights/{foreign.pk}/dismiss/")).status_code == 404


def test_the_detail_shape(shop, owner, owner_api, insight):
    data = owner_api(owner).get(url(shop, f"insights/{insight.pk}/")).json()
    assert data["branch"] == {"id": insight.branch_id, "name": "Chilonzor"}
    assert data["metrics"]["value"] == "4000000.00"
    assert data["title"].startswith("Supplier bills overdue")
    assert "Tolzor Farm" in data["explanation"]
    assert data["suggested_action"]


# Acting on one --------------------------------------------------------------------------------


def versions(company):
    return pulse.versions(company.pk, ["insights.open"])["insights.open"]


def test_acknowledge(shop, owner, owner_api, insight, django_capture_on_commit_callbacks):
    before = versions(shop)
    with django_capture_on_commit_callbacks(execute=True):
        response = owner_api(owner).post(url(shop, f"insights/{insight.pk}/acknowledge/"))
    assert response.status_code == 200
    assert response.json()["status"] == "acknowledged"
    insight.refresh_from_db()
    assert insight.acknowledged_by == owner.user
    assert AuditLog.objects.filter(action="insights.acknowledged", target_id=insight.pk).exists()
    assert versions(shop) != before


def test_dismiss_with_a_reason(shop, owner, owner_api, insight):
    response = owner_api(owner).post(
        url(shop, f"insights/{insight.pk}/dismiss/"), {"reason": "Agreed"}, format="json"
    )
    assert response.status_code == 200
    insight.refresh_from_db()
    assert insight.status == Insight.Status.DISMISSED
    assert insight.dismissed_reason == "Agreed"
    log = AuditLog.objects.get(action="insights.dismissed", target_id=insight.pk)
    assert log.details["reason"] == "Agreed"
    # Not live any more: acting on it again is refused.
    again = owner_api(owner).post(url(shop, f"insights/{insight.pk}/resolve/"))
    assert again.status_code == 400


def test_resolve(shop, owner, owner_api, insight):
    response = owner_api(owner).post(url(shop, f"insights/{insight.pk}/resolve/"))
    assert response.status_code == 200
    insight.refresh_from_db()
    assert insight.status == Insight.Status.RESOLVED
    assert insight.resolved_at is not None
    assert AuditLog.objects.filter(action="insights.resolved", target_id=insight.pk).exists()


def test_make_it_a_task(shop, owner, owner_api, insight):
    response = owner_api(owner).post(
        url(shop, f"insights/{insight.pk}/make-task/"),
        {"due_on": "2026-12-01", "title": "Call Tolzor Farm"},
        format="json",
    )
    assert response.status_code == 200, response.content
    data = response.json()
    task = Task.objects.get(pk=data["task"]["id"])
    assert task.title == "Call Tolzor Farm"
    assert task.assignee == owner
    assert task.due_at.date().isoformat() == "2026-12-01"
    assert data["insight"]["status"] == "acknowledged"
    assert data["insight"]["task"]["id"] == task.pk
    second = owner_api(owner).post(url(shop, f"insights/{insight.pk}/make-task/"))
    assert second.status_code == 400  # one open task per insight


def test_make_it_a_task_for_someone_unseen(shop, branch_accountant, owner_api, insight, member):
    from apps.companies.models import Branch

    elsewhere = Branch.objects.get(company=shop, name="Yunusobod")
    stranger = member.registered(shop, "Pharmacist")
    stranger.branches.set([elsewhere])
    response = owner_api(branch_accountant).post(
        url(shop, f"insights/{insight.pk}/make-task/"),
        {"assignee_id": stranger.pk},
        format="json",
    )
    assert response.status_code == 400


# Settings and "Check now" ---------------------------------------------------------------------


def test_settings(shop, owner, owner_api):
    client = owner_api(owner)
    data = client.get(url(shop, "insights/settings/")).json()
    assert data["sensitivity"] == "normal"
    assert data["quiet_from"] == "22:00"
    assert {kind["kind"] for kind in data["kinds"]} == set(Insight.Kind.values)
    response = client.patch(
        url(shop, "insights/settings/"),
        {"min_cash_buffer": "150000000.00", "disabled_kinds": ["staff_cost"], "quiet_to": "07:30"},
        format="json",
    )
    assert response.status_code == 200, response.content
    row = InsightSettings.objects.get(company=shop)
    assert str(row.min_cash_buffer) == "150000000.00"
    assert row.disabled_kinds == ["staff_cost"]
    assert row.quiet_to.strftime("%H:%M") == "07:30"
    log = AuditLog.objects.get(action="insights.settings_changed")
    assert log.details["changes"]["disabled_kinds"] == [[], ["staff_cost"]]
    bad = client.patch(url(shop, "insights/settings/"), {"disabled_kinds": ["x"]}, format="json")
    assert bad.status_code == 400


def test_settings_need_company_settings(shop, branch_accountant, owner_api):
    assert owner_api(branch_accountant).get(url(shop, "insights/settings/")).status_code == 403


def test_check_now_once_a_minute(shop, owner, owner_api):
    client = owner_api(owner)
    response = client.post(url(shop, "insights/check/"))
    assert response.status_code == 200, response.content
    assert set(response.json()) == {
        "created",
        "updated",
        "reopened",
        "resolved",
        "failed",
        "notified",
    }
    assert client.post(url(shop, "insights/check/")).status_code == 429
    assert AuditLog.objects.filter(action="insights.checked").count() == 1
