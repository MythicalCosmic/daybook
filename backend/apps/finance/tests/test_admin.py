import pytest
from django.urls import reverse

from apps.accounts.tests.factories import UserFactory
from apps.finance import services
from apps.finance.models import (
    Category,
    CompanyRate,
    Counterparty,
    Debt,
    ExchangeRate,
    FinanceSettings,
    MoneyAccount,
    Transaction,
    Transfer,
)
from apps.finance.tests.factories import CompanyRateFactory, CounterpartyFactory

pytestmark = pytest.mark.django_db

LEDGER = (
    Category,
    CompanyRate,
    Counterparty,
    Debt,
    FinanceSettings,
    MoneyAccount,
    Transaction,
    Transfer,
)


@pytest.fixture
def admin_client(client):
    client.force_login(UserFactory(is_staff=True, is_superuser=True))
    return client


@pytest.fixture
def ledger(books, owner, cash, bank, day):
    services.record_transaction(
        books, by=owner, kind="opening", amount=1000, occurred_on=day, account=cash
    )
    services.transfer(
        books, by=owner, from_account=cash, to_account=bank, amount_out=10, occurred_on=day
    )
    services.open_debt(
        books,
        by=owner,
        direction="receivable",
        kind="trade",
        amount=5,
        currency="UZS",
        issued_on=day,
        counterparty=CounterpartyFactory(company=books),
        category="sales",
    )
    services.get_settings(books)
    CompanyRateFactory(company=books, date=day)


def url(model, view, *args):
    return reverse(f"admin:finance_{model._meta.model_name}_{view}", args=args)


@pytest.mark.parametrize("model", LEDGER, ids=lambda m: m.__name__)
def test_the_ledger_is_shown_but_never_changed(admin_client, ledger, model):
    row = model.objects.first()

    assert admin_client.get(url(model, "changelist")).status_code == 200
    assert admin_client.get(url(model, "change", row.pk)).status_code == 200
    assert admin_client.get(url(model, "add")).status_code == 403
    assert admin_client.get(url(model, "delete", row.pk)).status_code == 403
    count = model.objects.count()
    assert admin_client.post(url(model, "delete", row.pk), {"post": "yes"}).status_code == 403
    assert model.objects.count() == count


def test_platform_admins_may_enter_global_rates(admin_client):
    response = admin_client.post(
        url(ExchangeRate, "add"),
        {
            "currency": "USD",
            "date": "2026-10-01",
            "rate": "12800",
            "source": "manual",
            "fetched_at_0": "2026-10-01",
            "fetched_at_1": "09:00:00",
        },
    )

    assert response.status_code == 302, response.content[:2000]
    assert ExchangeRate.objects.get().source == "manual"
