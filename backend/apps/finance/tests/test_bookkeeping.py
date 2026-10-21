"""The bookkeeping services of Package D: categories, counterparties, accounts, entries made by a
person, receipts, debts, rates, the period lock and settings."""

from datetime import timedelta
from decimal import Decimal

import pytest

from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.finance import conf, services
from apps.finance.models import Category, Counterparty, MoneyAccount, Transaction
from apps.finance.tests.factories import CounterpartyFactory, MoneyAccountFactory
from apps.inbox.models import Notification

pytestmark = pytest.mark.django_db
D = Decimal


class TestCategories:
    def test_two_levels_of_one_kind(self, books, owner):
        goods = Category.objects.get(company=books, system_code="goods")
        drinks = services.create_category(
            books, by=owner, name="Drinks", kind="expense", parent=goods
        )
        with pytest.raises(DomainError):
            services.create_category(books, by=owner, name="Cola", kind="expense", parent=drinks)
        with pytest.raises(DomainError):
            services.create_category(books, by=owner, name="Tips", kind="income", parent=goods)
        with pytest.raises(DomainError):
            services.create_category(books, by=owner, name="drinks", kind="expense", parent=goods)

    def test_system_categories_are_renamed_never_archived_and_salaries_stay_sensitive(
        self, books, owner
    ):
        rent = Category.objects.get(company=books, system_code="rent")
        assert services.update_category(rent, by=owner, name="Ijara").name == "Ijara"
        with pytest.raises(DomainError):
            services.update_category(rent, by=owner, is_active=False)
        salaries = Category.objects.get(company=books, system_code="salaries")
        with pytest.raises(DomainError):
            services.update_category(salaries, by=owner, is_sensitive=False)
        with pytest.raises(DomainError):
            services.delete_category(rent, by=owner)

    def test_archiving_a_parent_archives_its_children(self, books, owner):
        parent = services.create_category(books, by=owner, name="Supplies", kind="expense")
        child = services.create_category(
            books, by=owner, name="Bags", kind="expense", parent=parent
        )
        services.update_category(parent, by=owner, is_active=False)
        child.refresh_from_db()
        assert child.is_active is False

    def test_move_reorders_siblings(self, books, owner):
        a = services.create_category(books, by=owner, name="A", kind="expense")
        b = services.create_category(books, by=owner, name="B", kind="expense")
        c = services.create_category(books, by=owner, name="C", kind="expense", parent=a)
        services.move_category(c, by=owner, parent=b, index=0)
        services.move_category(b, by=owner, parent=None, index=0)
        c.refresh_from_db()
        assert c.parent_id == b.pk
        tops = list(
            Category.objects.filter(company=books, parent=None, kind="expense").order_by("order")
        )
        assert tops[0] == b
        with pytest.raises(DomainError):
            services.move_category(b, by=owner, parent=a, index=0)  # B has a child now

    def test_merge_moves_entries_children_and_defaults(self, books, owner, cash, day):
        old = services.create_category(books, by=owner, name="Old", kind="expense")
        kid = services.create_category(books, by=owner, name="Kid", kind="expense", parent=old)
        new = services.create_category(books, by=owner, name="New", kind="expense")
        party = CounterpartyFactory(company=books, default_category=old)
        services.record_transaction(
            books, by=owner, kind="opening", amount=D("100"), occurred_on=day, account=cash
        )
        row = services.record_transaction(
            books,
            by=owner,
            kind="expense",
            amount=D("10"),
            occurred_on=day,
            account=cash,
            category=old,
        )
        services.merge_category(old, into=new, by=owner)
        row.refresh_from_db()
        kid.refresh_from_db()
        party.refresh_from_db()
        assert (row.category_id, kid.parent_id, party.default_category_id) == (
            new.pk,
            new.pk,
            new.pk,
        )
        assert not Category.objects.filter(pk=old.pk).exists()
        assert AuditLog.objects.filter(action="finance.category_merged").exists()

    def test_a_merge_that_would_rewrite_a_closed_period_is_refused(self, books, owner, cash, day):
        old = services.create_category(books, by=owner, name="Old", kind="expense")
        new = services.create_category(books, by=owner, name="New", kind="expense")
        services.record_transaction(
            books, by=owner, kind="opening", amount=D("100"), occurred_on=day, account=cash
        )
        services.record_transaction(
            books,
            by=owner,
            kind="expense",
            amount=D("10"),
            occurred_on=day,
            account=cash,
            category=old,
        )
        services.lock_period(books, by=owner, until=day)
        with pytest.raises(DomainError):
            services.merge_category(old, into=new, by=owner)

    def test_copy_setup_brings_own_categories_only(self, books, owner, other_company, member):
        from apps.finance import defaults

        goods = Category.objects.get(company=books, system_code="goods")
        services.create_category(books, by=owner, name="Drinks", kind="expense", parent=goods)
        services.create_category(books, by=owner, name="Supplies", kind="expense")
        defaults.ensure(other_company)
        target_owner = member(other_company, "Owner")
        assert services.copy_categories(books, other_company, target_owner) == 2
        assert services.copy_categories(books, other_company, target_owner) == 0
        drinks = Category.objects.get(company=other_company, name="Drinks")
        assert drinks.parent.system_code == "goods"


