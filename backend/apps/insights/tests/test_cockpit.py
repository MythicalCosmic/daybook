"""The cockpit's numbers are the P&L's and the forecast's, inside the caller's scope; money only
for those who may see finance; decisions settle through their apps' own endpoints."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache

from apps.finance import claims as finance_claims
from apps.finance import queries
from apps.finance.models import Category, Claim
from apps.insights import cockpit, display, engine
from apps.insights.models import Insight
from apps.insights.tests.conftest import NOW, TODAY, days_before, mln

pytestmark = pytest.mark.django_db

MONTH = (TODAY.replace(day=1), TODAY)
SAME_DAYS = (TODAY.replace(month=9, day=1), TODAY.replace(month=9))
LAST_MONTH = (TODAY.replace(month=9, day=1), TODAY.replace(month=9, day=30))
BEFORE = (TODAY.replace(month=8, day=1), TODAY.replace(month=8, day=31))


@pytest.fixture(autouse=True)
def fresh_cache():
    cache.clear()


@pytest.fixture
def month_of_books(books, branches):
    chilonzor, yunusobod = branches
    books.income(mln(60), days_before(70), chilonzor)  # August
    books.expense(mln(50), days_before(70), chilonzor, category="goods")
    books.income(mln(100), days_before(40), chilonzor)  # September, the same days
    books.expense(mln(60), days_before(40), chilonzor, category="goods")
    books.expense(mln(9), days_before(38), chilonzor)  # rent
    books.expense(mln(20), days_before(22), chilonzor, category="salaries")  # 28 September
    books.income(mln(120), days_before(10), chilonzor)  # October
    books.expense(mln(70), days_before(9), chilonzor, category="goods")
    books.expense(mln(9), days_before(8), chilonzor)
    books.income(mln(80), days_before(10), yunusobod)
    books.expense(mln(79), days_before(9), yunusobod, category="goods")
    books.expense(mln(3), days_before(9), yunusobod)
    books.expense(mln(2), days_before(5), None, category="other_expense")  # no branch
    return books


def pnl(company, start, end, branch_ids, compare=None):
    return queries.pnl(company, start, end, "month", branch_ids=branch_ids, compare=compare)


def test_profit_by_branch_is_the_pnl(shop, owner, branches, month_of_books):
    data = cockpit.build(owner, now=NOW)
    money = data["money"]
    chilonzor, _yunusobod = branches
    rows = {row["id"]: row for row in money["branches"]}
    for branch in branches:
        month = pnl(shop, *MONTH, [branch.pk], compare=SAME_DAYS)
        row = rows[branch.pk]["month"]
        assert row["revenue"] == str(month["income"]["total"])
        assert row["profit"] == str(month["profit"]["total"])
        assert row["margin"] == month["margin"]["total"]
        assert row["previous"]["profit"] == str(month["profit"]["previous"])
        last = pnl(shop, *LAST_MONTH, [branch.pk], compare=BEFORE)
        assert rows[branch.pk]["last_month"]["profit"] == str(last["profit"]["total"])
        assert rows[branch.pk]["last_month"]["previous"]["profit"] == str(
            last["profit"]["previous"]
        )
    chilonzor_month = rows[chilonzor.pk]["month"]
    assert chilonzor_month["goods"] == "70000000.00"
    assert chilonzor_month["gross"] == "50000000.00"
    assert chilonzor_month["gross_margin"] == "41.7"
    assert [cost["key"] for cost in chilonzor_month["costs"]] == ["goods", "rent"]
    # Salaries are booked at the month's end: September had them, October doesn't yet.
    assert chilonzor_month["missing"] == [
        {"key": "salaries", "name": "Salaries", "last_month": "20000000.00"}
    ]
    total = pnl(shop, *MONTH, None)
    assert money["total"]["month"]["profit"] == str(total["profit"]["total"])
    # What no branch carries: the 2 mln of other expenses.
    assert money["unassigned"]["month"]["expense"] == "2000000.00"
    assert money["unassigned"]["month"]["costs"][0]["key"] == "other_expense"
    trend = rows[chilonzor.pk]["trend"]
    assert [point["month"] for point in trend] == [
        "2026-04",
        "2026-05",
        "2026-06",
        "2026-07",
        "2026-08",
        "2026-09",
    ]
    assert trend[-1]["profit"] == str(pnl(shop, *LAST_MONTH, [chilonzor.pk])["profit"]["total"])
    assert money["periods"]["month"] == {
        "from": "2026-10-01",
        "to": "2026-10-20",
        "previous_from": "2026-09-01",
        "previous_to": "2026-09-20",
    }


def test_branch_states(shop, owner, branches, month_of_books):
    data = cockpit.build(owner, now=NOW)
    states = {row["name"]: row["states"]["month"] for row in data["money"]["branches"]}
    # Chilonzor: margin 34.2 % against 31.0 %; Yunusobod: 80 mln in, 82 mln out.
    assert states["Chilonzor"] == {"state": "green", "reasons": []}
    assert states["Yunusobod"]["state"] == "red"
    assert "loss" in states["Yunusobod"]["reasons"]


def test_an_open_insight_colours_its_branch(shop, owner, branches, month_of_books):
    from apps.insights.tests.factories import InsightFactory

    InsightFactory(company=shop, branch=branches[0], severity=Insight.Severity.WARNING)
    data = cockpit.build(owner, now=NOW)
    chilonzor = next(row for row in data["money"]["branches"] if row["id"] == branches[0].pk)
    assert chilonzor["states"]["month"] == {"state": "amber", "reasons": ["warning"]}


def test_cash_and_runway_are_the_forecast(shop, owner, books):
    books.income(mln(300), days_before(70), category="other_income")
    for day in range(1, 57):
        books.expense(mln(1), days_before(day), category="utilities")
    party = books.party("Oqtosh Med")
    books.owed("payable", mln(40), days_before(10), TODAY + timedelta(days=12), party)
    data = cockpit.build(owner, now=NOW)
    cash = data["cash"]
    forecast = queries.forecast(shop, 90, branch_ids=None, today=TODAY)
    assert cash["now"] == forecast["start"]
    assert cash["low"]["date"] == forecast["low"]["date"]
    assert cash["low"]["balance"] == forecast["low"]["balance"]
    assert cash["points"] == [
        {"date": p["date"], "balance": p["balance"]} for p in forecast["points"]
    ]
    daily = Decimal(forecast["basis"]["daily_out"]) + Decimal(forecast["basis"]["daily_paid"])
    assert cash["daily_spend"] == str(daily)
    assert cash["runway"]["days"] == int(Decimal(forecast["start"]) / daily)
    assert cash["runway"]["basis"] == "spending"
    assert cash["low"]["causes"][0]["title"] == "Oqtosh Med"


def test_runway_ends_when_the_forecast_goes_below_zero(shop, owner, books):
    books.income(mln(10), days_before(70), category="other_income")
    party = books.party("Oqtosh Med")
    books.owed("payable", mln(30), days_before(10), TODAY + timedelta(days=6), party)
    cash = cockpit.build(owner, now=NOW)["cash"]
    assert cash["runway"] == {
        "days": 6,
        "basis": "forecast",
        "below_zero_on": (TODAY + timedelta(days=6)).isoformat(),
        "horizon": 90,
    }
    assert cash["low"]["short_by"] == "20000000.00"


def test_a_branch_accountant_sees_only_their_branch(
    shop, branch_accountant, branches, month_of_books
):
    chilonzor, _yunusobod = branches
    data = cockpit.build(branch_accountant, now=NOW)
    money = data["money"]
    assert [row["id"] for row in money["branches"]] == [chilonzor.pk]
    assert money["total"]["month"]["profit"] == str(
        pnl(shop, *MONTH, [chilonzor.pk])["profit"]["total"]
    )
    assert money["unassigned"] is None
    forecast = queries.forecast(shop, 90, branch_ids=[chilonzor.pk], today=TODAY)
    assert data["cash"]["now"] == forecast["start"]


def test_insights_follow_the_branch_scope(shop, owner, branch_accountant, branches):
    from apps.insights.tests.factories import InsightFactory

    mine = InsightFactory(company=shop, branch=branches[0])
    InsightFactory(company=shop, branch=branches[1])
    InsightFactory(company=shop, branch=None)
    seen = [item["id"] for item in cockpit.build(branch_accountant, now=NOW)["insights"]["items"]]
    assert seen == [mine.pk]
    assert len(cockpit.build(owner, now=NOW)["insights"]["items"]) == 3


def test_no_money_without_finance_view(shop, manager, month_of_books):
    data = cockpit.build(manager, now=NOW)
    assert "money" not in data
    assert "cash" not in data
    assert data["can"]["money"] is False
    assert data["can"]["insights"] is True


def test_no_money_while_finance_is_off(shop, owner, month_of_books):
    shop.features = []
    shop.save(update_fields=["features"])
    owner.refresh_from_db()
    data = cockpit.build(owner, now=NOW)
    assert "money" not in data


def test_the_money_is_cached_until_the_ledger_moves(shop, owner, books, branches):
    books.income(mln(10), days_before(5), branches[0])
    first = cockpit.build(owner, now=NOW)["money"]["total"]["month"]["revenue"]
    books.income(mln(5), days_before(4), branches[0])
    assert cockpit.build(owner, now=NOW)["money"]["total"]["month"]["revenue"] == first
    from apps.console import pulse

    pulse.bump(shop.pk, "finance.ledger")
    assert cockpit.build(owner, now=NOW)["money"]["total"]["month"]["revenue"] == "15000000.00"


# Decisions ------------------------------------------------------------------------------------


@pytest.fixture
def claim(shop, member, branches):
    """A pharmacist's expense above the approval limit."""
    from apps.finance import conf as finance_conf

    settings_row = finance_conf.get_settings(shop)
    settings_row.approval_threshold = Decimal(100_000)
    settings_row.save()
    pharmacist = member.registered(shop, "Pharmacist", first_name="Madina")
    pharmacist.branches.set([branches[0]])
    category = Category.objects.get(company=shop, system_code="repairs")
    return finance_claims.submit_claim(
        shop,
        by=pharmacist,
        amount=Decimal(1_850_000),
        category=category,
        spent_on=days_before(1),
        paid_from=Claim.PaidFrom.OWN_MONEY,
        description="Fridge thermometers",
    )


