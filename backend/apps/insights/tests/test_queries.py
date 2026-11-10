"""The read contract other apps call: `open(company, *, branch_ids, …)` and
`open_for(company, branch_ids)` (the briefings' facts)."""

import pytest
from django.utils import translation

from apps.insights import queries
from apps.insights.models import Insight
from apps.insights.tests.factories import InsightFactory

pytestmark = pytest.mark.django_db


def test_open_for_gives_plain_dicts_in_scope(shop, branches):
    chilonzor, yunusobod = branches
    urgent = InsightFactory(
        company=shop, branch=chilonzor, kind=Insight.Kind.CASH_LOW, severity="critical"
    )
    other = InsightFactory(company=shop, branch=yunusobod)
    InsightFactory(company=shop, branch=chilonzor, status=Insight.Status.DISMISSED)
    everything = queries.open_for(shop, None)
    assert [row["id"] for row in everything] == [urgent.pk, other.pk]
    assert [row["id"] for row in queries.open_for(shop, [yunusobod.pk])] == [other.pk]
    assert queries.open_for(shop, []) == []
    row = everything[1]
    assert set(row) >= {"id", "kind", "domain", "severity", "status", "title", "metrics"}
    assert row["branch"] == {"id": yunusobod.pk, "name": "Yunusobod"}
    assert row["metrics"]["value"] == "4000000.00"
    assert isinstance(row["detected_at"], str)


def test_open_for_by_keyword_and_domains(shop, branches):
    InsightFactory(company=shop, kind=Insight.Kind.STAFF_COST, domain="payroll")
    assert queries.open_for(shop, branch_ids=None, domains=["finance"]) == []
    assert len(queries.open_for(shop, branch_ids=None, domains=["payroll"])) == 1


def test_open_for_writes_in_the_active_language(shop):
    InsightFactory(company=shop)
    with translation.override("en"):
        assert queries.open_for(shop, None)[0]["title"].startswith("Supplier bills overdue")


def test_open_with_filters(shop):
    InsightFactory(company=shop, severity="critical")
    InsightFactory(company=shop)
    assert queries.open(shop, branch_ids=None).count() == 2
    assert queries.open(shop, branch_ids=None, severity="critical").count() == 1
    assert queries.open(shop, branch_ids=None, domain="payroll").count() == 0


def test_a_module_switched_off_hides_its_insights(shop):
    InsightFactory(company=shop)
    shop.features = []
    shop.save(update_fields=["features"])
    assert queries.open_for(shop, None) == []


def test_the_ai_tool_follows_the_askers_scope(shop, owner, branch_accountant, branches):
    from apps.ai.tools.registry import ToolContext
    from apps.insights.ai_tools import InsightsOpenInput, insights_open

    mine = InsightFactory(company=shop, branch=branches[0])
    InsightFactory(company=shop, branch=branches[1])
    InsightFactory(company=shop, kind=Insight.Kind.STAFF_COST, domain="payroll")
    everything = insights_open(ToolContext.for_member(owner), InsightsOpenInput())
    assert len(everything.rows) == 3
    theirs = insights_open(ToolContext.for_member(branch_accountant), InsightsOpenInput())
    assert [row["id"] for row in theirs.rows] == [mine.pk]  # no payroll view, one branch
    assert theirs.rows[0]["branch"] == "Chilonzor"