class TestCounterparties:
    @pytest.mark.parametrize(
        ("raw", "clean"),
        [("90 123 45 67", "+998901234567"), ("+998 (90) 123-45-67", "+998901234567"), ("", "")],
    )
    def test_phones_are_normalized(self, raw, clean):
        assert services.normalize_phone(raw) == clean

    @pytest.mark.parametrize("raw", ["123", "+7 999 123 45 67"])
    def test_foreign_or_short_numbers_are_refused(self, raw):
        with pytest.raises(DomainError):
            services.normalize_phone(raw)

    def test_create_and_update_audit_the_changes(self, books, owner):
        party = services.create_counterparty(
            books,
            by=owner,
            name=" Agromir ",
            kind="supplier",
            telegram_username="@agromir",
            tags=["a", "A", "b"],
        )
        assert (party.name, party.telegram_username, party.tags) == (
            "Agromir",
            "agromir",
            ["a", "b"],
        )
        services.update_counterparty(party, by=owner, credit_limit="5000000", tin="305112874")
        log = AuditLog.objects.get(action="finance.counterparty_updated")
        assert log.details["changes"]["credit_limit"] == [None, "5000000.00"]
        with pytest.raises(DomainError):
            services.create_counterparty(books, by=owner, name="Again", tin="305112874")
        with pytest.raises(DomainError):
            services.update_counterparty(party, by=owner, tin="12")
        assert Counterparty.objects.filter(company=books).count() == 1


class TestAccounts:
    def test_update_and_archive(self, books, owner, member, cash, day):
        cashier = member(books, "Cashier")
        services.update_account(cash, by=owner, name="Kassa", operators=[cashier], color="#c67139")
        assert list(cash.operators.all()) == [cashier]
        with pytest.raises(DomainError):
            services.update_account(cash, by=owner, number_last4="12345")
        services.record_transaction(
            books, by=owner, kind="opening", amount=D("5"), occurred_on=day, account=cash
        )
        with pytest.raises(DomainError):
            services.archive_account(cash, by=owner)
        empty = MoneyAccountFactory(company=books, name="Empty")
        assert services.archive_account(empty, by=owner).is_active is False
        assert services.reopen_account(empty, by=owner).is_active is True


