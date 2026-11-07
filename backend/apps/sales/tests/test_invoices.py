"""Invoices (PLAN-OWNER §3.8, §11.4's J acceptance, §14.7): the fixed create_invoice signature,
numbers unique and in order, issue opens one receivable and takes the stock (one row per batch
with series and expiry), the Rx wholesale cap warning, partial and other-currency payments, void
only before payment (the goods go back on sale), the PDF, sending it, and the endpoints."""

import inspect
from datetime import timedelta
from decimal import Decimal
from unittest import mock

import pytest

from apps.core.exceptions import DomainError
from apps.finance import services as finance
from apps.finance.models import LIVE_STATUSES, Debt, ExchangeRate, MoneyAccount, Transaction
from apps.inventory.services import Allocation
from apps.inventory.tests.factories import ProductFactory, StockBatchFactory
from apps.members.permissions import Perm
from apps.sales import services
from apps.sales.models import SalesSettings
from apps.sales.tests.factories import make_member, scoped_role


@pytest.fixture
def wholesale(shop):
    shop.clinic = services.create_customer(
        shop.company, by=shop.owner, name="Shifo klinikasi", phone="71 200 11 22", kind="clinic"
    )
    shop.drug = ProductFactory(
        company=shop.company,
        name="Amoksitsillin 500 mg kapsula №16",
        units_per_pack=2,
        rx_required=True,
        reference_price=Decimal("30000.00"),
        mxik_code="03004001001000000",
        vat_percent=Decimal("12.00"),
    )
    shop.bandage = ProductFactory(
        company=shop.company, name="Bint 7×14", units_per_pack=1, track_stock=False
    )
    return shop


def draft(shop, **extra):
    lines = extra.pop(
        "lines",
        [
            {"product_id": shop.drug.pk, "name": "", "quantity": "10", "price": "28000"},
            {"name": "Delivery", "quantity": "1", "price": "20000", "discount": "5000"},
        ],
    )
    branch = extra.pop("branch", shop.branch)
    return services.create_invoice(
        shop.company,
        by=shop.owner,
        counterparty=shop.clinic,
        lines=lines,
        branch=branch,
        **extra,
    )


def test_create_invoice_keeps_its_fixed_signature():
    parameters = inspect.signature(services.create_invoice).parameters
    assert list(parameters) == [
        "company",
        "by",
        "counterparty",
        "lines",
        "branch",
        "currency",
        "notes",
    ]
    assert parameters["branch"].default is None and parameters["currency"].default == "UZS"
    assert parameters["notes"].default == ""


def test_a_draft_adds_up_and_moves_nothing(wholesale):
    invoice = draft(wholesale)
    assert invoice.status == "draft" and invoice.number == ""
    assert invoice.subtotal == Decimal("300000.00") and invoice.discount == Decimal("5000.00")
    assert invoice.total == Decimal("295000.00")
    assert [line.name for line in invoice.lines.all()] == [wholesale.drug.name, "Delivery"]
    assert not Debt.objects.filter(counterparty=wholesale.clinic).exists()
    supplier = finance.create_counterparty(
        wholesale.company, by=wholesale.owner, name="Ko‘kterak Farm", kind="supplier"
    )
    with pytest.raises(DomainError):
        services.create_invoice(
            wholesale.company,
            by=wholesale.owner,
            counterparty=supplier,
            lines=[{"name": "x", "quantity": 1, "price": 1}],
        )


