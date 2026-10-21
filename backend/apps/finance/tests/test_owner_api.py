"""The finance owner endpoints (§4.7): permissions, tenancy, branch scope, hidden salary detail,
money as strings, and every write going through the services."""

import io
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from PIL import Image

from apps.audit.models import AuditLog
from apps.companies.models import Branch
from apps.finance import conf, queries, services
from apps.finance.models import (
    Category,
    CompanyRate,
    Counterparty,
    Debt,
    MoneyAccount,
    Receipt,
    Transaction,
)
from apps.finance.tests.factories import (
    CounterpartyFactory,
    ExchangeRateFactory,
    MoneyAccountFactory,
)
from apps.members.permissions import Perm

pytestmark = pytest.mark.django_db


def url(company, path: str) -> str:
    return f"/api/v1/owner/companies/{company.pk}/finance/{path}"


@pytest.fixture
def today(fin):
    return queries.local_today(fin)


@pytest.fixture
def boss(fin, member):
    return member(fin, "Owner", first_name="Dilnoza")


@pytest.fixture
def client(owner_api, boss):
    return owner_api(boss)


@pytest.fixture
def kassa(fin):
    return MoneyAccount.objects.get(company=fin, kind=MoneyAccount.Kind.CASH)


def jpeg() -> io.BytesIO:
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 120, 60)).save(out, "JPEG")
    out.seek(0)
    out.name = "receipt.jpg"
    return out


def expense(company, by, account, amount, day, category="rent", **fields):
    return services.record_transaction(
        company,
        by=by,
        kind="expense",
        amount=Decimal(amount),
        occurred_on=day,
        account=account,
        category=category,
        **fields,
    )


def income(company, by, account, amount, day, category="sales", **fields):
    return services.record_transaction(
        company,
        by=by,
        kind="income",
        amount=Decimal(amount),
        occurred_on=day,
        account=account,
        category=category,
        **fields,
    )


READS = [
    "overview/",
    "options/",
    "accounts/",
    "categories/",
    "counterparties/",
    "transactions/",
    "transfers/",
    "debts/",
    "debts/summary/",
    "rates/",
    "reports/pnl/",
    "reports/cash-flow/",
    "reports/balances/",
    "reports/debts-aging/",
    "settings/",
]


class TestAccess:
    @pytest.mark.parametrize("path", READS)
    def test_the_owner_reads_every_endpoint(self, client, fin, path):
        assert client.get(url(fin, path)).status_code == 200

    @pytest.mark.parametrize("path", ["overview/", "accounts/", "transactions/", "debts/"])
    def test_another_companys_id_answers_404(self, owner_api, other_company, member, fin, path):
        stranger = member(other_company, "Owner")
        assert owner_api(stranger).get(url(fin, path)).status_code == 404

    @pytest.mark.parametrize(
        "path", ["overview/", "accounts/", "transactions/", "debts/", "reports/pnl/"]
    )
    def test_a_manager_without_finance_permissions_gets_403(self, owner_api, fin, member, path):
        manager = member(fin, "Manager")
        assert owner_api(manager).get(url(fin, path)).status_code == 403

    def test_the_module_switched_off_answers_404(self, client, fin):
        fin.features = []
        fin.save(update_fields=["features"])
        assert client.get(url(fin, "overview/")).status_code == 404

    def test_a_mini_app_token_is_refused(self, api_as, boss, fin):
        assert api_as(boss).get(url(fin, "overview/")).status_code == 401

    def test_settings_need_finance_manage(self, owner_api, fin, role, person):
        viewer = person(fin, role(fin, "Viewer", [Perm.FINANCE_VIEW, Perm.BRANCHES_ALL]))
        assert owner_api(viewer).get(url(fin, "settings/")).status_code == 403
        assert owner_api(viewer).get(url(fin, "overview/")).status_code == 200


class TestOverview:
    def test_money_is_strings_and_month_compares_with_last(self, client, fin, boss, kassa, today):
        income(fin, boss, kassa, "1500000", today)
        expense(fin, boss, kassa, "400000", today)
        data = client.get(url(fin, "overview/")).json()
        assert data["month"]["income"] == "1500000.00"
        assert data["month"]["expense"] == "400000.00"
        assert data["month"]["profit"] == "1100000.00"
        assert data["cash"]["total"] == "1100000.00"
        assert data["has_ledger"] is True
        assert isinstance(data["receivable"]["total"], str)

    def test_a_write_refreshes_the_cached_overview(
        self, client, fin, boss, kassa, today, django_capture_on_commit_callbacks
    ):
        assert client.get(url(fin, "overview/")).json()["month"]["income"] == "0.00"
        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(
                url(fin, "transactions/"),
                {
                    "kind": "income",
                    "amount": "250000",
                    "occurred_on": today.isoformat(),
                    "account": kassa.pk,
                    "category": Category.objects.get(company=fin, system_code="sales").pk,
                },
                format="json",
            )
        assert response.status_code == 201
        assert client.get(url(fin, "overview/")).json()["month"]["income"] == "250000.00"


