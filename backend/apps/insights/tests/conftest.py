"""A pharmacy with two branches and its books, for the insights and cockpit tests.

Dates are fixed: `NOW` is 20 October 2026, 10:00 in Tashkent (outside the quiet hours), so
"this month so far" is 1 to 20 October and its same days last month 1 to 20 September.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from apps.companies.models import Branch
from apps.finance import defaults as finance_defaults
from apps.finance import services as finance
from apps.finance.models import Counterparty, MoneyAccount
from apps.finance.tests.factories import MoneyAccountFactory
from apps.members.models import AccessRole
from apps.members.permissions import Perm

ZONE = ZoneInfo("Asia/Tashkent")
NOW = datetime(2026, 10, 20, 10, 0, tzinfo=ZONE)
TODAY = date(2026, 10, 20)
MLN = Decimal(1_000_000)


def mln(value) -> Decimal:
    return Decimal(str(value)) * MLN


@pytest.fixture
def shop(company):
    company.features = ["finance"]
    company.timezone = "Asia/Tashkent"
    company.save(update_fields=["features", "timezone"])
    finance_defaults.ensure(company)
    return company


@pytest.fixture
def branches(shop):
    first = shop.branches.order_by("order", "pk").first()
    first.name = "Chilonzor"
    first.save(update_fields=["name"])
    second = Branch.objects.create(company=shop, name="Yunusobod", code="YNS", order=2)
    return first, second


@pytest.fixture
def owner(shop, member, branches):
    person = member.registered(shop, "Owner", first_name="Dilnoza")
    person.branches.set(branches)
    return person


@pytest.fixture
def role(db):
    """`role(company, "Name", [perms])`: a custom role, for permission and scope tests."""

    def make(company, name, perms):
        return AccessRole.objects.create(
            company=company, name=name, permissions=[str(perm) for perm in perms]
        )

    return make


@pytest.fixture
def branch_accountant(shop, member, role, branches):
    """Sees money and reports, but only Chilonzor (no branches.all)."""
    accountant = role(
        shop,
        "Branch accountant",
        [Perm.DASHBOARD_ACCESS, Perm.FINANCE_VIEW, Perm.REPORTS_VIEW, Perm.FINANCE_APPROVE],
    )
    person = member.registered(shop, "Employee", first_name="Aziza")
    person.role = accountant
    person.home_branch = branches[0]
    person.save(update_fields=["role", "home_branch"])
    person.branches.set([branches[0]])
    return person


@pytest.fixture
def manager(shop, member, branches):
    """The default Manager role: reports and approvals, no finance.view."""
    person = member.registered(shop, "Manager", first_name="Bekzod")
    person.branches.set([branches[0]])
    return person


class Books:
    """Ledger rows through the finance services (never factories), on fixed days."""

    def __init__(self, company, by, branches):
        self.company = company
        self.by = by
        self.branches = branches
        self.tills = {
            branch.pk: MoneyAccountFactory(
                company=company,
                name=f"Till {branch.name}",
                kind=MoneyAccount.Kind.CASH,
                branch=branch,
                allow_negative=True,
            )
            for branch in branches
        }
        self.bank = MoneyAccountFactory(
            company=company, name="Bank", kind=MoneyAccount.Kind.BANK, allow_negative=True
        )

    def account(self, branch):
        return self.bank if branch is None else self.tills[branch.pk]

    def income(self, amount, day: date, branch=None, category="sales"):
        return finance.record_transaction(
            self.company,
            by=self.by,
            kind="income",
            amount=Decimal(amount),
            occurred_on=day,
            account=self.account(branch),
            category=category,
        )

    def expense(self, amount, day: date, branch=None, category="rent", **fields):
        return finance.record_transaction(
            self.company,
            by=self.by,
            kind="expense",
            amount=Decimal(amount),
            occurred_on=day,
            account=self.account(branch),
            category=category,
            **fields,
        )

    def party(self, name: str, kind=Counterparty.Kind.SUPPLIER):
        return finance.create_counterparty(self.company, by=self.by, name=name, kind=kind)

    def owed(self, direction: str, amount, issued_on: date, due_on: date, party, branch=None):
        return finance.open_debt(
            self.company,
            by=self.by,
            direction=direction,
            kind="trade",
            amount=Decimal(amount),
            currency="UZS",
            issued_on=issued_on,
            due_on=due_on,
            counterparty=party,
            category="sales" if direction == "receivable" else "goods",
            branch=branch,
        )

    def pay(self, debt, amount, day: date):
        return finance.pay_debt(
            debt, by=self.by, amount=Decimal(amount), paid_on=day, account=self.bank
        )


@pytest.fixture
def books(shop, owner, branches):
    return Books(shop, owner, branches)


def days_before(count: int) -> date:
    return TODAY - timedelta(days=count)
