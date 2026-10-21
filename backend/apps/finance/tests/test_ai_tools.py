"""The finance AI tools run through the real runner (`call_tool`): permission, module, data
switch, branch scope, salary detail and scrubbing."""

import importlib
from decimal import Decimal

import pytest

from apps.ai.tools import registry
from apps.ai.tools.registry import SWITCHES
from apps.ai.tools.testing import call_tool
from apps.companies.models import Branch
from apps.finance import ai_tools, queries, services
from apps.finance.tests.factories import CounterpartyFactory, MoneyAccountFactory
from apps.members.permissions import Perm

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture(autouse=True)
def finance_tools(monkeypatch):
    """apps.ai's own tests swap in an empty tool registry and may import this module into it,
    so after them the real registry can lack these tools (the module is imported only once).
    Put them back, for this test only, whatever ran before."""
    registry.autodiscover()
    if "finance_summary" not in registry._tools:
        kept = {
            name: tool for name, tool in registry._tools.items() if not name.startswith("finance_")
        }
        monkeypatch.setattr(registry, "_tools", kept)
        importlib.reload(ai_tools)


@pytest.fixture
def today(fin):
    return queries.local_today(fin)


@pytest.fixture
def boss(fin, member):
    return member(fin, "Owner")


@pytest.fixture
def ledger(fin, boss, cash, today, member):
    services.record_transaction(
        fin,
        by=boss,
        kind="income",
        amount=D("5000000"),
        occurred_on=today,
        account=cash,
        category="sales",
    )
    worker = member(fin, "Employee", first_name="Jasur")
    services.record_transaction(
        fin,
        by=boss,
        kind="expense",
        amount=D("1200000"),
        occurred_on=today,
        account=cash,
        category="salaries",
        membership=worker,
        description="Jasur, call +998901234567",
    )
    services.open_debt(
        fin,
        by=boss,
        direction="receivable",
        kind="trade",
        amount=D("400000"),
        currency="UZS",
        issued_on=today,
        counterparty=CounterpartyFactory(company=fin, name="Barakat"),
        is_opening=True,
    )


def test_summary(boss, ledger):
    result = call_tool("finance_summary", boss)
    assert result["data"]["income"] == "5000000.00"
    assert result["data"]["expenses"] == "1200000.00"
    assert result["data"]["owed_to_us"] == "400000.00"
    assert result["currency"] == "UZS"


def test_transactions_hide_salary_detail_without_the_switch(boss, ledger):
    hidden = call_tool("finance_transactions", boss, kind="expense", _switches={"share_finance"})
    assert hidden["rows"][0]["person"] is None
    assert hidden["rows"][0]["description"] == ""
    shown = call_tool("finance_transactions", boss, kind="expense", _switches=SWITCHES)
    assert shown["rows"][0]["person"] == "Jasur"
    assert "[hidden]" in shown["rows"][0]["description"]  # the phone number is scrubbed


def test_cash_position_and_debts(boss, ledger):
    position = call_tool("finance_cash_position", boss)
    assert position["data"]["total"] == "3800000.00"
    debts = call_tool("finance_debts", boss, direction="receivable")
    assert debts["rows"][0]["party"] == "Barakat"
    assert debts["rows"][0]["outstanding"] == "400000.00"


def test_permission_module_and_switch(fin, member, boss, ledger):
    manager = member(fin, "Manager")
    assert call_tool("finance_summary", manager) == {"error": "not_allowed"}
    assert call_tool("finance_summary", boss, _switches={"share_task_text"}) == {
        "error": "not_allowed"
    }
    fin.features = []
    fin.save(update_fields=["features"])
    boss.company.refresh_from_db()
    assert call_tool("finance_summary", boss) == {"error": "not_allowed"}


def test_branch_scope(fin, boss, today, role, person):
    main = fin.branches.first()
    other = Branch.objects.create(company=fin, name="Yunusobod")
    for branch, amount in ((main, "100"), (other, "900")):
        account = MoneyAccountFactory(company=fin, name=f"Kassa {branch.pk}", branch=branch)
        services.record_transaction(
            fin,
            by=boss,
            kind="income",
            amount=D(amount),
            occurred_on=today,
            account=account,
            category="sales",
        )
    viewer = person(fin, role(fin, "Branch books", [Perm.FINANCE_VIEW]), branches=[main])
    assert call_tool("finance_summary", viewer)["data"]["income"] == "100.00"
    rows = call_tool("finance_transactions", viewer)["rows"]
    assert [row["amount"] for row in rows] == ["100.00"]