def test_issue_numbers_in_order_opens_one_receivable_and_takes_the_stock(wholesale):
    first_batch = StockBatchFactory(
        product=wholesale.drug, series="230415", unit_cost=Decimal("25000.00")
    )
    second_batch = StockBatchFactory(
        product=wholesale.drug, series="230520", unit_cost=Decimal("26000.00")
    )
    allocations = [
        Allocation(first_batch.pk, Decimal("12"), Decimal("12500.00")),
        Allocation(second_batch.pk, Decimal("8"), Decimal("13000.00")),
    ]
    invoice = draft(wholesale)
    with mock.patch("apps.inventory.services.deduct", return_value=allocations) as deduct:
        invoice = services.issue_invoice(invoice, by=wholesale.owner)
    assert invoice.number == "INV-CHL-0001" and invoice.status == "issued"
    args, kwargs = deduct.call_args
    assert args[1] == wholesale.drug and args[2] == Decimal("20.000")  # 10 packs of 2 parts
    assert kwargs["document"] == ("sales.invoice", invoice.pk)
    rows = list(invoice.lines.filter(product=wholesale.drug).order_by("pk"))
    assert [(r.series, r.quantity) for r in rows] == [
        ("230415", Decimal("6.000")),
        ("230520", Decimal("4.000")),
    ]
    assert sum(r.total for r in rows) == Decimal("280000.00")
    assert rows[0].mxik_code == "03004001001000000" and rows[0].vat_percent == Decimal("12.00")
    assert rows[0].expires_on == first_batch.expires_on
    # One receivable, its income booked now, due after the terms.
    debt = invoice.debt
    assert debt.amount == Decimal("295000.00") and debt.direction == "receivable"
    assert debt.source_type == "sales.invoice" and debt.source_id == invoice.pk
    terms = SalesSettings.objects.get(company=wholesale.company).invoice_terms_days
    assert invoice.due_on == invoice.issued_on + timedelta(days=terms)
    assert (
        Transaction.objects.filter(debt=debt, kind="income", status__in=LIVE_STATUSES).count() == 1
    )
    with pytest.raises(DomainError):
        services.issue_invoice(invoice, by=wholesale.owner)
    second = services.issue_invoice(
        draft(wholesale, lines=[{"name": "Service", "quantity": 1, "price": 1000}]),
        by=wholesale.owner,
    )
    assert second.number == "INV-CHL-0002"


def test_an_rx_line_above_the_wholesale_cap_warns_but_issues(wholesale):
    batch = StockBatchFactory(product=wholesale.drug, unit_cost=Decimal("22000.00"))
    # 22 000 + 15 % = 25 300 a pack, under the reference price of 30 000: 28 000 is above it.
    with mock.patch(
        "apps.inventory.services.deduct",
        return_value=[Allocation(batch.pk, Decimal("20"), Decimal("11000.00"))],
    ):
        invoice = services.issue_invoice(draft(wholesale), by=wholesale.owner)
    assert invoice.status == "issued"
    [warning] = invoice.warnings
    assert warning["cap"] == "25300.00" and warning["price"] == "28000.00"


def test_stock_lines_need_the_branch_the_goods_leave_from(wholesale):
    invoice = draft(wholesale, branch=None)
    with pytest.raises(DomainError):
        services.issue_invoice(invoice, by=wholesale.owner)


def test_partial_and_other_currency_payments(wholesale):
    invoice = services.issue_invoice(draft(wholesale), by=wholesale.owner)
    bank = finance.create_account(
        wholesale.company, by=wholesale.owner, kind="bank", name="Bank", currency="UZS"
    )
    invoice = services.record_invoice_payment(
        invoice, by=wholesale.owner, account=bank, amount="95000", paid_on=invoice.issued_on
    )
    assert invoice.status == "partly_paid"
    ExchangeRate.objects.create(currency="USD", date=invoice.issued_on, rate=Decimal("12500"))
    dollars = finance.create_account(
        wholesale.company, by=wholesale.owner, kind="bank", name="Bank USD", currency="USD"
    )
    invoice = services.record_invoice_payment(
        invoice,
        by=wholesale.owner,
        account=dollars,
        amount="16",
        paid_on=invoice.issued_on,
        debt_amount="200000",
    )
    assert invoice.status == "paid"
    with pytest.raises(DomainError):
        services.void_invoice(invoice, by=wholesale.owner, reason="Too late")


def test_void_before_payment_cancels_the_receivable_and_puts_the_goods_back(wholesale):
    batch = StockBatchFactory(product=wholesale.drug)
    with mock.patch(
        "apps.inventory.services.deduct",
        return_value=[Allocation(batch.pk, Decimal("20"), Decimal("5000.00"))],
    ):
        invoice = services.issue_invoice(draft(wholesale), by=wholesale.owner)
    with mock.patch("apps.inventory.services.restock") as restock:
        invoice = services.void_invoice(invoice, by=wholesale.owner, reason="Clinic cancelled")
    assert invoice.status == "void"
    invoice.debt.refresh_from_db()
    assert invoice.debt.status == "cancelled"
    [call] = restock.call_args_list
    assert call.kwargs["status"] == "sellable" and call.kwargs["document"] == (
        "sales.invoice",
        invoice.pk,
    )
    assert call.args[1] == [Allocation(batch.pk, Decimal("20.000"), Decimal("5000.00"))]


