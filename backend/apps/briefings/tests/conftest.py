"""Fixtures of the briefings tests: a pharmacy company with two branches (Chilonzor and
Yunusobod), its books, and its people by what they may see:

- owner: every permission, every branch;
- manager: reports, sales, attendance and people of Yunusobod only, no money (no finance.view);
- clerk: no reports.view (sees no review at all).

`ledger()` books five weeks of trade, 12 October to 15 November 2026, so the weekly review due
on Monday 16 November 08:00 (`NOW`, Asia/Tashkent) has a whole week, the week before and four
weeks to average:

- Chilonzor: 10 000 000 of sales and 6 000 000 of medicines a week; the reviewed week (9 to 15
  November) 12 000 000 and 6 600 000; transport 500 000 a week, 2 500 000 in the reviewed week;
  rent 3 000 000 once, in the week of 2 November.
- Yunusobod: 8 000 000 of sales and 4 800 000 of medicines a week; the reviewed week the same
  sales and 5 600 000 of medicines (its gross margin falls from 40 % to 30 %).
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from apps.ai import agents, availability
from apps.ai import conf as ai_conf
from apps.ai.fakes import FakeAnthropic
from apps.companies.models import Branch, Feature
from apps.finance import defaults as finance_defaults
from apps.finance import services as finance
from apps.finance.models import MoneyAccount
from apps.finance.tests.factories import MoneyAccountFactory
from apps.members.models import AccessRole
from apps.members.permissions import Perm

TZ = ZoneInfo("Asia/Tashkent")
MONDAY = date(2026, 11, 16)
NOW = datetime.combine(MONDAY, time(8, 5), TZ)
WEEK = (date(2026, 11, 9), date(2026, 11, 15))
PREVIOUS = (date(2026, 11, 2), date(2026, 11, 8))
AVERAGE = (date(2026, 10, 12), date(2026, 11, 8))
FIRST_WEEK = date(2026, 10, 12)


def at(day: date, hour: int = 8, minute: int = 5) -> datetime:
    return datetime.combine(day, time(hour, minute), TZ)


@pytest.fixture
def freeze(monkeypatch):
    """`freeze(moment)`: `timezone.now()` returns `moment` from then on."""

    def set_now(moment: datetime) -> datetime:
        monkeypatch.setattr("django.utils.timezone.now", lambda: moment)
        return moment

    set_now(NOW)
    return set_now


@pytest.fixture
def pharmacy(company, freeze):
    company.features = [Feature.FINANCE, Feature.SALES, Feature.STOCK, Feature.ATTENDANCE]
    company.save(update_fields=["features"])
    finance_defaults.ensure(company)
    first = company.branches.order_by("order", "pk").first()
    first.name, first.code = "Chilonzor", "CHL"
    first.save()
    Branch.objects.create(company=company, name="Yunusobod", code="YNS", order=1)
    return company


@pytest.fixture
def chilonzor(pharmacy):
    return pharmacy.branches.get(name="Chilonzor")


@pytest.fixture
def yunusobod(pharmacy):
    return pharmacy.branches.get(name="Yunusobod")


@pytest.fixture
def people(pharmacy, member, yunusobod):
    AccessRole.objects.create(
        company=pharmacy,
        name="Branch manager",
        permissions=[
            Perm.DASHBOARD_ACCESS,
            Perm.REPORTS_VIEW,
            Perm.SALES_VIEW,
            Perm.ATTENDANCE_VIEW,
            Perm.MEMBERS_VIEW,
        ],
    )
    AccessRole.objects.create(company=pharmacy, name="Clerk", permissions=[Perm.DASHBOARD_ACCESS])
    owner = member(pharmacy, "Owner", first_name="Dilnoza", last_name="Karimova")
    manager = member(
        pharmacy, "Branch manager", first_name="Bekzod", last_name="Mirzayev", home_branch=yunusobod
    )
    manager.branches.set([yunusobod])
    clerk = member(pharmacy, "Clerk", first_name="Aziz")
    return SimpleNamespace(owner=owner, manager=manager, clerk=clerk)


@pytest.fixture
def tills(pharmacy, chilonzor, yunusobod):
    return SimpleNamespace(
        chilonzor=MoneyAccountFactory(
            company=pharmacy, name="Kassa CHL", kind=MoneyAccount.Kind.CASH, branch=chilonzor
        ),
        yunusobod=MoneyAccountFactory(
            company=pharmacy, name="Kassa YNS", kind=MoneyAccount.Kind.CASH, branch=yunusobod
        ),
    )


def book(company, by, account, kind, amount, day, category):
    return finance.record_transaction(
        company,
        by=by,
        kind=kind,
        amount=Decimal(amount),
        occurred_on=day,
        account=account,
        category=category,
    )


@pytest.fixture
def ledger(pharmacy, people, tills):
    """Five weeks of trade (see the module's docstring)."""
    by = people.owner
    for week in range(5):
        monday = FIRST_WEEK + timedelta(days=7 * week)
        reviewed = monday == WEEK[0]
        book(
            pharmacy,
            by,
            tills.chilonzor,
            "income",
            12_000_000 if reviewed else 10_000_000,
            monday,
            "sales",
        )
        book(
            pharmacy,
            by,
            tills.chilonzor,
            "expense",
            6_600_000 if reviewed else 6_000_000,
            monday,
            "goods",
        )
        book(
            pharmacy,
            by,
            tills.chilonzor,
            "expense",
            2_500_000 if reviewed else 500_000,
            monday,
            "transport",
        )
        book(pharmacy, by, tills.yunusobod, "income", 8_000_000, monday, "sales")
        book(
            pharmacy,
            by,
            tills.yunusobod,
            "expense",
            5_600_000 if reviewed else 4_800_000,
            monday,
            "goods",
        )
    book(
        pharmacy, by, tills.chilonzor, "expense", 3_000_000, PREVIOUS[0] + timedelta(days=2), "rent"
    )
    return tills


@pytest.fixture
def till_days(pharmacy, chilonzor, yunusobod):
    """What the tills took on the Mondays of the reviewed week and the week before."""
    from apps.sales.models import DailySales

    rows = []
    for day, branch, net, receipts in (
        (WEEK[0], chilonzor, 900_000, 30),
        (WEEK[0], yunusobod, 600_000, 20),
        (PREVIOUS[0], yunusobod, 500_000, 25),
    ):
        rows.append(
            DailySales.objects.create(
                company=pharmacy,
                branch=branch,
                day=day,
                sales=net,
                net=net,
                receipts=receipts,
                computed_at=NOW,
            )
        )
    return rows


@pytest.fixture
def fake_claude(monkeypatch, settings):
    """Claude "configured" (a key) and answered by a script: `fake_claude.script(...)`."""
    settings.ANTHROPIC_API_KEY = "sk-test"
    settings.AI_FAKE = False
    fake = FakeAnthropic()
    monkeypatch.setattr("apps.ai.client.get_client", lambda: fake)
    availability.reset_breaker()
    return fake


@pytest.fixture
def ai_on(pharmacy):
    """AI switched on as an owner's consent leaves it, with Maslahatchi on."""

    def switch(company=pharmacy, advisor: bool = True):
        if Feature.AI not in company.features:
            company.features = [*company.features, Feature.AI]
            company.save(update_fields=["features"])
        row = ai_conf.get_settings(company)
        row.enabled = True
        row.save()
        state = agents.state_of(company, "advisor")
        state.enabled = advisor
        state.save()
        return state

    return switch