class TestAccounts:
    def test_list_has_balances_sparklines_and_totals(self, client, fin, boss, kassa, today, usd):
        ExchangeRateFactory(date=today, rate=Decimal("12800"))
        dollars = MoneyAccountFactory(company=fin, name="Dollars", kind="safe", currency="USD")
        income(fin, boss, kassa, "300000", today)
        services.record_transaction(
            fin, by=boss, kind="opening", amount=Decimal("10"), occurred_on=today, account=dollars
        )
        data = client.get(url(fin, "accounts/")).json()
        rows = {row["name"]: row for row in data["accounts"]}
        assert rows[kassa.name]["balance"] == "300000.00"
        assert rows[kassa.name]["spark"][-1] == "300000.00"
        assert len(rows[kassa.name]["spark"]) == 30
        assert rows["Dollars"]["base_balance"] == "128000.00"
        assert data["totals"]["base"] == "428000.00"
        assert {row["currency"] for row in data["totals"]["by_currency"]} == {"UZS", "USD"}

    def test_create_with_an_opening_balance_and_operators(self, client, fin, member, today):
        cashier = member(fin, "Cashier")
        response = client.post(
            url(fin, "accounts/"),
            {
                "name": "Hamkorbank",
                "kind": "bank",
                "currency": "UZS",
                "bank_name": "Hamkorbank",
                "number_last4": "1234",
                "operators": [cashier.pk],
                "opening_balance": "5000000",
                "opening_on": today.isoformat(),
            },
            format="json",
        )
        assert response.status_code == 201, response.json()
        data = response.json()
        assert data["balance"] == "5000000.00"
        assert data["operators"] == [{"id": cashier.pk, "name": str(cashier)}]
        account = MoneyAccount.objects.get(pk=data["id"])
        assert Transaction.objects.get(account=account).kind == "opening"

    def test_archive_needs_a_zero_balance(self, client, fin, boss, kassa, today):
        income(fin, boss, kassa, "1000", today)
        response = client.post(url(fin, f"accounts/{kassa.pk}/archive/"))
        assert response.status_code == 400
        empty = MoneyAccountFactory(company=fin, name="Old card", kind="card")
        assert client.post(url(fin, f"accounts/{empty.pk}/archive/")).json()["is_active"] is False

    def test_a_branch_scoped_member_sees_only_their_branchs_accounts(
        self, owner_api, fin, role, person
    ):
        main = fin.branches.first()
        other = Branch.objects.create(company=fin, name="Yunusobod")
        here = MoneyAccountFactory(company=fin, name="Here", branch=main)
        there = MoneyAccountFactory(company=fin, name="There", branch=other)
        viewer = person(fin, role(fin, "Branch accountant", [Perm.FINANCE_VIEW]), branches=[main])
        names = {
            row["name"] for row in owner_api(viewer).get(url(fin, "accounts/")).json()["accounts"]
        }
        assert "Here" in names
        assert "There" not in names
        # Company-level accounts (no branch) are for people who see every branch.
        assert MoneyAccount.objects.get(company=fin, kind="cash", branch=None).name not in names
        assert owner_api(viewer).get(url(fin, f"accounts/{there.pk}/")).status_code == 404
        assert owner_api(viewer).get(url(fin, f"accounts/{here.pk}/")).status_code == 200

    def test_a_recorder_sees_the_accounts_they_operate(self, owner_api, fin, role, person, kassa):
        recorder = person(fin, role(fin, "Recorder", [Perm.FINANCE_RECORD]))
        kassa.operators.add(recorder)
        rows = owner_api(recorder).get(url(fin, "accounts/")).json()["accounts"]
        assert [row["id"] for row in rows] == [kassa.pk]
        assert rows[0]["can_record"] is True

    def test_statement_has_running_balances(self, client, fin, boss, kassa, today):
        income(fin, boss, kassa, "1000000", today - timedelta(days=5))
        expense(fin, boss, kassa, "200000", today - timedelta(days=2))
        income(fin, boss, kassa, "50000", today)
        data = client.get(
            url(fin, f"accounts/{kassa.pk}/statement/"),
            {"from": (today - timedelta(days=3)).isoformat(), "to": today.isoformat()},
        ).json()
        assert data["opening"] == "1000000.00"
        assert [line["running_balance"] for line in data["lines"]] == ["800000.00", "850000.00"]
        assert data["closing"] == "850000.00"
        assert data["money_out"] == "200000.00"


