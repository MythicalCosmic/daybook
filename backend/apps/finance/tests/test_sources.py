import pytest

from apps.finance import services, sources
from apps.finance.models import Debt, Transaction, Transfer
from apps.finance.tests.factories import CounterpartyFactory

pytestmark = pytest.mark.django_db


class TestRegistry:
    def test_a_registered_type_has_a_label_and_a_link(self, src):
        assert sources.label("finance.test") == "Test"
        assert sources.url("finance.test", 12, company_id=3) == "/c/3/test/12"
        assert "finance.test" in sources.registered()

    def test_the_ledgers_own_type_is_registered(self):
        assert sources.get("finance.transaction") is not None
        assert sources.url("finance.transaction", 5, company_id=1) == (
            "/c/1/finance/transactions/5"
        )

    def test_unknown_types_read_as_themselves(self):
        assert sources.label("nowhere.thing") == "nowhere.thing"
        assert sources.url("nowhere.thing", 1, company_id=1) == ""

    def test_a_type_is_registered_once(self, src):
        with pytest.raises(sources.DuplicateSource):
            sources.register("finance.test", label="Again", url_template="")

    @pytest.mark.parametrize(
        "name",
        [
            "cashshift",
            "Sales.cashshift",
            "sales.",
            "nowhere.thing",
            "sales.cash-shift",
            "a." + "b" * 40,
        ],
    )
    def test_a_type_is_an_installed_apps_label_and_a_name(self, name):
        with pytest.raises(ValueError):
            sources.register(name, label="X", url_template="")
        assert sources.get(name) is None

    def test_another_app_may_register_its_types(self):
        sources.register("sales.cashshift", label="Shift", url_template="/c/{company_id}/s/{id}")
        try:
            assert sources.check(("sales.cashshift", 1, "m2")) == sources.Source(
                "sales.cashshift", 1, "m2"
            )
        finally:
            sources.unregister("sales.cashshift")


class TestCheck:
    def test_none_stays_none(self):
        assert sources.check(None) is None

    def test_a_plain_tuple_becomes_a_source(self, src):
        assert sources.check(("finance.test", 3)) == sources.Source("finance.test", 3, "")

    @pytest.mark.parametrize(
        "source",
        [
            ("finance.unknown", 1, ""),
            ("finance.test", 0, ""),
            ("finance.test", "1", ""),
            ("finance.test", True, ""),
            ("finance.test", 1, "k" * 33),
        ],
    )
    def test_bad_sources_are_refused(self, src, source):
        with pytest.raises(ValueError):
            sources.check(source)


class TestLosingTheRace:
    """A concurrent call that booked the same source first wins; its rows come back."""

    def blind_once(self, monkeypatch, name):
        real = getattr(services, name)
        calls = []

        def lookup(company, source):
            calls.append(source)
            return None if len(calls) == 1 else real(company, source)

        monkeypatch.setattr(services, name, lookup)

    def test_a_transaction(self, books, cash, day, src, monkeypatch):
        first = services.record_transaction(
            books,
            by=None,
            kind="income",
            amount=5,
            occurred_on=day,
            account=cash,
            category="sales",
            source=src(1),
        )
        self.blind_once(monkeypatch, "_live_row")
        again = services.record_transaction(
            books,
            by=None,
            kind="income",
            amount=5,
            occurred_on=day,
            account=cash,
            category="sales",
            source=src(1),
        )

        assert again == first
        assert Transaction.objects.count() == 1
        cash.refresh_from_db()
        assert cash.balance == 5

    def test_a_transfer(self, books, cash, bank, day, src, monkeypatch):
        cash.allow_negative = True
        cash.save()
        kwargs = {
            "by": None,
            "from_account": cash,
            "to_account": bank,
            "amount_out": 5,
            "occurred_on": day,
            "source": src(2),
        }
        first = services.transfer(books, **kwargs)
        self.blind_once(monkeypatch, "_posted_transfer")

        assert services.transfer(books, **kwargs) == first
        assert Transfer.objects.count() == 1

    def test_a_debt(self, books, day, src, monkeypatch):
        kwargs = {
            "by": None,
            "direction": "receivable",
            "kind": "trade",
            "amount": 5,
            "currency": "UZS",
            "issued_on": day,
            "counterparty": CounterpartyFactory(company=books),
            "category": "sales",
            "source": src(3),
        }
        first = services.open_debt(books, **kwargs)
        self.blind_once(monkeypatch, "_live_debt")

        assert services.open_debt(books, **kwargs) == first
        assert Debt.objects.count() == 1
        assert Transaction.objects.count() == 1