class TestEntries:
    def test_owner_and_opening_entries_take_a_direction(self, books, owner, cash, day):
        services.record_entry(
            books, by=owner, kind="opening", amount="100", occurred_on=day, account=cash
        )
        row = services.record_entry(
            books,
            by=owner,
            kind="owner",
            amount="40",
            direction="out",
            occurred_on=day,
            account=cash,
        )
        assert row.amount == D("-40.00")

    def test_a_large_expense_by_someone_else_tells_the_owners(
        self, books, owner, accountant, cash, day, django_capture_on_commit_callbacks
    ):
        settings_row = conf.get_settings(books)
        settings_row.large_expense_alert = D("1000000")
        settings_row.save()
        services.record_entry(
            books, by=owner, kind="opening", amount="9000000", occurred_on=day, account=cash
        )
        with django_capture_on_commit_callbacks(execute=True):
            services.record_entry(
                books,
                by=accountant,
                kind="expense",
                amount="2000000",
                occurred_on=day,
                account=cash,
                category="repairs",
            )
            services.record_entry(
                books,
                by=owner,
                kind="expense",
                amount="3000000",
                occurred_on=day,
                account=cash,
                category="repairs",
            )
        notes = Notification.objects.filter(kind="finance.large_expense")
        assert [note.recipient for note in notes] == [owner]
        assert "2 000 000" in notes[0].title

    def test_editing_a_pending_entry_moves_no_balance(self, books, owner, cash, day):
        row = services.record_transaction(
            books,
            by=owner,
            kind="expense",
            amount=D("10"),
            occurred_on=day,
            account=cash,
            category="rent",
            status="pending",
        )
        services.update_transaction(row, by=owner, amount="25")
        cash.refresh_from_db()
        assert cash.balance == D("0")
        row.refresh_from_db()
        assert row.amount == D("-25.00")

    def test_a_new_day_takes_that_days_rate(self, books, owner, dollars, day, usd):
        from apps.finance.tests.factories import ExchangeRateFactory

        ExchangeRateFactory(date=day + timedelta(days=1), rate=D("13000"))
        services.record_transaction(
            books, by=owner, kind="opening", amount=D("100"), occurred_on=day, account=dollars
        )
        row = services.record_transaction(
            books,
            by=owner,
            kind="expense",
            amount=D("10"),
            occurred_on=day,
            account=dollars,
            category="rent",
        )
        assert row.base_amount == D("-128000.00")
        services.update_transaction(row, by=owner, occurred_on=day + timedelta(days=1))
        row.refresh_from_db()
        assert (row.rate, row.base_amount) == (D("13000"), D("-130000.00"))

    def test_moving_an_entry_to_another_currency_needs_its_amount(
        self, books, owner, cash, dollars, day, usd
    ):
        services.record_transaction(
            books, by=owner, kind="opening", amount=D("100"), occurred_on=day, account=dollars
        )
        services.record_transaction(
            books, by=owner, kind="opening", amount=D("5000000"), occurred_on=day, account=cash
        )
        row = services.record_transaction(
            books,
            by=owner,
            kind="expense",
            amount=D("10"),
            occurred_on=day,
            account=dollars,
            category="rent",
        )
        with pytest.raises(DomainError, match="UZS"):
            services.update_transaction(row, by=owner, account=cash)
        services.update_transaction(row, by=owner, account=cash, amount=D("128000"))
        row.refresh_from_db()
        assert (row.currency, row.amount, row.base_amount) == ("UZS", D("-128000"), D("-128000"))
        dollars.refresh_from_db()
        cash.refresh_from_db()
        assert (dollars.balance, cash.balance) == (D("100.00"), D("4872000.00"))

    def test_a_void_entry_cant_be_changed(self, books, owner, cash, day):
        services.record_transaction(
            books, by=owner, kind="opening", amount=D("100"), occurred_on=day, account=cash
        )
        row = services.record_transaction(
            books,
            by=owner,
            kind="expense",
            amount=D("10"),
            occurred_on=day,
            account=cash,
            category="rent",
        )
        services.void_transaction(row, by=owner, reason="Wrong")
        with pytest.raises(DomainError):
            services.update_transaction(row, by=owner, description="x")


