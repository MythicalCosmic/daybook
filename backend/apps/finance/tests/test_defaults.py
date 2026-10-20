import pytest
from django.utils import translation

from apps.companies.signals import company_created
from apps.finance import conf, defaults, services
from apps.finance.models import Category, FinanceSettings, MoneyAccount

pytestmark = pytest.mark.django_db


def codes(company):
    return set(Category.objects.filter(company=company).values_list("system_code", flat=True))


def test_a_company_gets_the_system_categories_and_two_accounts(company):
    services.create_defaults(company)

    assert codes(company) == defaults.SYSTEM_CODES
    assert len(defaults.SYSTEM_CODES) == 18
    accounts = list(MoneyAccount.objects.filter(company=company).order_by("order"))
    assert [(a.kind, a.name, a.currency, a.branch) for a in accounts] == [
        ("cash", "Cash desk", "UZS", None),
        ("clearing", "Card terminal", "UZS", None),
    ]
    salaries = Category.objects.get(company=company, system_code="salaries")
    assert salaries.is_sensitive
    assert salaries.kind == "expense"
    assert Category.objects.get(company=company, system_code="sales").kind == "income"


def test_ensure_is_idempotent_and_respects_the_owners_changes(company):
    defaults.ensure(company)
    rent = Category.objects.get(company=company, system_code="rent")
    rent.name = "Ijara"
    rent.save()
    MoneyAccount.objects.filter(company=company, kind="cash").update(
        name="Main till", is_active=False
    )
    Category.objects.filter(company=company, system_code="marketing").delete()

    defaults.ensure(company)

    assert Category.objects.filter(company=company).count() == 18
    assert Category.objects.get(company=company, system_code="rent").name == "Ijara"
    assert MoneyAccount.objects.filter(company=company).count() == 2
    assert not MoneyAccount.objects.filter(company=company, name="Cash desk").exists()


def test_an_owners_category_with_the_same_name_is_adopted(company):
    mine = Category.objects.create(company=company, name="Rent", kind="expense")
    clash = Category.objects.create(company=company, name="Sales", kind="expense")

    defaults.ensure(company)

    mine.refresh_from_db()
    assert mine.system_code == "rent"
    clash.refresh_from_db()
    assert clash.system_code == ""
    sales = Category.objects.get(company=company, system_code="sales")
    assert (sales.name, sales.kind) == ("Sales (2)", "income")


def test_names_are_written_in_the_companys_language(company, monkeypatch):
    company.default_language = "ru"
    company.save()
    seen = []
    create = defaults._create_quietly

    def spy(model, **fields):
        seen.append(translation.get_language())
        create(model, **fields)

    monkeypatch.setattr(defaults, "_create_quietly", spy)
    with translation.override("en"):
        defaults.ensure(company)

    assert len(seen) == 20
    assert set(seen) == {"ru"}


def test_a_dollar_company_gets_dollar_accounts(company):
    company.base_currency = "USD"
    company.save()
    defaults.ensure(company)

    assert set(MoneyAccount.objects.filter(company=company).values_list("currency", flat=True)) == {
        "USD"
    }


def test_a_new_company_gets_its_defaults(company):
    company_created.send(sender=type(company), company=company, by=None)

    assert codes(company) == defaults.SYSTEM_CODES
    assert MoneyAccount.objects.filter(company=company).count() == 2


def test_settings_are_made_on_first_read(company):
    assert not FinanceSettings.objects.filter(company=company).exists()

    settings = conf.get_settings(company)

    assert settings == services.get_settings(company)
    assert (settings.locked_until, settings.rate_source, settings.reimburse_via) == (
        None,
        "cbu",
        "payroll",
    )
    assert FinanceSettings.objects.filter(company=company).count() == 1


def test_free_name():
    rows = MoneyAccount.objects.none()
    assert defaults.free_name(rows, "Cash") == "Cash"
