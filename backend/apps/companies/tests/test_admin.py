import re

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.companies.admin import CompanyForm
from apps.companies.models import Company
from apps.companies.signals import company_created
from apps.groups.tests.factories import TelegramGroupFactory
from apps.members.models import Membership
from apps.members.tests.factories import MembershipFactory
from apps.reminders.models import ReminderPolicy
from apps.tasks.tests.factories import jpeg_bytes

pytestmark = pytest.mark.django_db


def test_admin_sets_up_a_new_company_like_the_owner_bot(
    admin_client, django_capture_on_commit_callbacks
):
    created = []
    company_created.connect(lambda **kwargs: created.append(kwargs), weak=False, dispatch_uid="t")
    try:
        with django_capture_on_commit_callbacks(execute=True):
            response = admin_client.post(
                "/admin/companies/company/add/",
                {
                    "name": "Acme",
                    "slug": "acme",
                    "timezone": "Asia/Tashkent",
                    "default_language": "uz",
                    "base_currency": "UZS",
                    "rejoin_cooldown_hours": 24,
                    "morning_report_at": "09:00",
                    "evening_report_at": "20:00",
                    "owner_sees_personal_tasks": "on",
                },
            )
    finally:
        company_created.disconnect(dispatch_uid="t")

    assert response.status_code == 302
    company = Company.objects.get(slug="acme")
    assert company.accessroles.count() == 6
    assert [branch.name for branch in company.branches.all()] == ["Acme"]
    assert ReminderPolicy.objects.filter(company=company, is_default=True).exists()
    assert [(kwargs["company"], kwargs["by"]) for kwargs in created] == [(company, None)]


def test_admin_logos_are_reencoded(admin_client, company, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    form = CompanyForm(
        data={
            "name": company.name,
            "slug": company.slug,
            "timezone": company.timezone,
            "default_language": company.default_language,
            "base_currency": "UZS",
            "rejoin_cooldown_hours": 24,
            "morning_report_at": "09:00",
            "evening_report_at": "20:00",
        },
        files={"logo": SimpleUploadedFile("logo.png", jpeg_bytes(), "image/png")},
        instance=company,
    )

    assert form.is_valid(), form.errors
    company = form.save()
    assert re.fullmatch(r"logos/[0-9a-f]{32}\.jpg", company.logo.name)


def test_admin_refuses_a_logo_that_is_not_a_picture(company):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>'
    form = CompanyForm(
        data={"name": company.name},
        files={"logo": SimpleUploadedFile("logo.png", svg, "image/png")},
        instance=company,
    )

    assert not form.is_valid()
    assert "logo" in form.errors


def test_branches_have_an_admin_but_are_never_deleted(admin_client, company):
    branch = company.branches.get()

    page = admin_client.get(f"/admin/companies/branch/{branch.pk}/change/")
    listing = admin_client.get("/admin/companies/branch/")

    assert page.status_code == 200
    assert listing.status_code == 200
    assert admin_client.post(f"/admin/companies/branch/{branch.pk}/delete/").status_code == 403


@pytest.mark.parametrize(
    "url",
    [
        "/admin/companies/company/",
        "/admin/companies/company/add/",
        "/admin/companies/branch/",
        "/admin/companies/branch/add/",
        "/admin/members/membership/",
        "/admin/members/accessrole/",
        "/admin/members/position/",
        "/admin/accounts/user/",
        "/admin/groups/telegramgroup/",
        "/admin/groups/groupreport/",
    ],
)
def test_admin_pages_render(admin_client, company, url):
    assert admin_client.get(url).status_code == 200


def test_company_change_page_renders_with_inlines(admin_client, company):
    TelegramGroupFactory(company=company, title="Shop team")

    response = admin_client.get(f"/admin/companies/company/{company.pk}/change/")

    assert response.status_code == 200
    assert b"Employee" in response.content
    assert b"Shop team" in response.content


def test_admin_approve_action(admin_client, company):
    request = MembershipFactory(company=company)

    response = admin_client.post(
        "/admin/members/membership/",
        {"action": "approve_selected", "_selected_action": [request.pk]},
    )

    assert response.status_code == 302
    request.refresh_from_db()
    assert request.status == Membership.Status.APPROVED
