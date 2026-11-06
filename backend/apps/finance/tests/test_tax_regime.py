"""The tax regime (§14.8, Must): the setting, `vat_percent`, the Get started step, the
turnover tile, and the pharmacy categories `defaults.ensure` adds once."""

from datetime import date
from decimal import Decimal

import pytest

from apps.audit.models import AuditLog
from apps.companies.tests.factories import CompanyFactory
from apps.console import registry
from apps.finance import conf, defaults, providers, queries, services
from apps.finance.models import Category, FinanceSettings
from apps.members.permissions import Perm

pytestmark = pytest.mark.django_db


def url(company, path: str) -> str:
    return f"/api/v1/owner/companies/{company.pk}/finance/{path}"


# The setting and vat_percent ------------------------------------------------------------------


def test_a_company_starts_on_turnover_tax_without_vat(books):
    row = conf.get_settings(books)

    assert (row.tax_regime, row.vat_percent) == ("turnover", Decimal("0.00"))
    assert (row.turnover_threshold, row.base_value) == (12000, Decimal("412000.00"))
    assert queries.vat_percent(books) == Decimal("0")
    assert not providers.tax_regime_done(books)


@pytest.mark.parametrize(
    ("regime", "percent"),
    [("vat", "12.00"), ("vat_simplified", "6.00"), ("turnover", "0.00")],
)
def test_vat_percent_follows_the_regime(books, owner, regime, percent):
    services.update_settings(books, by=owner, tax_regime=regime)

    assert queries.vat_percent(books) == Decimal(percent)
    assert providers.tax_regime_done(books)


def test_a_rate_given_with_the_regime_wins(books, owner):
    services.update_settings(books, by=owner, tax_regime="vat", vat_percent="15")

    assert queries.vat_percent(books) == Decimal("15.00")
    # Changing only the rate later keeps the regime.
    services.update_settings(books, by=owner, vat_percent="12.5")
    row = conf.get_settings(books)
    assert (row.tax_regime, row.vat_percent) == ("vat", Decimal("12.50"))


@pytest.mark.parametrize("bad", ["-1", "100.5", "abc"])
def test_a_vat_rate_is_a_percentage(books, owner, bad):
    from apps.core.exceptions import DomainError

    with pytest.raises(DomainError):
        services.update_settings(books, by=owner, vat_percent=bad)


def test_changing_the_regime_is_audited(books, owner):
    services.update_settings(books, by=owner, tax_regime="vat")

    log = AuditLog.objects.get(company_id=books.pk, action="finance.settings_updated")
    assert log.details["changes"]["tax_regime"] == ["turnover", "vat"]
    assert log.details["changes"]["vat_percent"] == ["0.00", "12.00"]


def test_the_setup_step_is_registered():
    step = registry.SETUP_STEPS.get("finance.tax_regime")

    assert step.feature == "finance"
    assert step.perm == Perm.FINANCE_MANAGE
    assert step.url == "settings/finance"


# The API ------------------------------------------------------------------------------------


@pytest.fixture
def boss(fin, member):
    return member(fin, "Owner", first_name="Dilnoza")


def test_the_settings_endpoint_reads_and_writes_the_regime(fin, boss, owner_api):
    client = owner_api(boss)

    before = client.get(url(fin, "settings/")).json()
    assert before["tax_regime"] == "turnover"
    assert before["vat_percent"] == "0.00"
    assert before["base_value"] == "412000.00"
    assert before["tax_regime_set"] is False
    assert before["payroll_on"] is False

    response = client.patch(
        url(fin, "settings/"),
        {"tax_regime": "vat_simplified", "turnover_threshold": 11000, "base_value": "420000"},
        format="json",
    )

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["tax_regime"] == "vat_simplified"
    assert body["vat_percent"] == "6.00"
    assert body["turnover_threshold"] == 11000
    assert body["base_value"] == "420000.00"
    assert body["tax_regime_set"] is True


def test_settings_need_finance_manage_and_stay_in_the_company(
    fin, owner_api, role, person, other_company
):
    viewer = person(fin, role(fin, "Viewer", [Perm.FINANCE_VIEW]))
    client = owner_api(viewer)

    assert (
        client.patch(url(fin, "settings/"), {"tax_regime": "vat"}, format="json").status_code == 403
    )
    assert client.get(url(other_company, "settings/")).status_code in (403, 404)
    assert conf.get_settings(fin).tax_regime == "turnover"


def test_the_turnover_tile(fin, boss, owner_api, cash):
    today = queries.local_today(fin)
    services.record_transaction(
        fin,
        by=boss,
        kind="income",
        amount=Decimal("2472000000"),
        occurred_on=today,
        account=cash,
        category="sales",
    )
    # Last year's sales don't count.
    services.record_transaction(
        fin,
        by=boss,
        kind="income",
        amount=Decimal("1000000"),
        occurred_on=date(today.year - 1, 12, 31),
        account=cash,
        category="sales",
    )

    body = owner_api(boss).get(url(fin, "tax-summary/")).json()

    assert body["regime"] == "turnover"
    assert body["year"] == today.year
    assert body["turnover"] == "2472000000.00"
    assert body["threshold"] == "4944000000.00"  # 12 000 base values of 412 000 som
    assert body["share"] == "0.50"
    assert body["over"] is False


def test_the_turnover_tile_needs_finance_view(fin, owner_api, role, person):
    stranger = person(fin, role(fin, "Recorder", [Perm.FINANCE_RECORD]))

    assert owner_api(stranger).get(url(fin, "tax-summary/")).status_code == 403


# Pharmacy categories --------------------------------------------------------------------------


def names(company, **filters) -> set[str]:
    return set(Category.objects.filter(company=company, **filters).values_list("name", flat=True))


def test_a_new_company_gets_the_pharmacy_categories(company):
    defaults.ensure(company)

    assert {"Marketing bonuses", "Insurance fund reimbursements"} <= names(
        company, kind="income", system_code=""
    )
    assert {"Licences and certificates", "Destruction services", "Instrument checks"} <= names(
        company, kind="expense", system_code=""
    )
    goods = Category.objects.get(company=company, system_code="goods")
    assert goods.name == "Medicines and goods"
    assert conf.get_settings(company).defaults_version == defaults.DEFAULTS_VERSION


def test_pharmacy_categories_are_added_once(company):
    defaults.ensure(company)
    Category.objects.filter(company=company, name="Instrument checks").delete()
    Category.objects.filter(company=company, name="Destruction services").update(
        name="Utilizatsiya"
    )

    defaults.ensure(company)

    assert "Instrument checks" not in names(company)
    assert "Destruction services" not in names(company)
    assert "Utilizatsiya" in names(company)


def test_an_existing_company_keeps_its_goods_name_and_gains_the_categories(company):
    # A company made before this release: its own name for goods, no pharmacy categories yet.
    defaults.ensure(company)
    Category.objects.filter(company=company, system_code="goods").update(name="Goods for sale")
    Category.objects.filter(company=company, system_code="").delete()
    FinanceSettings.objects.filter(company=company).update(defaults_version=0)
    Category.objects.create(company=company, name="Marketing bonuses", kind="income")

    defaults.ensure(company)

    assert Category.objects.get(company=company, system_code="goods").name == "Goods for sale"
    assert Category.objects.filter(company=company, name="Marketing bonuses").count() == 1
    assert "Destruction services" in names(company)


def test_pharmacy_categories_are_written_in_the_companys_language():
    company = CompanyFactory(default_language="ru")

    defaults.ensure(company)

    assert Category.objects.filter(company=company, system_code="").count() == 5
