"""Partners and dividends (v11): shares that add up to 100 %, share changes over time, the
dividend split and its payment as owner draws, taking a payment back, cancelling, the profit
share report and the endpoints."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.core.exceptions import DomainError
from apps.finance import owner_draw, partners, queries, services
from apps.finance.models import Dividend, MoneyAccount, Partner, Transaction
from apps.finance.tests.factories import MoneyAccountFactory

pytestmark = pytest.mark.django_db
D = Decimal


def url(company, path: str) -> str:
    return f"/api/v1/owner/companies/{company.pk}/finance/{path}"


@pytest.fixture
def boss(fin, member):
    return member(fin, "Owner", first_name="Dilnoza", last_name="Karimova")


@pytest.fixture
def today(fin):
    return queries.local_today(fin)


@pytest.fixture
def bank(fin, boss, today):
    account = MoneyAccountFactory(company=fin, name="Bank", kind=MoneyAccount.Kind.BANK)
    services.record_transaction(
        fin,
        by=boss,
        kind="opening",
        amount=D("300000000"),
        occurred_on=today - timedelta(days=120),
        account=account,
    )
    return account


@pytest.fixture
def quarter(today):
    """The last full quarter."""
    first = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
    end = first - timedelta(days=1)
    return date(end.year, 3 * ((end.month - 1) // 3) + 1, 1), end


@pytest.fixture
def two(fin, boss, quarter):
    """Dilnoza 60 % and an outside partner 40 %, from before the quarter."""
    return partners.set_partners(
        fin,
        by=boss,
        effective_on=quarter[0] - timedelta(days=30),
        rows=[
            {"membership": boss, "name": "", "share": "60"},
            {"membership": None, "name": "Rustam Qodirov", "share": "40"},
        ],
    )


def sale(company, by, account, amount, day):
    return services.record_transaction(
        company,
        by=by,
        kind="income",
        amount=D(amount),
        occurred_on=day,
        account=account,
        category="sales",
    )


# Partners --------------------------------------------------------------------------------------


def test_shares_must_add_up_to_100(fin, boss, today):
    for rows in (
        [{"membership": boss, "name": "", "share": "60"}],
        [
            {"membership": boss, "name": "", "share": "60"},
            {"membership": None, "name": "Rustam", "share": "50"},
        ],
        [
            {"membership": None, "name": "Rustam", "share": "50"},
            {"membership": None, "name": "rustam", "share": "50"},
        ],
        [{"membership": None, "name": " ", "share": "100"}],
        [{"membership": None, "name": "Rustam", "share": "0"}, {"name": "B", "share": "100"}],
        [],
    ):
        with pytest.raises(DomainError):
            partners.set_partners(fin, by=boss, effective_on=today, rows=rows)
    assert not Partner.objects.filter(company=fin).exists()


def test_a_member_partner_takes_their_name(fin, boss, two):
    assert [(row.name, row.share) for row in two] == [
        ("Dilnoza Karimova", D("60.00")),
        ("Rustam Qodirov", D("40.00")),
    ]
    assert two[0].membership == boss
    assert partners.identity(two[0]) == f"m{boss.pk}"
    assert partners.identity(two[1]) == "n:rustam qodirov"


def test_a_change_ends_the_old_shares_the_day_before(fin, boss, two, today):
    made = partners.set_partners(
        fin,
        by=boss,
        effective_on=today,
        rows=[
            {"membership": boss, "name": "", "share": "50"},
            {"membership": None, "name": "Rustam Qodirov", "share": "50"},
        ],
    )

    for old in two:
        old.refresh_from_db()
        assert old.ends_on == today - timedelta(days=1)
    assert [row.share for row in partners.current(fin)] == [D("50.00"), D("50.00")]
    assert [row.share for row in partners.partners_on(fin, today - timedelta(days=1))] == [
        D("60.00"),
        D("40.00"),
    ]
    # A change can't start before the last one; one on the same day replaces it.
    with pytest.raises(DomainError):
        partners.set_partners(
            fin,
            by=boss,
            effective_on=today - timedelta(days=1),
            rows=[{"membership": boss, "name": "", "share": "100"}],
        )
    partners.set_partners(
        fin, by=boss, effective_on=today, rows=[{"membership": boss, "name": "", "share": "100"}]
    )
    assert [(row.name, row.share) for row in partners.current(fin)] == [
        ("Dilnoza Karimova", D("100.00"))
    ]
    assert not Partner.objects.filter(pk__in=[row.pk for row in made]).exists()


# Dividends -------------------------------------------------------------------------------------


def test_a_dividend_splits_by_the_shares_and_rounding_goes_to_the_biggest(fin, boss, two, quarter):
    dividend = partners.create_dividend(
        fin, by=boss, period_start=quarter[0], period_end=quarter[1], amount="10000000.01"
    )

    lines = list(dividend.lines.order_by("-share"))
    assert [(line.partner.name, line.amount) for line in lines] == [
        ("Dilnoza Karimova", D("6000000.01")),
        ("Rustam Qodirov", D("4000000.00")),
    ]
    assert sum(line.amount for line in lines) == dividend.amount
    assert partners.state(dividend) == Dividend.Status.DRAFT


def test_paying_a_dividend_books_one_owner_draw_per_partner(fin, boss, bank, two, quarter, today):
    dividend = partners.create_dividend(
        fin, by=boss, period_start=quarter[0], period_end=quarter[1], amount="50000000"
    )

    partners.pay_dividend(dividend, by=boss, account=bank, paid_on=today)

    dividend.refresh_from_db()
    assert dividend.status == Dividend.Status.PAID
    assert dividend.paid_at is not None
    rows = Transaction.objects.filter(company=fin, source_type="finance.dividend").order_by(
        "amount"
    )
    assert [(row.kind, row.amount, row.account_id) for row in rows] == [
        ("owner", D("-30000000.00"), bank.pk),
        ("owner", D("-20000000.00"), bank.pk),
    ]
    assert rows[0].membership == boss
    assert rows[1].membership is None
    assert "Rustam Qodirov" in rows[1].description
    assert queries.balance(bank) == D("250000000.00")
    # Dividends are owner money: never in the profit; in this month's draws.
    assert owner_draw.owner_flows(fin, today, today)["drawn"] == D("50000000.00")
    with pytest.raises(DomainError):
        partners.pay_dividend(dividend, by=boss, account=bank, paid_on=today)


def test_one_line_at_a_time_and_taking_a_payment_back(fin, boss, bank, two, quarter, today):
    dividend = partners.create_dividend(
        fin, by=boss, period_start=quarter[0], period_end=quarter[1], amount="10000000"
    )
    first, _second = dividend.lines.order_by("-share")

    partners.pay_dividend(dividend, by=boss, account=bank, paid_on=today, line_ids=[first.pk])
    dividend.refresh_from_db()
    assert dividend.status == Dividend.Status.PARTLY_PAID
    with pytest.raises(DomainError):
        partners.update_dividend(dividend, by=boss, amount="20000000")
    with pytest.raises(DomainError):
        partners.cancel_dividend(dividend, by=boss, reason="Xato")

    partners.undo_payment(first, by=boss, reason="Noto‘g‘ri hisobdan")
    dividend.refresh_from_db()
    assert dividend.status == Dividend.Status.DRAFT
    first.refresh_from_db()
    assert first.transaction.status == Transaction.Status.VOID
    assert queries.balance(bank) == D("300000000.00")

    # Paid again later (the void freed its source), then the whole round.
    partners.pay_dividend(dividend, by=boss, account=bank, paid_on=today)
    dividend.refresh_from_db()
    assert dividend.status == Dividend.Status.PAID
    assert queries.balance(bank) == D("290000000.00")


def test_a_draw_voided_in_the_ledger_unpays_its_line(fin, boss, bank, two, quarter, today):
    dividend = partners.create_dividend(
        fin, by=boss, period_start=quarter[0], period_end=quarter[1], amount="10000000"
    )
    partners.pay_dividend(dividend, by=boss, account=bank, paid_on=today)
    line = dividend.lines.order_by("share").first()

    services.void_transaction(line.transaction, by=boss, reason="Qaytarildi")

    assert partners.state(dividend) == Dividend.Status.PARTLY_PAID


def test_a_dividend_needs_partners_a_business_account_and_enough_money(
    fin, boss, bank, quarter, today
):
    with pytest.raises(DomainError):
        partners.create_dividend(
            fin, by=boss, period_start=quarter[0], period_end=quarter[1], amount="1000"
        )
    partners.set_partners(
        fin,
        by=boss,
        effective_on=quarter[0],
        rows=[{"membership": boss, "name": "", "share": "100"}],
    )
    dividend = partners.create_dividend(
        fin, by=boss, period_start=quarter[0], period_end=quarter[1], amount="400000000"
    )
    with pytest.raises(DomainError):  # more than the bank holds: nothing is paid
        partners.pay_dividend(dividend, by=boss, account=bank, paid_on=today)
    assert not Transaction.objects.filter(company=fin, source_type="finance.dividend").exists()
    terminal = MoneyAccount.objects.get(company=fin, kind=MoneyAccount.Kind.CLEARING)
    with pytest.raises(DomainError):
        partners.pay_dividend(dividend, by=boss, account=terminal, paid_on=today)
    dollars = MoneyAccountFactory(company=fin, name="Dollar", kind="safe", currency="USD")
    with pytest.raises(DomainError):
        partners.pay_dividend(dividend, by=boss, account=dollars, paid_on=today)

    partners.cancel_dividend(dividend, by=boss, reason="Kattaroq summa kerak emas")
    dividend.refresh_from_db()
    assert dividend.status == Dividend.Status.CANCELLED
    with pytest.raises(DomainError):
        partners.pay_dividend(dividend, by=boss, account=bank, paid_on=today)


def test_the_suggestion_is_the_profit_at_most_what_is_safe(fin, boss, bank, two, quarter):
    sale(fin, boss, bank, "40000000", quarter[0] + timedelta(days=3))

    data = partners.suggest(fin, quarter[0], quarter[1])

    assert data["profit"] == D("40000000.00")
    assert data["limited_by"] == "profit"
    assert data["amount"] == D("40000000.00")
    assert [(row["name"], row["amount"]) for row in data["split"]] == [
        ("Dilnoza Karimova", D("24000000.00")),
        ("Rustam Qodirov", D("16000000.00")),
    ]
    partners.create_dividend(
        fin, by=boss, period_start=quarter[0], period_end=quarter[1], amount="30000000"
    )
    assert partners.suggest(fin, quarter[0], quarter[1])["amount"] == D("10000000.00")

    owner_draw.update_settings(fin, by=boss, cash_buffer="335000000")  # leaves 5 mln safe
    data = partners.suggest(fin, quarter[0], quarter[1])
    assert data["limited_by"] == "safe"
    assert data["amount"] == D("5000000.00")


def test_profit_share_weighs_the_days_each_share_was_held(fin, boss, bank, two, quarter):
    start, end = quarter
    sale(fin, boss, bank, "90000000", start + timedelta(days=1))
    middle = start + timedelta(days=(end - start).days // 2)
    partners.set_partners(
        fin,
        by=boss,
        effective_on=middle,
        rows=[
            {"membership": boss, "name": "", "share": "40"},
            {"membership": None, "name": "Rustam Qodirov", "share": "60"},
        ],
    )
    dividend = partners.create_dividend(
        fin, by=boss, period_start=start, period_end=end, amount="10000000"
    )
    partners.pay_dividend(dividend, by=boss, account=bank, paid_on=end, line_ids=None)

    data = partners.profit_share(fin, start, end)

    days = (end - start).days + 1
    before = (middle - start).days
    after = days - before
    dilnoza, rustam = sorted(data["partners"], key=lambda row: row["name"])
    assert dilnoza["share"] == (D(60 * before + 40 * after) / days).quantize(D("0.01"))
    assert dilnoza["profit"] + rustam["profit"] == pytest.approx(D("90000000"), abs=D("0.02"))
    # The round used the shares of the quarter's last day: 40 / 60.
    assert dilnoza["dividends_paid"] == D("4000000.00")
    assert rustam["dividends_paid"] == D("6000000.00")
    assert data["unassigned_share"] == 0


# The endpoints ---------------------------------------------------------------------------------


def test_partners_through_the_api(fin, boss, owner_api, today):
    client = owner_api(boss)

    wrong = client.put(
        url(fin, "partners/"),
        {"effective_on": today.isoformat(), "partners": [{"member": boss.pk, "share": "70"}]},
        format="json",
    )
    assert wrong.status_code == 400
    response = client.put(
        url(fin, "partners/"),
        {
            "effective_on": today.isoformat(),
            "partners": [
                {"member": boss.pk, "share": "60"},
                {"name": "Rustam Qodirov", "share": "40"},
            ],
        },
        format="json",
    )
    assert response.status_code == 200
    data = response.json()
    assert [(row["name"], row["share"]) for row in data["current"]] == [
        ("Dilnoza Karimova", "60.00"),
        ("Rustam Qodirov", "40.00"),
    ]
    assert data["since"] == today.isoformat()
    assert {"id": boss.pk, "name": "Dilnoza Karimova"} in data["people"]
    assert client.get(url(fin, "owner-money/")).json()["partners"] == 2


def test_a_dividend_round_through_the_api(fin, boss, bank, two, quarter, owner_api, today):
    client = owner_api(boss)
    sale(fin, boss, bank, "20000000", quarter[0] + timedelta(days=2))
    period = {"from": quarter[0].isoformat(), "to": quarter[1].isoformat()}

    suggested = client.get(url(fin, "dividends/suggest/"), period).json()
    assert suggested["amount"] == "20000000.00"
    made = client.post(
        url(fin, "dividends/"),
        {
            "period_start": quarter[0].isoformat(),
            "period_end": quarter[1].isoformat(),
            "amount": "20000000",
            "note": "III chorak",
        },
        format="json",
    )
    assert made.status_code == 201
    pk = made.json()["id"]
    assert [line["amount"] for line in made.json()["lines"]] == ["12000000.00", "8000000.00"]
    changed = client.patch(url(fin, f"dividends/{pk}/"), {"amount": "10000000"}, format="json")
    assert [line["amount"] for line in changed.json()["lines"]] == ["6000000.00", "4000000.00"]
    paid = client.post(
        url(fin, f"dividends/{pk}/pay/"),
        {"account": bank.pk, "paid_on": today.isoformat()},
        format="json",
    )
    assert paid.status_code == 200
    assert paid.json()["status"] == "paid"
    assert paid.json()["paid_amount"] == "10000000.00"
    assert all(line["account"] == {"id": bank.pk, "name": "Bank"} for line in paid.json()["lines"])
    line = paid.json()["lines"][0]["id"]
    undone = client.post(
        url(fin, f"dividends/{pk}/lines/{line}/undo/"), {"reason": "Xato"}, format="json"
    )
    assert undone.json()["status"] == "partly_paid"
    listed = client.get(url(fin, "dividends/")).json()
    assert [row["id"] for row in listed] == [pk]
    share = client.get(url(fin, "partners/profit-share/"), period).json()
    assert share["profit"] == "20000000.00"
    assert {row["name"] for row in share["partners"]} == {"Dilnoza Karimova", "Rustam Qodirov"}


def test_dividends_of_another_company_are_not_found(
    fin, boss, two, quarter, owner_api, other_company, member
):
    dividend = partners.create_dividend(
        fin, by=boss, period_start=quarter[0], period_end=quarter[1], amount="1000000"
    )
    stranger = member(other_company, "Owner")
    other_company.features = ["finance"]
    other_company.save(update_fields=["features"])
    client = owner_api(stranger)
    path = f"/api/v1/owner/companies/{other_company.pk}/finance/dividends/{dividend.pk}/"
    assert client.get(path).status_code == 404
    assert client.post(f"{path}cancel/", {"reason": "x"}, format="json").status_code == 404