class TestReceipts:
    def test_pictures_get_a_thumbnail_and_anything_else_is_refused(self, books, owner, cash, day):
        import io

        from PIL import Image

        picture = io.BytesIO()
        Image.new("RGB", (900, 600), (10, 120, 200)).save(picture, "PNG")
        receipt = services.upload_receipt(books, by=owner, file=picture)
        assert receipt.content_type == "image/jpeg"
        assert receipt.file.name.endswith(".jpg")
        assert receipt.thumb.name.endswith(".webp")
        with pytest.raises(DomainError):
            services.upload_receipt(
                books, by=owner, file=io.BytesIO(b"<svg onload=alert(1)></svg>")
            )
        row = services.record_entry(
            books,
            by=owner,
            kind="opening",
            amount="10",
            occurred_on=day,
            account=cash,
            receipts=[receipt],
        )
        assert list(row.receipts.all()) == [receipt]


class TestDebts:
    def test_update_and_cancelled_debts(self, books, owner, day):
        debt = services.open_debt(
            books,
            by=owner,
            direction="payable",
            kind="bill",
            amount=D("100"),
            currency="UZS",
            issued_on=day,
            counterparty=CounterpartyFactory(company=books),
            is_opening=True,
        )
        services.update_debt(debt, by=owner, due_on=day + timedelta(days=9), description="Rent")
        debt.refresh_from_db()
        assert debt.due_on == day + timedelta(days=9)
        with pytest.raises(DomainError):
            services.update_debt(debt, by=owner, due_on=day - timedelta(days=1))
        services.cancel_debt(debt, by=owner, reason="Mistake")
        with pytest.raises(DomainError):
            services.update_debt(debt, by=owner, description="Again")


class TestRatesAndSettings:
    def test_company_rate_beats_the_central_bank(self, books, owner, day, usd):
        from apps.finance.rates import rate_for

        services.set_company_rate(books, by=owner, currency="USD", day=day, rate="12950")
        assert rate_for(books, "USD", day).rate == D("12950")
        services.set_company_rate(books, by=owner, currency="USD", day=day, rate="12960")
        assert rate_for(books, "USD", day).rate == D("12960")
        with pytest.raises(DomainError):
            services.set_company_rate(books, by=owner, currency="UZS", day=day, rate="1")

    def test_the_period_lock_moves_forward_freely_and_back_only_for_owners(
        self, books, owner, accountant, day
    ):
        services.lock_period(books, by=accountant, until=day)
        with pytest.raises(DomainError):
            services.lock_period(books, by=accountant, until=day - timedelta(days=1))
        services.lock_period(books, by=owner, until=None)
        assert conf.get_settings(books).locked_until is None
        actions = list(
            AuditLog.objects.filter(action__startswith="finance.period")
            .order_by("pk")
            .values_list("action", flat=True)
        )
        assert actions == ["finance.period_locked", "finance.period_reopened"]

    def test_settings_are_audited(self, books, owner):
        services.update_settings(
            books, by=owner, receipt_required_over="250000", rate_source="manual"
        )
        row = conf.get_settings(books)
        assert (row.receipt_required_over, row.rate_source) == (D("250000.00"), "manual")
        log = AuditLog.objects.get(action="finance.settings_updated")
        assert log.details["changes"]["rate_source"] == ["cbu", "manual"]


def test_bulk_reports_each_entry(books, owner, cash, day):
    services.record_transaction(
        books, by=owner, kind="opening", amount=D("100"), occurred_on=day, account=cash
    )
    rows = [
        services.record_transaction(
            books,
            by=owner,
            kind="expense",
            amount=D("1"),
            occurred_on=day,
            account=cash,
            category="rent",
        )
        for _ in range(2)
    ]
    services.lock_period(books, by=owner, until=day - timedelta(days=1))
    results = services.bulk_transactions(rows, by=owner, action="void", payload={"reason": "Dup"})
    assert [item["ok"] for item in results] == [True, True]
    assert Transaction.objects.filter(status="void").count() == 2
    cash.refresh_from_db()
    assert cash.balance == D("100.00")
    assert MoneyAccount.objects.get(pk=cash.pk).balance == D("100.00")
