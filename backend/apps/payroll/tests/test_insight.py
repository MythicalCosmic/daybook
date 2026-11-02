"""What payroll tells people beyond the runs: the wallet's "earned so far", the overview, the
AI tool, the portfolio card, briefings, the company calendar and the hourly cost contract."""

from datetime import date
from decimal import Decimal

import pytest
from django.core.cache import cache

from apps.ai.tools.registry import SWITCHES
from apps.ai.tools.testing import call_tool
from apps.console import contracts
from apps.payroll import (
    ai_tools,  # noqa: F401  (registers the tool before apps/ai's tests swap the registry)
    earnings,
    providers,
    services,
)
from apps.payroll.contracts import cost_rate
from apps.payroll.models import AdjustmentRule
from apps.payroll.tests.conftest import local

pytestmark = pytest.mark.django_db

D = Decimal


def url(company, path=""):
    return f"/api/v1/owner/companies/{company.pk}/payroll/{path}"


def my_url(company, path=""):
    return f"/api/v1/companies/{company.pk}/payroll/{path}"


@pytest.fixture
def team(staff, monkeypatch):
    monkeypatch.setattr(
        "apps.hr.queries.employment_dates",
        lambda company, member_ids: {pk: (date(2025, 6, 1), None) for pk in member_ids},
    )
    cache.clear()
    services.set_pay(staff.ali, by=None, effective_from=date(2026, 1, 1), amount="5200000")
    services.set_pay(staff.sara, by=None, effective_from=date(2026, 1, 1), amount="4680000")
    return staff


def test_earned_so_far_and_the_estimate(shop, team, freeze, api_as):
    freeze(local(date(2026, 10, 21), 12))
    services.propose(team.ali, by=team.manager, kind="bonus", amount="100000", reason="Help")
    response = api_as(team.ali).get(my_url(shop, "earnings/current/"))
    assert response.status_code == 200, response.data
    data = response.data
    # 17 of October's 26 working days have passed by Wednesday the 21st.
    assert data["so_far"]["net"] == "3400000.00" and data["so_far"]["base"] == "3400000.00"
    assert data["estimate"]["net"] == "5200000.00"
    assert data["has_pay_setup"] and data["pay_type"] == "monthly"
    assert [row["amount"] for row in data["proposed"]] == ["100000.00"]
    # Somebody without a pay setup sees why there is nothing.
    vali = api_as(team.vali).get(my_url(shop, "earnings/current/")).data
    assert vali["has_pay_setup"] is False and vali["so_far"]["net"] == "0.00"


def test_rule_progress_in_the_wallet(shop, team, freeze):
    freeze(local(date(2026, 10, 21), 12))
    services.save_rule(
        shop,
        by=None,
        name="On time",
        kind="bonus",
        metric=AdjustmentRule.Metric.HOURS,
        mode=AdjustmentRule.Mode.TIERED,
        tiers=[{"threshold": "100", "amount": "100000"}, {"threshold": "150", "amount": "300000"}],
        is_active=True,
    )
    found = earnings.current(team.ali, fresh=True)["progress"]
    assert found == [
        {
            "rule": found[0]["rule"],
            "name": "On time",
            "metric": "attendance.hours",
            "value": "0.00",
            "earned": "0.00",
            "target": "100.00",
            "target_amount": "100000.00",
            "min_tasks": None,
            "tasks": None,
        }
    ]


def test_overview(shop, team, freeze, owner_api):
    freeze(local(date(2026, 11, 3), 10))
    run = services.create_run(shop, by=team.owner, period="2026-10")
    services.finalize_run(run, by=team.owner)
    response = owner_api(team.accountant).get(url(shop, "overview/"), {"months": 3})
    assert response.status_code == 200, response.data
    data = response.data
    assert [row["period"] for row in data["months"]] == ["2026-10-01"]
    assert data["months"][0]["net"] == "9880000.00"
    assert data["projected"]["period"] == "2026-11-01" and data["projected"]["source"] == "estimate"
    assert data["projected"]["gross"] == "9880000.00"
    assert {row["label"] for row in data["by_branch"]} == {"Chilonzor", "Yunusobod"}
    assert data["headcount"] == 2
    assert owner_api(team.manager).get(url(shop, "overview/")).status_code == 403
    assert owner_api(team.owner).get(url(shop, "overview/"), {"months": 99}).status_code == 400


def test_ai_payroll_summary_needs_the_switch_and_payroll_view(shop, team, freeze):
    freeze(local(date(2026, 11, 3), 10))
    run = services.create_run(shop, by=team.owner, period="2026-10")
    services.finalize_run(run, by=team.owner)
    result = call_tool("payroll_summary", team.accountant, month="2026-10")
    assert result["data"]["net"] == "9880000.00" and result["data"]["status"] == "finalized"
    assert {row["id"] for row in result["rows"]} == {team.ali.pk, team.sara.pk}
    without = call_tool(
        "payroll_summary",
        team.accountant,
        _switches=SWITCHES - {"share_salaries"},
        month="2026-10",
    )
    assert "error" in without
    assert "error" in call_tool("payroll_summary", team.manager, month="2026-10")
    projection = call_tool("payroll_summary", team.owner, month="2026-11")
    assert projection["data"]["status"] == "no_run"


def test_portfolio_card_briefing_and_calendar(shop, team, freeze):
    now = freeze(local(date(2026, 11, 3), 10))
    run = services.create_run(shop, by=team.owner, period="2026-10")
    services.finalize_run(run, by=team.owner)
    facts = providers.company_facts(shop, None, team.owner)
    assert contracts.problems(contracts.COMPANY_FACTS["payroll"], facts) == []
    assert facts == {"next_run_on": "2026-11-05", "next_run_amount": "9880000.00"}
    brief = providers.brief_section(shop, date(2026, 11, 3), now, None)
    assert brief["run"]["status"] == "finalized" and brief["pay_day"] == "2026-11-05"
    items = providers.calendar_events(shop, date(2026, 11, 1), date(2026, 11, 30), team.owner)
    assert [(item.kind, item.start) for item in items] == [
        ("payroll.pay_day", date(2026, 11, 5)),
        ("payroll.advance_day", date(2026, 11, 20)),
    ]


def test_cost_rate_from_the_pay_setup(shop, team):
    # October: 26 working days of 8 hours for 5 200 000.
    assert cost_rate(team.ali, date(2026, 10, 20)) == D("25000.00")
    assert cost_rate(team.vali, date(2026, 10, 20)) is None
    services.set_pay(
        team.vali, by=None, effective_from=date(2026, 1, 1), amount="15000", pay_type="hourly"
    )
    assert cost_rate(team.vali, date(2026, 10, 20)) == D("15000.00")
