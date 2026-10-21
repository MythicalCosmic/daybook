"""O settings/ and settings/logo/: the company's own settings (§4.4)."""

import io
from datetime import date
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.audit.models import AuditLog
from apps.companies.audit_actions import CompanyAction
from apps.companies.models import Company
from apps.finance import services as finance
from apps.finance.tests.factories import MoneyAccountFactory

pytestmark = pytest.mark.django_db


def url(company, path="settings/"):
    return f"/api/v1/owner/companies/{company.pk}/{path}"


@pytest.fixture
def owner(company, member):
    return member(company, "Owner")


def jpeg(size=(1600, 900), color=(198, 113, 57)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "PNG")
    return out.getvalue()


def test_everyone_with_dashboard_access_reads_the_settings(company, member, owner_api):
    manager = member(company, "Manager")

    response = owner_api(manager).get(url(company))

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == company.name
    assert data["timezone"] == "Asia/Tashkent"
    assert data["morning_report_at"] == "09:00" and data["evening_report_at"] == "20:00"
    assert data["workdays"] == [0, 1, 2, 3, 4, 5]
    assert data["base_currency"] == "UZS" and data["base_currency_locked"] is False
    assert data["logo"] is None and data["setup_completed"] is False


def test_owner_changes_settings_and_it_is_audited(company, owner, owner_api):
    response = owner_api(owner).patch(
        url(company),
        {
            "name": "Baraka Market",
            "timezone": "Asia/Samarkand",
            "default_language": "ru",
            "workdays": [0, 1, 2, 3, 4],
            "morning_report_at": "08:30",
            "evening_report_at": "21:15",
            "morning_digest": False,
            "rejoin_cooldown_hours": 48,
            "owner_sees_personal_tasks": False,
            "team_directory_phones": False,
        },
        format="json",
    )

    assert response.status_code == 200, response.content
    company.refresh_from_db()
    assert company.name == "Baraka Market"
    assert company.timezone == "Asia/Samarkand" and company.default_language == "ru"
    assert company.workdays == [0, 1, 2, 3, 4]
    assert str(company.morning_report_at) == "08:30:00"
    assert (company.morning_digest, company.owner_sees_personal_tasks) == (False, False)
    log = AuditLog.objects.get(action=CompanyAction.SETTINGS_CHANGED)
    assert log.actor == owner.user
    assert log.details["changes"]["name"] == [log.details["changes"]["name"][0], "Baraka Market"]
    assert "rejoin_cooldown_hours" in log.details["changes"]


def test_a_manager_cannot_change_settings(company, member, owner_api):
    manager = member(company, "Manager")

    response = owner_api(manager).patch(url(company), {"name": "Mine"}, format="json")

    assert response.status_code == 403
    company.refresh_from_db()
    assert company.name != "Mine"


def test_another_companys_settings_are_not_found(company, other_company, owner, owner_api):
    assert owner_api(owner).get(url(other_company)).status_code == 404
    assert (
        owner_api(owner).patch(url(other_company), {"name": "x"}, format="json").status_code == 404
    )


def test_employees_without_dashboard_access_are_refused(company, member, owner_api):
    worker = member(company, "Employee")

    assert owner_api(worker).get(url(company)).status_code == 403


@pytest.mark.parametrize(
    "patch",
    [
        {"name": "  "},
        {"timezone": "Mars/Olympus"},
        {"workdays": []},
        {"workdays": [7]},
        {"base_currency": "EUR"},
        {"rejoin_cooldown_hours": 1000},
        {"morning_report_at": "20:00"},
    ],
)
def test_bad_settings_are_refused(company, owner, owner_api, patch):
    response = owner_api(owner).patch(url(company), patch, format="json")

    assert response.status_code == 400


def test_base_currency_changes_until_money_is_booked(company, owner, owner_api):
    assert (
        owner_api(owner).patch(url(company), {"base_currency": "USD"}, format="json").status_code
        == 200
    )
    owner_api(owner).patch(url(company), {"base_currency": "UZS"}, format="json")
    company.refresh_from_db()
    account = MoneyAccountFactory(company=company, name="Kassa")
    finance.record_transaction(
        company,
        by=owner,
        kind="opening",
        account=account,
        amount=Decimal("150000.00"),
        occurred_on=date.today(),
    )

    response = owner_api(owner).patch(url(company), {"base_currency": "USD"}, format="json")

    assert response.status_code == 400
    assert "stays UZS" in response.json()["detail"]
    assert owner_api(owner).get(url(company)).json()["base_currency_locked"] is True
    # Sending the same currency again is fine.
    assert (
        owner_api(owner).patch(url(company), {"base_currency": "UZS"}, format="json").status_code
        == 200
    )


def test_logo_is_reencoded_and_can_be_removed(company, owner, owner_api, settings):
    upload = SimpleUploadedFile("logo.png", jpeg(), content_type="image/png")

    response = owner_api(owner).post(
        url(company, "settings/logo/"), {"logo": upload}, format="multipart"
    )

    assert response.status_code == 200, response.content
    company.refresh_from_db()
    assert company.logo.name.startswith("logos/") and company.logo.name.endswith(".jpg")
    with Image.open(company.logo.path) as image:
        assert max(image.size) == 1024 and image.format == "JPEG"
    assert response.json()["logo"].endswith(".jpg")
    assert AuditLog.objects.filter(action=CompanyAction.LOGO_CHANGED).count() == 1

    removed = owner_api(owner).delete(url(company, "settings/logo/"))

    assert removed.status_code == 200 and removed.json()["logo"] is None
    assert not Company.objects.get(pk=company.pk).logo


def test_a_logo_that_is_not_a_picture_is_refused(company, owner, owner_api):
    fake = SimpleUploadedFile("logo.png", b"<svg onload=alert(1)>", content_type="image/png")

    response = owner_api(owner).post(
        url(company, "settings/logo/"), {"logo": fake}, format="multipart"
    )

    assert response.status_code == 400
    company.refresh_from_db()
    assert not company.logo


def test_the_logo_needs_company_settings(company, member, owner_api):
    manager = member(company, "Manager")
    upload = SimpleUploadedFile("logo.png", jpeg(), content_type="image/png")

    assert (
        owner_api(manager)
        .post(url(company, "settings/logo/"), {"logo": upload}, format="multipart")
        .status_code
        == 403
    )
