"""Review fixes of the finance owner API: branch-scoped writes, rows other modules booked,
decisions on waiting entries, scoped party balances, salary-detail masking of receipts and
sources, other companies' ids everywhere, and query counts that don't grow with the data."""

import io
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache
from PIL import Image

from apps.companies.models import Branch
from apps.core.files import signed_url
from apps.finance import queries, services, sources
from apps.finance.models import Category, Debt, MoneyAccount, Transaction
from apps.finance.tests.factories import CounterpartyFactory, MoneyAccountFactory
from apps.members.permissions import Perm

pytestmark = pytest.mark.django_db

D = Decimal


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
def kassa(fin, boss, today):
    account = MoneyAccount.objects.get(company=fin, kind=MoneyAccount.Kind.CASH)
    services.record_transaction(
        fin, by=boss, kind="opening", amount=D("10000000"), occurred_on=today, account=account
    )
    return account


@pytest.fixture
def module_source():
    """A source type of another module (sales), as package E registers its own."""
    sources.register("sales.reviewtest", label="Shift", url_template="/c/{company_id}/sales/{id}")
    yield lambda id, key="": sources.Source("sales.reviewtest", id, key)
    sources.unregister("sales.reviewtest")


@pytest.fixture
def branches(fin):
    main = fin.branches.first()
    other = Branch.objects.create(company=fin, name="Yunusobod")
    return main, other


def jpeg() -> io.BytesIO:
    out = io.BytesIO()
    Image.new("RGB", (30, 20), (90, 120, 60)).save(out, "JPEG")
    out.seek(0)
    out.name = "receipt.jpg"
    return out


def expense(company, by, account, amount, day, category="rent", **fields):
    return services.record_transaction(
        company,
        by=by,
        kind="expense",
        amount=D(amount),
        occurred_on=day,
        account=account,
        category=category,
        **fields,
    )


class TestBranchScopedWrites:
    """A member limited to some branches can't make rows without a branch (§2.6): before the
    fix they were made and then answered 500, because the member couldn't see them."""

    def manager(self, fin, role, person, branches, perms=()):
        return person(
            fin,
            role(fin, "Branch manager", [Perm.FINANCE_VIEW, Perm.FINANCE_RECORD, *perms]),
            branches=branches,
        )

    def test_an_account_takes_the_only_branch(self, owner_api, fin, role, person, branches):
        main, _other = branches
        member = self.manager(fin, role, person, [main], [Perm.FINANCE_MANAGE])
        response = owner_api(member).post(
            url(fin, "accounts/"), {"name": "Kassa 2", "kind": "cash"}, format="json"
        )
        assert response.status_code == 201
        assert response.json()["branch"]["id"] == main.pk

    def test_with_several_branches_one_must_be_picked(self, owner_api, fin, role, person, branches):
        member = self.manager(fin, role, person, list(branches), [Perm.FINANCE_MANAGE])
        response = owner_api(member).post(
            url(fin, "accounts/"), {"name": "Kassa 2", "kind": "cash"}, format="json"
        )
        assert response.status_code == 400
        assert "branch" in response.json()
        assert not MoneyAccount.objects.filter(company=fin, name="Kassa 2").exists()

    def test_a_debt_takes_the_only_branch(self, owner_api, fin, role, person, branches, today):
        main, _other = branches
        member = self.manager(fin, role, person, [main], [Perm.FINANCE_MANAGE])
        party = CounterpartyFactory(company=fin)
        response = owner_api(member).post(
            url(fin, "debts/"),
            {
                "direction": "receivable",
                "kind": "trade",
                "mode": "opening",
                "amount": "250000",
                "currency": "UZS",
                "issued_on": today.isoformat(),
                "counterparty": party.pk,
            },
            format="json",
        )
        assert response.status_code == 201
        assert response.json()["branch"]["id"] == main.pk

    def test_moving_a_row_out_of_every_branch_is_refused(
        self, owner_api, fin, role, person, branches, boss, today
    ):
        main, _other = branches
        member = self.manager(fin, role, person, [main], [Perm.FINANCE_MANAGE])
        here = MoneyAccountFactory(company=fin, name="Here", branch=main)
        services.record_transaction(
            fin, by=boss, kind="opening", amount=D("1000"), occurred_on=today, account=here
        )
        row = expense(fin, boss, here, "100", today)
        api = owner_api(member)
        assert (
            api.patch(url(fin, f"accounts/{here.pk}/"), {"branch": None}, format="json").status_code
            == 400
        )
        assert (
            api.patch(
                url(fin, f"transactions/{row.pk}/"), {"branch": None}, format="json"
            ).status_code
            == 400
        )
        # Someone who sees every branch may keep company-level rows.
        assert (
            owner_api(boss)
            .patch(url(fin, f"accounts/{here.pk}/"), {"branch": None}, format="json")
            .status_code
            == 200
        )

    def test_a_recorder_without_finance_view_cant_open_debts(
        self, owner_api, fin, role, person, kassa, today
    ):
        recorder = person(fin, role(fin, "Recorder", [Perm.FINANCE_RECORD, Perm.BRANCHES_ALL]))
        kassa.operators.add(recorder)
        response = owner_api(recorder).post(
            url(fin, "debts/"),
            {
                "direction": "receivable",
                "kind": "trade",
                "mode": "account",
                "account": kassa.pk,
                "amount": "1000",
                "currency": "UZS",
                "issued_on": today.isoformat(),
                "counterparty": CounterpartyFactory(company=fin).pk,
            },
            format="json",
        )
        assert response.status_code == 403
        assert not Debt.objects.filter(company=fin).exists()