def test_decisions_list_the_waiting_claim(shop, owner, claim):
    data = cockpit.build(owner, now=NOW)["decisions"]
    assert data["total"] == 1
    assert {
        key: value
        for key, value in next(s for s in data["sources"] if s["key"] == "finance.claims").items()
        if key != "label"
    } == {"key": "finance.claims", "group": "expense", "count": 1}
    [item] = data["items"]
    assert item["source"] == "finance.claims"
    assert item["group"] == "expense"
    approve = next(action for action in item["actions"] if action["key"] == "approve")
    assert approve["endpoint"] == f"finance/claims/{claim.pk}/approve/"


def test_approve_in_one_tap_through_the_claims_endpoint(shop, owner, claim, owner_api):
    item = cockpit.build(owner, now=NOW)["decisions"]["items"][0]
    approve = next(action for action in item["actions"] if action["key"] == "approve")
    response = owner_api(owner).post(
        f"/api/v1/owner/companies/{shop.pk}/{approve['endpoint']}", approve["body"], format="json"
    )
    assert response.status_code == 200, response.content
    claim.refresh_from_db()
    assert claim.status == Claim.Status.APPROVED
    assert cockpit.build(owner, now=NOW)["decisions"]["items"] == []


def test_reject_needs_its_reason(shop, owner, claim, owner_api):
    item = cockpit.build(owner, now=NOW)["decisions"]["items"][0]
    reject = next(action for action in item["actions"] if action["key"] == "reject")
    assert reject["needs_reason"] is True
    response = owner_api(owner).post(
        f"/api/v1/owner/companies/{shop.pk}/{reject['endpoint']}",
        {**reject["body"], "reason": "Not a company cost"},
        format="json",
    )
    assert response.status_code == 200, response.content
    claim.refresh_from_db()
    assert claim.status == Claim.Status.REJECTED


def test_decisions_keep_each_queues_permission(shop, manager, claim):
    # The default Manager approves join requests and time off, not expense claims.
    sources = {s["key"] for s in cockpit.build(manager, now=NOW)["decisions"]["sources"]}
    assert "finance.claims" not in sources
    assert {"members.join", "timeoff.request"} <= sources


def test_a_join_request_is_a_decision(shop, owner, member):
    from apps.members.models import Membership

    member(shop, "Employee", status=Membership.Status.PENDING, onboarded_at=NOW)
    data = cockpit.build(owner, now=NOW)["decisions"]
    assert any(item["source"] == "members.join" for item in data["items"])


def test_open_insights_in_the_cockpit(shop, owner, books):
    books.income(mln(50), days_before(70), category="other_income")
    supplier = books.party("Tolzor Farm")
    books.owed("payable", mln(4), days_before(20), days_before(3), supplier)
    engine.run(shop, NOW, notify=False)
    data = cockpit.build(owner, now=NOW)["insights"]
    assert data["live"] == 1
    assert data["open"] == 1
    assert data["items"][0]["kind"] == "overdue_payables"
    assert data["items"][0]["title"] == "Supplier bills overdue: " + display.money(mln(4))
