"""The demo's contracts: built on any company with two branches, standing alone (without the
finance demo's parties) and with Finance's rent already planned."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.companies.models import Branch
from apps.contracts import demo, providers, services
from apps.contracts.models import BusinessContract, ContractFile
from apps.core.uploads import accept_document
from apps.finance import defaults as finance_defaults
from apps.finance import recurring
from apps.finance import services as finance
from apps.finance.models import Category, Counterparty, MoneyAccount, RecurringRule

pytestmark = pytest.mark.django_db


@pytest.fixture
def pharmacy(company, demo_people):
    company.features = ["finance"]
    company.save(update_fields=["features"])
    finance_defaults.ensure(company)
    Branch.objects.create(company=company, name="Yunusobod", order=1)
    people = demo_people(company)
    return company, people


def test_the_demo_tells_its_story(pharmacy):
    company, people = pharmacy
    owner = people["owner"]
    landlord = finance.create_counterparty(
        company, by=owner, name="Rustam Qodirov (ijara)", kind="other"
    )
    finance.create_account(company, by=owner, kind="cash", name="Dollar seyf", currency="USD")
    rent = Category.objects.get(company=company, system_code="rent")
    today = services.local_today(company)
    planned = recurring.create_rule(
        company,
        by=owner,
        name="Ijara",
        kind="expense",
        mode="bill",
        frequency="monthly",
        day=3,
        category=rent,
        counterparty=landlord,
        branch=company.branches.order_by("order", "pk").first(),
        amount=Decimal(9_000_000),
        starts_on=today - timedelta(days=60),
    )

    demo.seed(company, people, timezone.now())

    rows = {row.kind: row for row in BusinessContract.objects.filter(company=company)}
    assert BusinessContract.objects.filter(company=company).count() == 4
    leases = BusinessContract.objects.filter(company=company, kind="lease").order_by("pk")
    chilonzor, yunusobod = leases
    # Chilonzor took over the rent already planned: counted once.
    assert chilonzor.rule_id == planned.pk
    assert RecurringRule.objects.filter(company=company, counterparty=landlord).count() == 1
    assert (chilonzor.notice_deadline - today).days == 10
    assert providers.decision_count(people["owner"]) == 1
    # Yunusobod ends in 45 days, paid from dollars.
    assert (yunusobod.ends_on - today).days == 45
    assert yunusobod.rule.currency == "USD"
    assert yunusobod.status == "active"  # 45 days: before the 30-day warning
    lease_insights = providers.lease_ending(type("Ctx", (), {"company": company, "today": today}))
    assert {finding.subject_id for finding in lease_insights} == {chilonzor.pk, yunusobod.pk}
    assert rows["supply"].counterparty.name == "Ko‘kterak Farm Distribyutor"
    assert rows["service"].rule is not None
    # The scans are real PDFs the upload check accepts.
    files = ContractFile.objects.filter(contract__company=company)
    assert files.count() == 3
    for row in files:
        with row.file.open("rb") as handle:
            assert accept_document(handle.read(), allowed=("pdf",)).name.endswith(".pdf")


def test_the_demo_stands_alone(pharmacy):
    company, people = pharmacy
    MoneyAccount.objects.filter(company=company, currency="USD").delete()
    demo.seed(company, people, timezone.now())
    assert BusinessContract.objects.filter(company=company).count() == 4
    assert Counterparty.objects.filter(company=company, name="Akmal Hasanov (ijara)").exists()
    # No dollar account: the Yunusobod rent stays out of the forecast instead of failing.
    yunusobod = BusinessContract.objects.get(company=company, currency="USD")
    assert not yunusobod.in_forecast and yunusobod.rule_id is None


def test_the_small_demo(company, member):
    company.features = ["finance"]
    company.save(update_fields=["features"])
    owner = member(company, "Owner")
    demo.seed_small(company, {"owner": owner}, timezone.now())
    assert BusinessContract.objects.get(company=company).title == "Ombor ijarasi"
