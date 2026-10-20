"""O features/: module switches; switching one on creates its defaults and shows it (§4.4)."""

import pytest

from apps.audit.models import AuditLog
from apps.companies import services
from apps.companies.audit_actions import CompanyAction
from apps.core.exceptions import DomainError
from apps.finance.models import Category, MoneyAccount

pytestmark = pytest.mark.django_db


def url(company):
    return f"/api/v1/owner/companies/{company.pk}/features/"


@pytest.fixture
def owner(company, member):
    return member(company, "Owner")


def test_lists_every_module_with_its_switch(company, owner, owner_api):
    response = owner_api(owner).get(url(company))

    assert response.status_code == 200
    data = response.json()
    assert data["features"] == []
    keys = [module["key"] for module in data["modules"]]
    assert keys == ["finance", "sales", "stock", "attendance", "hr", "payroll", "ai", "recognition"]
    assert not any(module["enabled"] for module in data["modules"])


def test_switching_finance_on_creates_its_defaults(
    company, owner, owner_api, django_capture_on_commit_callbacks
):
    assert not MoneyAccount.objects.filter(company=company).exists()

    with django_capture_on_commit_callbacks(execute=True):
        response = owner_api(owner).patch(url(company), {"features": ["finance"]}, format="json")

    assert response.status_code == 200
    assert response.json()["features"] == ["finance"]
    company.refresh_from_db()
    assert company.features == ["finance"]
    assert MoneyAccount.objects.filter(company=company).exists()
    assert Category.objects.filter(company=company).exists()
    log = AuditLog.objects.get(action=CompanyAction.FEATURES_CHANGED)
    assert log.details["on"] == ["finance"] and log.details["off"] == []


def test_switched_on_modules_show_in_me(company, owner, owner_api):
    owner_api(owner).patch(url(company), {"features": ["sales", "attendance"]}, format="json")

    me = owner_api(owner).get("/api/v1/owner/me/").json()

    [row] = [c for c in me["companies"] if c["id"] == company.pk]
    assert row["features"] == ["sales", "attendance"]


def test_switching_off_keeps_the_data(company, owner):
    services.set_features(company, by=owner, features=["finance"])
    accounts = MoneyAccount.objects.filter(company=company).count()

    services.set_features(company, by=owner, features=[])

    company.refresh_from_db()
    assert company.features == []
    assert MoneyAccount.objects.filter(company=company).count() == accounts


def test_features_are_kept_in_a_fixed_order_without_repeats(company, owner):
    services.set_features(company, by=owner, features=["payroll", "finance", "payroll"])

    company.refresh_from_db()
    assert company.features == ["finance", "payroll"]


def test_unknown_modules_are_refused(company, owner, owner_api):
    response = owner_api(owner).patch(url(company), {"features": ["casino"]}, format="json")

    assert response.status_code == 400
    with pytest.raises(DomainError):
        services.set_features(company, by=owner, features=["casino"])


def test_nothing_changes_nothing_is_audited(company, owner):
    services.set_features(company, by=owner, features=[])

    assert not AuditLog.objects.filter(action=CompanyAction.FEATURES_CHANGED).exists()


def test_only_company_settings_may_switch_modules(company, member, owner_api, other_company):
    manager = member(company, "Manager")

    assert owner_api(manager).get(url(company)).status_code == 403
    assert (
        owner_api(manager).patch(url(company), {"features": ["ai"]}, format="json").status_code
        == 403
    )
    owner = member(company, "Owner")
    assert owner_api(owner).get(url(other_company)).status_code == 404