def test_an_account_can_start_in_the_red(client, fin, today):
    response = client.post(
        url(fin, "accounts/"),
        {
            "name": "Humo kredit karta",
            "kind": "card",
            "opening_balance": "-1500000",
            "opening_on": today.isoformat(),
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    data = response.json()
    assert data["balance"] == "-1500000.00"
    assert data["allow_negative"] is True


class TestRowsOfOtherModules:
    def test_an_entry_another_module_booked_cant_be_voided_here(
        self, client, fin, boss, kassa, today, module_source
    ):
        row = services.record_transaction(
            fin,
            by=None,
            kind="income",
            amount=D("500000"),
            occurred_on=today,
            account=kassa,
            category="sales",
            source=module_source(41),
        )
        detail = client.get(url(fin, f"transactions/{row.pk}/")).json()
        assert detail["can_void"] is False
        response = client.post(
            url(fin, f"transactions/{row.pk}/void/"), {"reason": "wrong"}, format="json"
        )
        assert response.status_code == 400
        assert "Shift" in response.json()["detail"]
        row.refresh_from_db()
        assert row.status == Transaction.Status.POSTED

    def test_bulk_void_skips_them_with_the_reason(
        self, client, fin, boss, kassa, today, module_source
    ):
        theirs = services.record_transaction(
            fin,
            by=None,
            kind="income",
            amount=D("10"),
            occurred_on=today,
            account=kassa,
            category="sales",
            source=module_source(42),
        )
        mine = expense(fin, boss, kassa, "20", today)
        response = client.post(
            url(fin, "transactions/bulk/"),
            {"ids": [theirs.pk, mine.pk], "action": "void", "reason": "cleanup"},
            format="json",
        )
        results = {item["id"]: item for item in response.json()["results"]}
        assert results[mine.pk]["ok"] is True
        assert results[theirs.pk]["ok"] is False
        assert "Shift" in results[theirs.pk]["error"]

    def test_a_transfer_or_debt_another_module_made_stays(
        self, client, fin, boss, kassa, today, module_source
    ):
        safe = MoneyAccountFactory(company=fin, name="Safe")
        moved = services.transfer(
            fin,
            by=None,
            from_account=kassa,
            to_account=safe,
            amount_out=D("1000"),
            occurred_on=today,
            source=module_source(43),
        )
        assert (
            client.post(
                url(fin, f"transfers/{moved.pk}/void/"), {"reason": "x"}, format="json"
            ).status_code
            == 400
        )
        debt = services.open_debt(
            fin,
            by=None,
            direction="receivable",
            kind="trade",
            amount=D("700"),
            currency="UZS",
            issued_on=today,
            counterparty=CounterpartyFactory(company=fin),
            category="sales",
            source=module_source(44),
        )
        assert client.get(url(fin, f"debts/{debt.pk}/")).json()["can_cancel"] is False
        assert (
            client.post(
                url(fin, f"debts/{debt.pk}/cancel/"), {"reason": "x"}, format="json"
            ).status_code
            == 400
        )
        debt.refresh_from_db()
        assert debt.status == Debt.Status.OPEN


class TestWaitingEntries:
    def pending(self, fin, by, kassa, today, **fields):
        return services.record_transaction(
            fin,
            by=by,
            kind="expense",
            amount=D("450000"),
            occurred_on=today,
            account=kassa,
            category="transport",
            status="pending",
            **fields,
        )

    def test_approving_posts_it_and_moves_the_balance(
        self, owner_api, fin, member, boss, kassa, today
    ):
        worker = member(fin, "Accountant", first_name="Nigora")
        row = self.pending(fin, worker, kassa, today)
        before = MoneyAccount.objects.get(pk=kassa.pk).balance
        listed = owner_api(boss).get(url(fin, f"transactions/{row.pk}/")).json()
        assert listed["can_approve"] is True
        response = owner_api(boss).post(url(fin, f"transactions/{row.pk}/approve/"))
        assert response.status_code == 200
        assert response.json()["status"] == "posted"
        assert MoneyAccount.objects.get(pk=kassa.pk).balance == before - D("450000")

    def test_rejecting_needs_a_reason_and_keeps_the_balance(
        self, owner_api, fin, member, boss, kassa, today
    ):
        worker = member(fin, "Accountant", first_name="Nigora")
        row = self.pending(fin, worker, kassa, today)
        api = owner_api(boss)
        assert api.post(url(fin, f"transactions/{row.pk}/reject/"), {}).status_code == 400
        response = api.post(
            url(fin, f"transactions/{row.pk}/reject/"), {"reason": "No receipt"}, format="json"
        )
        assert response.json()["status"] == "rejected"
        assert response.json()["void_reason"] == "No receipt"

    def test_nobody_but_an_owner_decides_their_own_entry(
        self, owner_api, fin, member, kassa, today
    ):
        accountant = member(fin, "Accountant", first_name="Aziza")
        row = self.pending(fin, accountant, kassa, today)
        api = owner_api(accountant)
        assert api.get(url(fin, f"transactions/{row.pk}/")).json()["can_approve"] is False
        assert api.post(url(fin, f"transactions/{row.pk}/approve/")).status_code == 403

    def test_deciding_needs_finance_approve(self, owner_api, fin, role, person, boss, kassa, today):
        row = self.pending(fin, boss, kassa, today)
        viewer = person(fin, role(fin, "Books", [Perm.FINANCE_VIEW, Perm.BRANCHES_ALL]))
        assert (
            owner_api(viewer).post(url(fin, f"transactions/{row.pk}/approve/")).status_code == 403
        )

    def test_a_claims_entry_is_decided_with_its_claim(
        self, owner_api, fin, member, boss, kassa, today, src
    ):
        row = self.pending(fin, None, kassa, today, source=src(7))
        api = owner_api(boss)
        assert api.get(url(fin, f"transactions/{row.pk}/")).json()["can_approve"] is False
        assert api.post(url(fin, f"transactions/{row.pk}/approve/")).status_code == 400


class TestScopedPartyBalances:
    def test_a_branch_member_sees_only_their_branchs_debts_of_a_party(
        self, owner_api, fin, role, person, boss, branches, today
    ):
        main, other = branches
        party = CounterpartyFactory(company=fin, name="Barakat Kafe")
        for branch, amount in ((main, "100000"), (other, "900000")):
            services.open_debt(
                fin,
                by=boss,
                direction="receivable",
                kind="trade",
                amount=D(amount),
                currency="UZS",
                issued_on=today,
                counterparty=party,
                branch=branch,
                is_opening=True,
            )
        viewer = person(fin, role(fin, "Branch books", [Perm.FINANCE_VIEW]), branches=[main])
        api = owner_api(viewer)
        listed = api.get(url(fin, "counterparties/")).json()["results"]
        assert [row["owes_us"] for row in listed if row["id"] == party.pk] == ["100000.00"]
        detail = api.get(url(fin, f"counterparties/{party.pk}/")).json()
        assert detail["counterparty"]["owes_us"] == "100000.00"
        everything = owner_api(boss).get(url(fin, f"counterparties/{party.pk}/")).json()
        assert everything["counterparty"]["owes_us"] == "1000000.00"

    def test_owes_filter_follows_the_scope(
        self, owner_api, fin, role, person, boss, branches, today
    ):
        main, other = branches
        party = CounterpartyFactory(company=fin, name="Only Yunusobod")
        services.open_debt(
            fin,
            by=boss,
            direction="receivable",
            kind="trade",
            amount=D("5000"),
            currency="UZS",
            issued_on=today,
            counterparty=party,
            branch=other,
            is_opening=True,
        )
        viewer = person(fin, role(fin, "Branch books", [Perm.FINANCE_VIEW]), branches=[main])
        rows = owner_api(viewer).get(url(fin, "counterparties/"), {"owes": "us"}).json()
        assert rows["count"] == 0
        rows = owner_api(boss).get(url(fin, "counterparties/"), {"owes": "us"}).json()
        assert [row["id"] for row in rows["results"]] == [party.pk]


class TestSalaryDetail:
    def salary(self, fin, boss, kassa, today, worker):
        row = expense(fin, boss, kassa, "4300000", today, category="salaries", membership=worker)
        services.upload_receipt(fin, by=boss, file=jpeg(), txn=row)
        return row

    def test_a_salary_receipt_link_needs_payroll_view(
        self, fin, boss, kassa, today, member, role, person, client
    ):
        worker = member(fin, "Employee", first_name="Alisher")
        row = self.salary(fin, boss, kassa, today, worker)
        receipt = row.receipts.get()
        viewer = person(fin, role(fin, "Books", [Perm.FINANCE_VIEW, Perm.BRANCHES_ALL]))
        link = signed_url(
            receipt.file,
            user=viewer.user,
            company_id=fin.pk,
            check=f"finance.receipt:{receipt.pk}",
        )
        assert client.get(link).status_code == 404
        payroll = person(
            fin, role(fin, "Payroll", [Perm.FINANCE_VIEW, Perm.BRANCHES_ALL, Perm.PAYROLL_VIEW])
        )
        link = signed_url(
            receipt.file,
            user=payroll.user,
            company_id=fin.pk,
            check=f"finance.receipt:{receipt.pk}",
        )
        assert client.get(link).status_code == 200

    def test_a_masked_row_hides_where_it_came_from(
        self, owner_api, fin, boss, kassa, today, member, role, person, src
    ):
        worker = member(fin, "Employee", first_name="Alisher")
        row = expense(
            fin,
            None,
            kassa,
            "4300000",
            today,
            category="salaries",
            membership=worker,
            source=src(12),
        )
        viewer = person(fin, role(fin, "Books", [Perm.FINANCE_VIEW, Perm.BRANCHES_ALL]))
        data = owner_api(viewer).get(url(fin, f"transactions/{row.pk}/")).json()
        assert data["masked"] is True
        assert data["source"] is None
        assert owner_api(boss).get(url(fin, f"transactions/{row.pk}/")).json()["source"]["id"] == 12

    def test_a_salary_category_isnt_merged_into_an_open_one(self, fin, boss):
        bonuses = services.create_category(
            fin, by=boss, name="Bonuslar", kind="expense", is_sensitive=True
        )
        rent = Category.objects.get(company=fin, system_code="rent")
        with pytest.raises(services.DomainError, match="salary detail"):
            services.merge_category(bonuses, into=rent, by=boss)


def test_the_cached_overview_follows_a_change_of_scope(
    owner_api, fin, role, person, boss, branches, today
):
    main, other = branches
    there = MoneyAccountFactory(company=fin, name="There", branch=other)
    services.record_transaction(
        fin, by=boss, kind="opening", amount=D("777000"), occurred_on=today, account=there
    )
    cache.clear()
    viewer = person(fin, role(fin, "Books", [Perm.FINANCE_VIEW, Perm.BRANCHES_ALL]))
    api = owner_api(viewer)
    assert api.get(url(fin, "overview/")).json()["cash"]["total"] == "777000.00"
    viewer.role.permissions = [Perm.DASHBOARD_ACCESS, Perm.FINANCE_VIEW]
    viewer.role.save()
    viewer.branches.set([main])
    assert api.get(url(fin, "overview/")).json()["cash"]["total"] == "0.00"


OTHER_COMPANY_WRITES = [
    ("get", "accounts/{account}/"),
    ("patch", "accounts/{account}/"),
    ("post", "accounts/{account}/archive/"),
    ("get", "accounts/{account}/statement/"),
    ("patch", "categories/{category}/"),
    ("delete", "categories/{category}/"),
    ("post", "categories/{category}/merge/"),
    ("get", "counterparties/{party}/"),
    ("patch", "counterparties/{party}/"),
    ("get", "transactions/{row}/"),
    ("patch", "transactions/{row}/"),
    ("post", "transactions/{row}/void/"),
    ("post", "transactions/{row}/approve/"),
    ("post", "transactions/{row}/receipts/"),
    ("get", "debts/{debt}/"),
    ("patch", "debts/{debt}/"),
    ("post", "debts/{debt}/payments/"),
    ("post", "debts/{debt}/write-off/"),
    ("post", "debts/{debt}/cancel/"),
    ("put", "debts/{debt}/installments/"),
    ("post", "transfers/{transfer}/void/"),
    ("delete", "rates/{rate}/"),
]


@pytest.fixture
def foreign(other_company, member):
    """A second company with one of everything, and its owner."""
    from apps.finance import defaults

    other_company.features = ["finance"]
    other_company.save(update_fields=["features"])
    defaults.ensure(other_company)
    owner = member(other_company, "Owner")
    day = queries.local_today(other_company)
    cash = MoneyAccount.objects.get(company=other_company, kind="cash")
    safe = MoneyAccountFactory(company=other_company, name="Safe")
    services.record_transaction(
        other_company, by=owner, kind="opening", amount=D("1000"), occurred_on=day, account=cash
    )
    row = expense(other_company, owner, cash, "10", day)
    party = CounterpartyFactory(company=other_company)
    debt = services.open_debt(
        other_company,
        by=owner,
        direction="receivable",
        kind="trade",
        amount=D("50"),
        currency="UZS",
        issued_on=day,
        counterparty=party,
        is_opening=True,
    )
    moved = services.transfer(
        other_company,
        by=owner,
        from_account=cash,
        to_account=safe,
        amount_out=D("5"),
        occurred_on=day,
    )
    rate = services.set_company_rate(
        other_company, by=owner, currency="USD", day=day, rate=D("12000")
    )
    return {
        "company": other_company,
        "account": cash.pk,
        "category": Category.objects.get(company=other_company, system_code="rent").pk,
        "party": party.pk,
        "row": row.pk,
        "debt": debt.pk,
        "transfer": moved.pk,
        "rate": rate.pk,
    }


@pytest.mark.parametrize(("method", "path"), OTHER_COMPANY_WRITES)
def test_another_companys_records_answer_404_by_id(client, fin, kassa, foreign, method, path):
    target = url(fin, path.format(**foreign))
    response = getattr(client, method)(target, {}, format="json")
    assert response.status_code == 404, (method, path, response.status_code)


def test_ids_of_another_company_in_a_payload_are_refused(client, fin, kassa, today, foreign):
    base = {
        "kind": "expense",
        "amount": "10",
        "occurred_on": today.isoformat(),
        "account": kassa.pk,
        "category": Category.objects.get(company=fin, system_code="rent").pk,
    }
    for field, value in (
        ("account", foreign["account"]),
        ("category", foreign["category"]),
        ("counterparty", foreign["party"]),
    ):
        response = client.post(url(fin, "transactions/"), {**base, field: value}, format="json")
        assert response.status_code == 400, field
        assert field in response.json()
    response = client.post(
        url(fin, "transfers/"),
        {
            "from_account": kassa.pk,
            "to_account": foreign["account"],
            "amount_out": "5",
            "occurred_on": today.isoformat(),
        },
        format="json",
    )
    assert response.status_code == 400
    response = client.post(
        url(fin, "categories/"),
        {"name": "Sub", "kind": "expense", "parent": foreign["category"]},
        format="json",
    )
    assert response.status_code == 400


class TestQueryCounts:
    """List endpoints cost the same number of queries for 3 rows as for 12."""

    def fill(self, fin, boss, kassa, today, n):
        party = CounterpartyFactory(company=fin, name=f"Party {n}")
        for index in range(n):
            row = expense(
                fin,
                boss,
                kassa,
                str(1000 + index),
                today - timedelta(days=index % 5),
                counterparty=party,
                description=f"row {index}",
            )
            if index % 3 == 0:
                services.upload_receipt(fin, by=boss, file=jpeg(), txn=row)
            services.open_debt(
                fin,
                by=boss,
                direction="receivable",
                kind="trade",
                amount=D("100"),
                currency="UZS",
                issued_on=today,
                due_on=today + timedelta(days=index % 6),
                counterparty=CounterpartyFactory(company=fin),
                is_opening=True,
            )
            MoneyAccountFactory(company=fin, name=f"Card {n}-{index}", kind="card")

    def count(self, client, path, params=None) -> int:
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        cache.clear()
        with CaptureQueriesContext(connection) as queries_run:
            response = client.get(path, params or {})
        assert response.status_code == 200, response.json()
        return len(queries_run)

    @pytest.mark.parametrize(
        "path",
        [
            "transactions/",
            "accounts/",
            "debts/",
            "counterparties/",
            "overview/",
            "accounts/{kassa}/statement/",
        ],
    )
    def test_lists_dont_grow_with_their_rows(self, client, fin, boss, kassa, today, path):
        target = url(fin, path.format(kassa=kassa.pk))
        self.fill(fin, boss, kassa, today, 3)
        few = self.count(client, target)
        self.fill(fin, boss, kassa, today, 9)
        many = self.count(client, target)
        assert many == few, (path, few, many)
