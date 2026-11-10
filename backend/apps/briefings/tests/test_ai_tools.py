"""The advisor's own tools, run the way "Ask the advisor" runs them (permission, module, data
switch, branch scope, scrubbing): the latest review's facts, and what if the money changes."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.ai.tools.registry import SWITCHES
from apps.ai.tools.testing import call_tool
from apps.briefings import reviews
from apps.finance import planning

from .conftest import MONDAY, NOW

pytestmark = pytest.mark.django_db


def test_the_latest_review_with_its_facts(ledger, people, pharmacy):
    reviews.tick()

    found = call_tool("briefings_advisor_facts", people.owner, _now=NOW)

    data = found["data"]
    assert data["written"] is True
    assert data["review"]["headline"].startswith("Week of 9–15")
    assert data["review"]["went_wrong"] and data["review"]["suggestions"]
    assert data["facts"]["finance"]["revenue"]["value"] == "20000000.00"
    assert all(
        "url" not in signal and "weight" not in signal for signal in data["facts"]["signals"]
    )
    assert found["currency"] == "UZS"


def test_before_the_first_review_the_facts_of_last_week(ledger, people):
    data = call_tool("briefings_advisor_facts", people.owner, _now=NOW)["data"]

    assert data["written"] is False and data["review"] is None
    assert data["facts"]["period"]["start"] == "2026-11-09"


def test_no_money_when_the_owner_keeps_it_from_the_ai(ledger, people):
    reviews.tick()
    switches = SWITCHES - {"share_finance"}

    data = call_tool("briefings_advisor_facts", people.owner, _switches=switches, _now=NOW)["data"]

    assert data["review"] is None
    assert not {"finance", "sales", "stock"} & set(data["facts"])
    assert all(
        not signal["key"].startswith(("revenue", "cash", "branch", "expense", "debts"))
        for signal in data["facts"]["signals"]
    )


def test_a_manager_reads_their_own_scope_only(ledger, till_days, people):
    data = call_tool("briefings_advisor_facts", people.manager, _now=NOW)["data"]

    assert "finance" not in data["facts"]
    assert data["facts"]["sales"]["net"]["value"] == "600000.00"


def test_without_reports_no_facts(ledger, people):
    assert call_tool("briefings_advisor_facts", people.clerk, _now=NOW) == {"error": "not_allowed"}


def test_what_if_a_second_pharmacy_costs_30_mln_a_month(ledger, people, pharmacy):
    start = MONDAY + timedelta(days=5)

    data = call_tool(
        "briefings_advisor_scenario",
        people.owner,
        monthly_change=-30_000_000,
        start=start.isoformat(),
        one_off=-20_000_000,
        days=90,
        label="Second pharmacy",
        _now=NOW,
    )["data"]

    plan = planning.forecast(pharmacy, 90, branch_ids=None, today=MONDAY)
    assert data["baseline"]["low"] == plan["low"]
    assert data["cash_now"] == plan["start"]
    assert data["change"] == {
        "monthly": "-30000000.00",
        "one_off": "-20000000.00",
        "from": start.isoformat(),
        "months_in_horizon": 3,
        "total_in_horizon": "-110000000.00",
    }
    end = Decimal(plan["end"]) - Decimal(110_000_000)
    assert data["scenario"]["end"] == f"{end:.2f}"
    low = data["scenario"]["low"]
    assert Decimal(low["balance"]) <= Decimal(plan["low"]["balance"])
    if data["scenario"]["below_zero_on"]:
        below = date.fromisoformat(data["scenario"]["below_zero_on"])
        assert data["scenario"]["runway_days"] == (below - MONDAY).days
    assert data["label"] == "Second pharmacy"


def test_more_income_lifts_the_low_point(ledger, people, pharmacy):
    data = call_tool(
        "briefings_advisor_scenario", people.owner, monthly_change=5_000_000, _now=NOW
    )["data"]

    assert Decimal(data["scenario"]["end"]) > Decimal(data["baseline"]["end"])
    assert data["change"]["from"] == MONDAY.isoformat()


def test_the_scenario_needs_finance_and_valid_input(ledger, people):
    assert call_tool("briefings_advisor_scenario", people.manager, monthly_change=-1, _now=NOW) == {
        "error": "not_allowed"
    }
    wrong = call_tool("briefings_advisor_scenario", people.owner, monthly_change="lots", _now=NOW)
    assert wrong["error"] == "invalid_input"
    short = call_tool(
        "briefings_advisor_scenario", people.owner, monthly_change=-1, days=5, _now=NOW
    )
    assert short["error"] == "invalid_input"


def test_the_tools_belong_to_the_advisor(ledger, people):
    from apps.ai.tools import registry

    tools = {tool.name: tool for tool in registry.all_tools()}

    assert tools["briefings_advisor_facts"].domain == "advisor"
    assert tools["briefings_advisor_scenario"].domain == "advisor"
    assert tools["briefings_advisor_scenario"].switch == "share_finance"
