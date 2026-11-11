"""The statement pack PDF (v12): it renders in Uzbek, Russian and English with its headings,
each purpose puts its own pages up front, and the finance demo's books make a sensible pack (it
balances, the loan is in the notes with its interest)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.template.loader import render_to_string
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from apps.core import pdf
from apps.finance import demo, queries, services, statement_pack, statements
from apps.finance.models import Debt, StatementPack

pytestmark = pytest.mark.django_db

D = Decimal


@pytest.fixture
def shop(fin, owner, cash, bank, today):
    """Three months of a small pharmacy with a loan."""
    lender = services.create_counterparty(fin, by=owner, name="Hamkor bank", kind="other")
    start = today - timedelta(days=95)
    services.record_transaction(
        fin, by=owner, kind="opening", amount=D("20000000"), occurred_on=start, account=bank
    )
    loan = services.open_debt(
        fin,
        by=owner,
        direction="payable",
        kind="loan",
        amount=D("12000000"),
        currency="UZS",
        issued_on=start,
        counterparty=lender,
        account=bank,
    )
    for offset in range(0, 95, 7):
        day = start + timedelta(days=offset)
        services.record_transaction(
            fin,
            by=owner,
            kind="income",
            amount=D("3000000"),
            occurred_on=day,
            account=cash,
            category="sales",
        )
        services.record_transaction(
            fin,
            by=owner,
            kind="expense",
            amount=D("2100000"),
            occurred_on=day,
            account=bank,
            category="goods",
        )
    services.pay_debt(loan, by=owner, amount=D("1000000"), paid_on=today, account=bank)
    services.record_transaction(
        fin,
        by=owner,
        kind="expense",
        amount=D("150000"),
        occurred_on=today,
        account=bank,
        category="other_expense",
        debt=loan,
    )
    return fin


@pytest.fixture
def today(fin):
    return queries.local_today(fin)


def context(company, owner, today, purpose: str, language: str, period: str = "quarter"):
    start, end = statement_pack.period_range(period, today, today)
    return statement_pack.collect(
        company,
        period=period,
        start=start,
        end=end,
        purpose=purpose,
        language=language,
        branch_ids=None,
        prepared_by=owner,
    )


@pytest.mark.parametrize("language", ["uz", "ru", "en"])
def test_the_pack_renders_in_each_language(shop, owner, today, language):
    data = context(shop, owner, today, "bank", language)
    content = pdf.render_pdf(statement_pack.TEMPLATE, data, language=language)
    assert content.startswith(b"%PDF")
    assert statement_pack.page_count(content) >= 6
    with translation.override(language):
        html = render_to_string(statement_pack.TEMPLATE, data)
        for heading in (
            "Financial statements",
            "Summary",
            "Profit and loss",
            "Cash flow",
            "Balance sheet",
            "Notes",
            "Loans and their payments",
            "Prepared from the company's records in Daybook. Not audited.",
        ):
            text = _(heading)
            assert text in html or text.replace("'", "&#x27;") in html, heading


def test_each_purpose_puts_its_pages_up_front(shop, owner, today):
    bank = context(shop, owner, today, "bank", "en")
    assert bank["order"][:2] == ["loans", "cash_flow"]
    assert bank["loans"]["raw"]["left"] == D("11000000.00")
    assert bank["loans"]["raw"]["interest"] == D("150000.00")
    partner = context(shop, owner, today, "partner", "en")
    assert "partners" not in partner["order"]  # no partners set: no partner pages
    sale = context(shop, owner, today, "sale", "en")
    assert sale["order"][0] == "valuation"
    assert sale["valuation"]["applies"] is True
    assert sale["raw"]["worth"]["earnings_method"]["debt"] == D("11000000.00")


def test_a_branch_pack_has_no_valuation_and_says_whose(shop, owner, today):
    branch = shop.branches.first()
    start, end = statement_pack.period_range("month", today, today)
    data = statement_pack.collect(
        shop,
        period="month",
        start=start,
        end=end,
        purpose="sale",
        language="en",
        branch_ids=[branch.pk],
    )
    assert "valuation" not in data["order"]
    assert data["branches"] == branch.name
    assert data["balance"]["whole_company"] is False


def test_the_numbers_read_as_printed(fin):
    fmt = statement_pack.Fmt("uz", "UZS")
    assert fmt.n(D("1234567.49")) == "1 234 567"
    assert fmt.n(D("-1500")) == "(1 500)"
    assert fmt.n(D(0)) == "–"
    assert fmt.money(D("2500000")) == "2 500 000 so‘m"
    assert fmt.pct(D("-12.34")) == "−12,3 %"
    assert statement_pack.Fmt("en", "UZS").n(D("1234567")) == "1,234,567"
    assert statement_pack.Fmt("en", "UZS").day(date(2026, 10, 31)) == "31 Oct 2026"
    assert fmt.day(date(2026, 10, 31)) == "31.10.2026"
    # A fraction takes the plural ("1.4 months", «1,4 месяца»).
    assert [statement_pack._plural(D(v)) for v in ("1", "1.04", "1.4", "5")] == [1, 1, 2, 5]


def test_periods(fin):
    today = date(2026, 11, 12)
    assert statement_pack.period_range("month", date(2026, 10, 15), today) == (
        date(2026, 10, 1),
        date(2026, 10, 31),
    )
    assert statement_pack.period_range("quarter", today, today) == (date(2026, 10, 1), today)
    assert statement_pack.period_range("year", date(2025, 3, 1), today) == (
        date(2025, 1, 1),
        date(2025, 12, 31),
    )


def test_the_download_name(shop, owner, today):
    pack = StatementPack(
        company=shop,
        requested_by=owner,
        period="quarter",
        start=date(2026, 7, 1),
        end=date(2026, 9, 30),
        purpose="bank",
        language="en",
    )
    assert statement_pack.download_name(pack).endswith("-2026-q3.pdf")


@pytest.fixture
def seeded(company, demo_people):
    """The finance demo, as seed_demo makes it (the other modules' demos aside)."""
    people = demo_people(company)
    now = timezone.now()
    company.features = ["finance"]
    company.save(update_fields=["features"])
    demo.seed(company, people, now)
    demo.finish(company, people, now)
    return company, people


def test_the_demo_makes_a_sensible_pack(seeded):
    company, people = seeded
    today = queries.local_today(company)
    sheet = statements.balance_sheet(company, today, branch_ids=None)
    assert sheet["check"]["balanced"] is True
    assert sheet["reconciliation"]["unexplained"] == D("0.00")
    loan = Debt.objects.get(company=company, kind="loan")
    data = context(company, people["owner"], today, "bank", "uz", period="month")
    assert [row["lender"] for row in data["loans"]["rows"]] == [loan.counterparty.name]
    last_month = today.replace(day=1) - timedelta(days=1)
    october = context(company, people["owner"], last_month, "bank", "uz", period="month")
    # The demo's monthly interest is booked on its loan.
    assert october["loans"]["raw"]["interest"] > 0
    content = pdf.render_pdf(statement_pack.TEMPLATE, data, language="uz")
    assert content.startswith(b"%PDF")