def test_the_pdf_prints_mxik_vat_and_says_it_is_not_an_e_invoice(wholesale):
    invoice = services.issue_invoice(draft(wholesale), by=wholesale.owner)
    data = services.invoice_pdf(invoice, language="en")
    assert data.startswith(b"%PDF")
    from apps.sales.invoice_print import context

    printed = context(invoice)
    assert printed["lines"][0]["mxik"] == "03004001001000000"
    assert printed["lines"][0]["vat_percent"] == "12"
    assert printed["customer"]["name"] == "Shifo klinikasi"


def test_sending_goes_to_the_customers_telegram_or_gives_a_link(
    wholesale, django_capture_on_commit_callbacks
):
    invoice = services.issue_invoice(draft(wholesale), by=wholesale.owner)
    sent = services.send_invoice(invoice, by=wholesale.owner)
    assert sent["delivered"] == "link" and sent["url"].startswith("/api/v1/files/")
    from apps.accounts.models import User

    User.objects.create(username="shifo", telegram_id=777000, telegram_username="shifo_klinika")
    services.update_customer(
        wholesale.clinic, by=wholesale.owner, telegram_username="@Shifo_Klinika"
    )
    with (
        mock.patch("apps.notifications.telegram.send_document") as send_document,
        django_capture_on_commit_callbacks(execute=True),
    ):
        sent = services.send_invoice(invoice, by=wholesale.owner)
    assert sent == {"delivered": "telegram"}
    assert send_document.call_args.args[:2] == ("employee", 777000)
    invoice.refresh_from_db()
    assert invoice.sent_at is not None and invoice.pdf


def test_invoice_endpoints_check_permissions(wholesale, owner_api, other_company, member):
    url = f"/api/v1/owner/companies/{wholesale.company.pk}/sales/invoices/"
    client = owner_api(wholesale.owner)
    made = client.post(
        url,
        {
            "customer_id": wholesale.clinic.pk,
            "branch_id": wholesale.branch.pk,
            "lines": [{"name": "Analysis", "quantity": "2", "price": "50000"}],
        },
        format="json",
    )
    assert made.status_code == 201, made.content
    invoice_id = made.json()["id"]
    assert client.post(f"{url}{invoice_id}/issue/").json()["number"] == "INV-CHL-0001"
    assert client.get(url).json()["count"] == 1
    assert client.get(f"{url}{invoice_id}/pdf/").json()["url"].startswith("/api/v1/files/")
    # sales.view reads but can't write; payments need finance.record.
    viewer = make_member(wholesale.company, "Owner")
    viewer.role = scoped_role(wholesale.company, Perm.SALES_VIEW, Perm.BRANCHES_ALL)
    viewer.save(update_fields=["role"])
    assert owner_api(viewer).get(f"{url}{invoice_id}/").status_code == 200
    assert (
        owner_api(viewer)
        .post(f"{url}{invoice_id}/void/", {"reason": "x"}, format="json")
        .status_code
        == 403
    )
    biller = make_member(wholesale.company, "Owner")
    biller.role = scoped_role(wholesale.company, Perm.SALES_INVOICES, Perm.BRANCHES_ALL)
    biller.save(update_fields=["role"])
    account = MoneyAccount.objects.filter(company=wholesale.company, is_active=True).first()
    paid = owner_api(biller).post(
        f"{url}{invoice_id}/payments/",
        {"account_id": account.pk, "amount": "1000", "paid_on": made.json()["created_at"][:10]},
        format="json",
    )
    assert paid.status_code == 403
    stranger = member(other_company, "Owner")
    assert owner_api(stranger).get(f"{url}{invoice_id}/").status_code == 404


def test_a_distributors_sales_start_in_invoices_mode(db):
    from apps.companies.tests.factories import CompanyFactory
    from apps.sales.conf import get_settings

    distributor = CompanyFactory(business_kind="distributor", features=["sales"])
    assert get_settings(distributor).mode == "invoices"
    pharmacy = CompanyFactory(features=["sales"])
    assert get_settings(pharmacy).mode == "shift_totals"