class TestTransactions:
    def test_record_an_expense(self, client, fin, kassa, boss, today):
        income(fin, boss, kassa, "1000000", today)
        rent = Category.objects.get(company=fin, system_code="rent")
        party = CounterpartyFactory(company=fin, name="Landlord")
        response = client.post(
            url(fin, "transactions/"),
            {
                "kind": "expense",
                "amount": "350000",
                "occurred_on": today.isoformat(),
                "account": kassa.pk,
                "category": rent.pk,
                "counterparty": party.pk,
                "description": "October rent",
            },
            format="json",
        )
        assert response.status_code == 201, response.json()
        data = response.json()
        assert data["amount"] == "-350000.00"
        assert data["base_amount"] == "-350000.00"
        assert data["counterparty"] == {"id": party.pk, "name": "Landlord"}
        assert data["can_edit"] is True
        kassa.refresh_from_db()
        assert kassa.balance == Decimal("650000.00")
        assert AuditLog.objects.filter(action="finance.transaction_recorded").exists()

    def test_receipts_arrive_with_the_entry_and_open_through_signed_links(
        self, client, fin, kassa, boss, today
    ):
        income(fin, boss, kassa, "1000000", today)
        rent = Category.objects.get(company=fin, system_code="rent")
        pdf = io.BytesIO(b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF")
        pdf.name = "bill.pdf"
        response = client.post(
            url(fin, "transactions/"),
            {
                "kind": "expense",
                "amount": "100000",
                "occurred_on": today.isoformat(),
                "account": kassa.pk,
                "category": rent.pk,
                "receipts": [jpeg(), pdf],
            },
            format="multipart",
        )
        assert response.status_code == 201, response.json()
        receipts = response.json()["receipts"]
        assert [r["content_type"] for r in receipts] == ["image/jpeg", "application/pdf"]
        assert receipts[0]["thumb_url"]
        assert receipts[1]["thumb_url"] is None
        assert client.get(receipts[0]["url"]).status_code == 200

    def test_a_receipt_is_required_above_the_threshold(self, client, fin, kassa, boss, today):
        income(fin, boss, kassa, "10000000", today)
        settings_row = conf.get_settings(fin)
        settings_row.receipt_required_over = Decimal("1000000")
        settings_row.save()
        payload = {
            "kind": "expense",
            "amount": "2000000",
            "occurred_on": today.isoformat(),
            "account": kassa.pk,
            "category": Category.objects.get(company=fin, system_code="goods").pk,
        }
        response = client.post(url(fin, "transactions/"), payload, format="json")
        assert response.status_code == 400
        assert "receipt" in response.json()["detail"]
        assert not Transaction.objects.filter(kind="expense").exists()
        upload = client.post(url(fin, "receipts/"), {"file": jpeg()}, format="multipart")
        assert upload.status_code == 201
        payload["receipt_ids"] = [upload.json()["id"]]
        response = client.post(url(fin, "transactions/"), payload, format="json")
        assert response.status_code == 201, response.json()
        assert len(response.json()["receipts"]) == 1

    def test_someone_elses_uploaded_receipt_cant_be_linked(
        self, client, fin, kassa, boss, today, member, owner_api
    ):
        accountant = member(fin, "Accountant")
        upload = owner_api(accountant).post(
            url(fin, "receipts/"), {"file": jpeg()}, format="multipart"
        )
        response = client.post(
            url(fin, "transactions/"),
            {
                "kind": "income",
                "amount": "1000",
                "occurred_on": today.isoformat(),
                "account": kassa.pk,
                "category": Category.objects.get(company=fin, system_code="sales").pk,
                "receipt_ids": [upload.json()["id"]],
            },
            format="json",
        )
        assert response.status_code == 400

    def test_filters(self, client, fin, kassa, boss, today):
        goods = Category.objects.get(company=fin, system_code="goods")
        drinks = services.create_category(
            fin, by=boss, name="Medicines", kind="expense", parent=goods
        )
        income(fin, boss, kassa, "5000000", today)
        expense(
            fin,
            boss,
            kassa,
            "120000",
            today,
            category=drinks,
            description="Paratsetamol 500 mg, 20 boxes",
        )
        expense(fin, boss, kassa, "900000", today, category="rent")
        rows = client.get(url(fin, "transactions/"), {"category": goods.pk}).json()["results"]
        assert [row["description"] for row in rows] == ["Paratsetamol 500 mg, 20 boxes"]
        rows = client.get(url(fin, "transactions/"), {"kind": "expense", "min": "500000"}).json()
        assert [row["amount"] for row in rows["results"]] == ["-900000.00"]
        assert client.get(url(fin, "transactions/"), {"q": "paratsetamol"}).json()["count"] == 1
        page = client.get(url(fin, "transactions/")).json()
        assert page["summary"] == {
            "money_in": "5000000.00",
            "money_out": "1020000.00",
            "net": "3980000.00",
            "currency": "UZS",
        }
        assert (
            client.get(url(fin, "transactions/"), {"ordering": "amount"}).json()["results"][0][
                "amount"
            ]
            == "-900000.00"
        )

    def test_the_creator_edits_within_24_hours_others_need_finance_manage(
        self, owner_api, fin, role, person, kassa, boss, today
    ):
        recorder = person(fin, role(fin, "Recorder", [Perm.FINANCE_RECORD]))
        kassa.operators.add(recorder)
        income(fin, boss, kassa, "1000000", today)
        own = expense(fin, recorder, kassa, "10000", today)
        theirs = expense(fin, boss, kassa, "20000", today)
        api = owner_api(recorder)
        assert (
            api.patch(
                url(fin, f"transactions/{own.pk}/"), {"description": "Stationery"}, format="json"
            ).status_code
            == 200
        )
        assert (
            api.patch(
                url(fin, f"transactions/{theirs.pk}/"), {"description": "x"}, format="json"
            ).status_code
            == 403
        )
        Transaction.objects.filter(pk=own.pk).update(created_at=timezone.now() - timedelta(days=2))
        assert (
            api.patch(
                url(fin, f"transactions/{own.pk}/"), {"description": "Y"}, format="json"
            ).status_code
            == 403
        )

    def test_editing_the_amount_and_account_moves_the_balances(
        self, client, fin, kassa, bank, boss, today
    ):
        income(fin, boss, kassa, "1000000", today)
        income(fin, boss, bank, "1000000", today)
        row = expense(fin, boss, kassa, "100000", today)
        response = client.patch(
            url(fin, f"transactions/{row.pk}/"),
            {"amount": "250000", "account": bank.pk},
            format="json",
        )
        assert response.status_code == 200, response.json()
        assert response.json()["amount"] == "-250000.00"
        kassa.refresh_from_db()
        bank.refresh_from_db()
        assert kassa.balance == Decimal("1000000.00")
        assert bank.balance == Decimal("750000.00")
        log = AuditLog.objects.filter(action="finance.transaction_updated").get()
        assert log.details["changes"]["amount"] == ["-100000.00", "-250000.00"]

    def test_a_row_from_another_module_only_takes_a_new_description(
        self, client, fin, kassa, boss, today, src
    ):
        row = income(fin, boss, kassa, "1000", today, source=src(7))
        assert (
            client.patch(
                url(fin, f"transactions/{row.pk}/"), {"amount": "5"}, format="json"
            ).status_code
            == 400
        )
        assert (
            client.patch(
                url(fin, f"transactions/{row.pk}/"), {"description": "Z"}, format="json"
            ).status_code
            == 200
        )

    def test_void_and_bulk(self, client, fin, kassa, boss, today):
        income(fin, boss, kassa, "1000000", today)
        rows = [expense(fin, boss, kassa, "1000", today) for _ in range(3)]
        response = client.post(
            url(fin, f"transactions/{rows[0].pk}/void/"), {"reason": "Typo"}, format="json"
        )
        assert response.json()["status"] == "void"
        marketing = Category.objects.get(company=fin, system_code="marketing")
        response = client.post(
            url(fin, "transactions/bulk/"),
            {
                "ids": [rows[0].pk, rows[1].pk, 999999],
                "action": "categorize",
                "category": marketing.pk,
            },
            format="json",
        )
        results = {item["id"]: item for item in response.json()["results"]}
        assert results[rows[1].pk]["ok"] is True
        assert results[rows[0].pk]["ok"] is False  # already void
        assert results[999999]["ok"] is False
        response = client.post(
            url(fin, "transactions/bulk/"),
            {"ids": [rows[1].pk, rows[2].pk], "action": "void", "reason": "Duplicates"},
            format="json",
        )
        assert all(item["ok"] for item in response.json()["results"])
        kassa.refresh_from_db()
        assert kassa.balance == Decimal("1000000.00")

    def test_the_period_lock_is_enforced(self, client, fin, kassa, boss, today):
        old = income(fin, boss, kassa, "1000", today - timedelta(days=10))
        assert (
            client.post(
                url(fin, "settings/lock/"),
                {"until": (today - timedelta(days=5)).isoformat()},
                format="json",
            ).status_code
            == 200
        )
        response = client.post(
            url(fin, "transactions/"),
            {
                "kind": "income",
                "amount": "5",
                "occurred_on": (today - timedelta(days=6)).isoformat(),
                "account": kassa.pk,
                "category": Category.objects.get(company=fin, system_code="sales").pk,
            },
            format="json",
        )
        assert response.status_code == 400
        assert (
            client.patch(
                url(fin, f"transactions/{old.pk}/"), {"description": "x"}, format="json"
            ).status_code
            == 400
        )
        assert (
            client.post(
                url(fin, f"transactions/{old.pk}/void/"), {"reason": "x"}, format="json"
            ).status_code
            == 400
        )
        assert client.get(url(fin, f"transactions/{old.pk}/")).json()["can_edit"] is False

    def test_salary_detail_is_hidden_without_payroll_view(
        self, owner_api, fin, role, person, kassa, boss, today, member
    ):
        worker = member(fin, "Employee", first_name="Alisher")
        income(fin, boss, kassa, "9000000", today)
        expense(
            fin,
            boss,
            kassa,
            "4300000",
            today,
            category="salaries",
            membership=worker,
            description="Alisher, October",
        )
        viewer = person(fin, role(fin, "Bookkeeper", [Perm.FINANCE_VIEW, Perm.BRANCHES_ALL]))
        rows = (
            owner_api(viewer).get(url(fin, "transactions/"), {"kind": "expense"}).json()["results"]
        )
        assert rows[0]["masked"] is True
        assert rows[0]["membership"] is None
        assert rows[0]["description"] == ""
        assert rows[0]["amount"] == "-4300000.00"  # the totals still add up
        assert (
            owner_api(viewer).get(url(fin, "transactions/"), {"q": "Alisher"}).json()["count"] == 0
        )
        payroll = person(
            fin, role(fin, "Payroll", [Perm.FINANCE_VIEW, Perm.BRANCHES_ALL, Perm.PAYROLL_VIEW])
        )
        rows = (
            owner_api(payroll).get(url(fin, "transactions/"), {"kind": "expense"}).json()["results"]
        )
        assert rows[0]["membership"]["id"] == worker.pk

    def test_rows_of_other_branches_are_invisible(self, owner_api, fin, role, person, boss, today):
        main = fin.branches.first()
        other = Branch.objects.create(company=fin, name="Yunusobod")
        here = MoneyAccountFactory(company=fin, name="Here", branch=main)
        there = MoneyAccountFactory(company=fin, name="There", branch=other)
        income(fin, boss, here, "1000", today)
        hidden = income(fin, boss, there, "2000", today)
        viewer = person(fin, role(fin, "Branch", [Perm.FINANCE_VIEW]), branches=[main])
        data = owner_api(viewer).get(url(fin, "transactions/")).json()
        assert [row["amount"] for row in data["results"]] == ["1000.00"]
        assert owner_api(viewer).get(url(fin, f"transactions/{hidden.pk}/")).status_code == 404

    def test_owner_money_and_opening_need_finance_manage(
        self, owner_api, fin, role, person, kassa, today
    ):
        recorder = person(fin, role(fin, "Recorder", [Perm.FINANCE_RECORD]))
        kassa.operators.add(recorder)
        response = owner_api(recorder).post(
            url(fin, "transactions/"),
            {
                "kind": "owner",
                "amount": "10",
                "occurred_on": today.isoformat(),
                "account": kassa.pk,
            },
            format="json",
        )
        assert response.status_code == 403

    def test_a_recorder_records_only_on_accounts_they_operate(
        self, owner_api, fin, role, person, kassa, bank, today
    ):
        recorder = person(fin, role(fin, "Recorder", [Perm.FINANCE_RECORD]))
        kassa.operators.add(recorder)
        sales = Category.objects.get(company=fin, system_code="sales").pk
        payload = {
            "kind": "income",
            "amount": "10",
            "occurred_on": today.isoformat(),
            "category": sales,
        }
        assert (
            owner_api(recorder)
            .post(url(fin, "transactions/"), {**payload, "account": bank.pk}, format="json")
            .status_code
            == 400
        )
        assert (
            owner_api(recorder)
            .post(url(fin, "transactions/"), {**payload, "account": kassa.pk}, format="json")
            .status_code
            == 201
        )


class TestTransfers:
    def test_a_cross_currency_transfer(self, client, fin, kassa, dollars, boss, today):
        ExchangeRateFactory(date=today, rate=Decimal("12800"))
        income(fin, boss, kassa, "13000000", today)
        response = client.post(
            url(fin, "transfers/"),
            {
                "from_account": kassa.pk,
                "to_account": dollars.pk,
                "amount_out": "12900000",
                "amount_in": "1000",
                "occurred_on": today.isoformat(),
            },
            format="json",
        )
        assert response.status_code == 201, response.json()
        data = response.json()
        assert data["exchange_rate"] == "12900.000000"
        assert data["amount_in"] == "1000.00"
        fx = Transaction.objects.get(kind="fx")
        assert fx.base_amount == Decimal("-100000.00")
        void = client.post(
            url(fin, f"transfers/{data['id']}/void/"), {"reason": "Wrong"}, format="json"
        )
        assert void.json()["status"] == "void"


class TestDebts:
    def test_sell_on_credit_get_paid_and_see_the_summary(self, client, fin, kassa, today):
        party = CounterpartyFactory(company=fin, name="Tonggi Shabnam klinikasi")
        response = client.post(
            url(fin, "debts/"),
            {
                "direction": "receivable",
                "kind": "trade",
                "mode": "category",
                "category": Category.objects.get(company=fin, system_code="sales").pk,
                "amount": "900000",
                "currency": "UZS",
                "issued_on": (today - timedelta(days=20)).isoformat(),
                "due_on": (today - timedelta(days=5)).isoformat(),
                "counterparty": party.pk,
            },
            format="json",
        )
        assert response.status_code == 201, response.json()
        debt = response.json()
        assert debt["outstanding"] == "900000.00"
        assert debt["days_overdue"] == 5
        assert client.get(url(fin, "debts/"), {"overdue": "true"}).json()["count"] == 1
        payment = client.post(
            url(fin, f"debts/{debt['id']}/payments/"),
            {"account": kassa.pk, "amount": "400000", "paid_on": today.isoformat()},
            format="json",
        )
        assert payment.status_code == 201, payment.json()
        detail = client.get(url(fin, f"debts/{debt['id']}/")).json()
        assert detail["debt"]["paid"] == "400000.00"
        assert [row["kind"] for row in detail["payments"]] == ["income", "debt_payment"]
        summary = client.get(url(fin, "debts/summary/")).json()
        assert summary["receivable"]["total"] == "500000.00"
        assert summary["receivable"]["overdue"] == "500000.00"
        assert summary["aging"]["receivable"]["d1_30"] == "500000.00"

    def test_write_off_and_cancel_need_finance_manage(
        self, owner_api, fin, role, person, boss, today
    ):
        party = CounterpartyFactory(company=fin)
        debt = services.open_debt(
            fin,
            by=boss,
            direction="receivable",
            kind="trade",
            amount=Decimal("100"),
            currency="UZS",
            issued_on=today,
            counterparty=party,
            is_opening=True,
        )
        recorder = person(
            fin, role(fin, "Recorder", [Perm.FINANCE_RECORD, Perm.FINANCE_VIEW, Perm.BRANCHES_ALL])
        )
        api = owner_api(recorder)
        assert (
            api.post(
                url(fin, f"debts/{debt.pk}/write-off/"), {"reason": "Gone"}, format="json"
            ).status_code
            == 403
        )
        assert (
            owner_api(boss)
            .post(url(fin, f"debts/{debt.pk}/write-off/"), {"reason": "Gone"}, format="json")
            .status_code
            == 201
        )
        debt.refresh_from_db()
        assert debt.status == Debt.Status.WRITTEN_OFF

    def test_an_instalment_plan(self, client, fin, boss, today):
        party = CounterpartyFactory(company=fin)
        debt = services.open_debt(
            fin,
            by=boss,
            direction="receivable",
            kind="trade",
            amount=Decimal("300"),
            currency="UZS",
            issued_on=today - timedelta(days=40),
            counterparty=party,
            is_opening=True,
        )
        bad = client.put(
            url(fin, f"debts/{debt.pk}/installments/"),
            {"installments": [{"due_on": today.isoformat(), "amount": "100"}]},
            format="json",
        )
        assert bad.status_code == 400
        response = client.put(
            url(fin, f"debts/{debt.pk}/installments/"),
            {
                "installments": [
                    {"due_on": (today - timedelta(days=10)).isoformat(), "amount": "100"},
                    {"due_on": (today + timedelta(days=20)).isoformat(), "amount": "200"},
                ]
            },
            format="json",
        )
        assert response.status_code == 200, response.json()
        assert [row["status"] for row in response.json()] == ["overdue", "due"]
        debt.refresh_from_db()
        assert debt.due_on == today + timedelta(days=20)

    def test_salary_debts_hide_the_person_without_payroll_view(
        self, owner_api, fin, role, person, boss, member, today, kassa
    ):
        worker = member(fin, "Employee")
        services.record_transaction(
            fin,
            by=boss,
            kind="income",
            amount=Decimal("5000000"),
            occurred_on=today,
            account=kassa,
            category="sales",
        )
        services.open_debt(
            fin,
            by=boss,
            direction="receivable",
            kind="advance",
            amount=Decimal("1000000"),
            currency="UZS",
            issued_on=today,
            membership=worker,
            account=kassa,
        )
        viewer = person(fin, role(fin, "Bookkeeper", [Perm.FINANCE_VIEW, Perm.BRANCHES_ALL]))
        row = owner_api(viewer).get(url(fin, "debts/")).json()["results"][0]
        assert row["masked"] is True
        assert row["party"] is None
        assert row["outstanding"] == "1000000.00"


class TestCategories:
    def test_tree_create_rename_merge_move_delete(self, client, fin, boss, kassa, today):
        tree = client.get(url(fin, "categories/")).json()
        goods = next(node for node in tree if node["system_code"] == "goods")
        assert goods["is_system"] is True
        child = client.post(
            url(fin, "categories/"),
            {"name": "Medicines", "kind": "expense", "parent": goods["id"], "color": "#c67139"},
            format="json",
        )
        assert child.status_code == 201
        assert (
            client.patch(
                url(fin, f"categories/{goods['id']}/"), {"name": "Stock"}, format="json"
            ).status_code
            == 200
        )
        assert client.delete(url(fin, f"categories/{goods['id']}/")).status_code == 400
        other = services.create_category(fin, by=boss, name="Beverages", kind="expense")
        expense(fin, boss, kassa, "1", today, category=other) if kassa.balance else None
        merged = client.post(
            url(fin, f"categories/{other.pk}/merge/"), {"into": child.json()["id"]}, format="json"
        )
        assert merged.status_code == 200
        assert not Category.objects.filter(pk=other.pk).exists()
        moved = client.post(
            url(fin, f"categories/{child.json()['id']}/move/"),
            {"parent": None, "index": 0},
            format="json",
        )
        assert moved.status_code == 200
        assert Category.objects.get(pk=child.json()["id"]).parent_id is None
        assert client.delete(url(fin, f"categories/{child.json()['id']}/")).status_code == 204

    def test_marking_a_category_sensitive_needs_payroll_view(self, owner_api, fin, role, person):
        manager = person(fin, role(fin, "Books", [Perm.FINANCE_VIEW, Perm.FINANCE_MANAGE]))
        response = owner_api(manager).post(
            url(fin, "categories/"),
            {"name": "Bonuses", "kind": "expense", "is_sensitive": True},
            format="json",
        )
        assert response.status_code == 403


class TestCounterparties:
    def test_create_list_and_detail(self, client, fin, boss, today):
        response = client.post(
            url(fin, "counterparties/"),
            {"name": "Agromir", "kind": "supplier", "phone": "90 123 45 67", "tags": ["weekly"]},
            format="json",
        )
        assert response.status_code == 201, response.json()
        party = response.json()
        assert party["phone"] == "+998901234567"
        duplicate = client.post(
            url(fin, "counterparties/"),
            {"name": "Agromir 2", "phone": "+998901234567"},
            format="json",
        )
        assert duplicate.status_code == 400
        services.open_debt(
            fin,
            by=boss,
            direction="payable",
            kind="trade",
            amount=Decimal("700000"),
            currency="UZS",
            issued_on=today,
            counterparty=Counterparty.objects.get(pk=party["id"]),
            is_opening=True,
        )
        rows = client.get(url(fin, "counterparties/"), {"owes": "we"}).json()["results"]
        assert [(row["name"], row["we_owe"]) for row in rows] == [("Agromir", "700000.00")]
        detail = client.get(url(fin, f"counterparties/{party['id']}/")).json()
        assert len(detail["debts"]) == 1
        assert client.get(url(fin, "counterparties/"), {"q": "agro"}).json()["count"] == 1


class TestRates:
    def test_current_rate_company_rates_and_fetch(self, client, fin, today, monkeypatch):
        ExchangeRateFactory(date=today - timedelta(days=3), rate=Decimal("12700"))
        data = client.get(url(fin, "rates/")).json()
        assert data["current"]["stale"] is True
        assert data["current"]["rate"] == "12700.000000"
        response = client.post(
            url(fin, "rates/"), {"date": today.isoformat(), "rate": "12750.5"}, format="json"
        )
        assert response.status_code == 201
        data = client.get(url(fin, "rates/")).json()
        assert data["current"] == data["current"] | {
            "rate": "12750.500000",
            "stale": False,
            "source": "company",
        }
        own = CompanyRate.objects.get(company=fin)
        assert client.delete(url(fin, f"rates/{own.pk}/")).status_code == 204

        from apps.finance import cbu

        monkeypatch.setattr(
            cbu,
            "fetch_json",
            lambda url_, **kw: [
                {
                    "Ccy": "USD",
                    "Rate": "12811.42",
                    "Nominal": "1",
                    "Date": today.strftime("%d.%m.%Y"),
                }
            ],
        )
        response = client.post(url(fin, "rates/fetch/"))
        assert response.json() == response.json() | {"ok": True, "rate": "12811.420000"}

        def broken(url_, **kw):
            raise OSError("timeout")

        monkeypatch.setattr(cbu, "fetch_json", broken)
        assert client.post(url(fin, "rates/fetch/")).status_code == 502


class TestSettings:
    def test_settings_and_reopening_a_period(self, client, owner_api, fin, member, today):
        response = client.patch(
            url(fin, "settings/"),
            {"large_expense_alert": "10000000", "reimburse_via": "cash"},
            format="json",
        )
        assert response.json()["large_expense_alert"] == "10000000.00"
        accountant = member(fin, "Accountant")
        api = owner_api(accountant)
        assert (
            api.post(
                url(fin, "settings/lock/"),
                {"until": (today - timedelta(days=30)).isoformat()},
                format="json",
            ).status_code
            == 200
        )
        assert (
            api.post(url(fin, "settings/lock/"), {"until": None}, format="json").status_code == 400
        )
        assert (
            client.post(url(fin, "settings/lock/"), {"until": None}, format="json").status_code
            == 200
        )
        future = (today + timedelta(days=1)).isoformat()
        assert (
            client.post(url(fin, "settings/lock/"), {"until": future}, format="json").status_code
            == 400
        )


class TestReports:
    def test_the_report_endpoints_take_ranges_and_branches(self, client, fin, kassa, boss, today):
        income(fin, boss, kassa, "1000000", today)
        expense(fin, boss, kassa, "300000", today)
        pnl = client.get(url(fin, "reports/pnl/"), {"preset": "month", "compare": "prev"}).json()
        assert pnl["profit"]["total"] == "700000.00"
        assert pnl["income"]["nodes"][0]["total"] == "1000000.00"
        assert pnl["margin"]["total"] == "70.0"
        assert pnl["compare"] is not None
        flow = client.get(url(fin, "reports/cash-flow/"), {"preset": "last_30"}).json()
        assert flow["totals"] == {
            "income": "1000000.00",
            "expense": "300000.00",
            "net": "700000.00",
        }
        assert {row["key"] for row in flow["breakdown"]} >= {"operating", "owner", "transfers"}
        assert flow["series"][-1] == {
            "date": today.isoformat(),
            "income": "1000000.00",
            "expense": "300000.00",
            "net": "700000.00",
        }
        assert client.get(url(fin, "reports/pnl/"), {"group": "year"}).status_code == 400
        assert client.get(url(fin, "reports/pnl/"), {"from": "nope"}).status_code == 400
        balances = client.get(url(fin, "reports/balances/")).json()
        assert balances["total"] == "700000.00"
        trend = client.get(
            url(fin, "reports/category-trend/"),
            {"category": Category.objects.get(company=fin, system_code="rent").pk, "months": 3},
        ).json()
        assert trend["series"][-1]["amount"] == "300000.00"


def test_receipts_are_deleted_with_their_files(client, fin, kassa, boss, today):
    income(fin, boss, kassa, "1000", today)
    row = expense(fin, boss, kassa, "100", today)
    upload = client.post(
        url(fin, f"transactions/{row.pk}/receipts/"), {"file": jpeg()}, format="multipart"
    )
    assert upload.status_code == 201
    receipt = Receipt.objects.get()
    assert (
        client.delete(url(fin, f"transactions/{row.pk}/receipts/{receipt.pk}/")).status_code == 204
    )
    assert not Receipt.objects.exists()
