import pytest

from apps.companies.models import Company
from apps.groups.tests.factories import TelegramGroupFactory
from apps.members.models import Membership
from apps.members.tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db


def test_admin_creates_company_with_default_roles(admin_client):
    response = admin_client.post(
        "/admin/companies/company/add/",
        {
            "name": "Acme",
            "slug": "acme",
            "timezone": "Asia/Tashkent",
            "default_language": "uz",
            "rejoin_cooldown_hours": 24,
            "morning_report_at": "09:00",
            "evening_report_at": "20:00",
        },
    )

    assert response.status_code == 302
    company = Company.objects.get(slug="acme")
    assert company.accessroles.count() == 5


@pytest.mark.parametrize(
    "url",
    [
        "/admin/companies/company/",
        "/admin/companies/company/add/",
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
