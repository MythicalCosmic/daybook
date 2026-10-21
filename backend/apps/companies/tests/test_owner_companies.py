"""POST /api/v1/owner/companies/ ("New company" in the dashboard switcher, §13.2)."""

import pytest

from apps.accounts.tests.factories import UserFactory
from apps.audit.models import AuditLog
from apps.companies import services
from apps.companies.audit_actions import CompanyAction
from apps.companies.models import Branch, Company
from apps.members.models import Membership
from apps.signin import signup
from apps.signin.tokens import OwnerAccessToken

pytestmark = pytest.mark.django_db

NEW = "/api/v1/owner/companies/"
INFO = "/api/v1/owner/companies/new/"


@pytest.fixture
def owner(company, member):
    return member(company, "Owner")


def test_an_owner_creates_another_company_without_a_code(
    owner, owner_api, settings, django_capture_on_commit_callbacks
):
    settings.COMPANY_SIGNUP = "code"

    with django_capture_on_commit_callbacks(execute=True):
        response = owner_api(owner).post(
            NEW,
            {
                "name": "Baraka Dorixona",
                "timezone": "Asia/Tashkent",
                "language": "uz",
                "base_currency": "USD",
            },
            format="json",
        )

    assert response.status_code == 201, response.content
    company = Company.objects.get(pk=response.json()["id"])
    assert (company.name, company.base_currency, company.default_language) == (
        "Baraka Dorixona",
        "USD",
        "uz",
    )
    membership = Membership.objects.get(company=company, user=owner.user)
    assert membership.role.is_owner and membership.status == Membership.Status.APPROVED
    assert Branch.objects.filter(company=company).count() == 1
    assert AuditLog.objects.filter(action=CompanyAction.CREATED, company_id=company.pk).exists()
    # It appears in the switcher at once.
    me = owner_api(owner).get("/api/v1/owner/me/").json()
    assert company.pk in [row["id"] for row in me["companies"]]


def test_info_tells_what_is_allowed_and_what_can_be_copied(owner, owner_api, settings, company):
    settings.COMPANY_SIGNUP = "code"

    data = owner_api(owner).get(INFO).json()

    assert data["mode"] == "code" and data["allowed"] is True and data["needs_code"] is False
    assert data["owned"] == 1 and data["limit"] == settings.MAX_COMPANIES_PER_USER
    keys = {part["key"] for part in data["parts"]}
    assert {"companies.settings", "companies.modules"} <= keys
    [source] = data["sources"]
    assert source["id"] == company.pk and "companies.settings" in source["parts"]


def test_copying_setup_from_another_company(owner, owner_api, company):
    services.update_settings(company, by=owner, workdays=[0, 1, 2, 3, 4], morning_digest=False)
    services.set_features(company, by=owner, features=["finance", "attendance"])

    response = owner_api(owner).post(
        NEW,
        {
            "name": "Second shop",
            "copy_from": company.pk,
            "parts": ["companies.settings", "companies.modules"],
        },
        format="json",
    )

    assert response.status_code == 201, response.content
    assert response.json()["copied"] == {"companies.settings": 1, "companies.modules": 2}
    new = Company.objects.get(pk=response.json()["id"])
    assert new.workdays == [0, 1, 2, 3, 4] and new.morning_digest is False
    assert new.features == ["finance", "attendance"]
    # People and money are never copied.
    assert Membership.objects.filter(company=new).count() == 1
    assert AuditLog.objects.filter(action=CompanyAction.SETUP_COPIED, company_id=new.pk).exists()


def test_copying_from_a_company_you_cannot_open_is_refused(owner, owner_api, other_company):
    response = owner_api(owner).post(
        NEW,
        {"name": "Sneaky", "copy_from": other_company.pk, "parts": ["companies.settings"]},
        format="json",
    )

    assert response.status_code == 400
    assert not Company.objects.filter(name="Sneaky").exists()


def test_unknown_copy_parts_roll_everything_back(owner, owner_api, company):
    response = owner_api(owner).post(
        NEW,
        {"name": "Half made", "copy_from": company.pk, "parts": ["companies.nope"]},
        format="json",
    )

    assert response.status_code == 400
    assert not Company.objects.filter(name="Half made").exists()


def test_a_newcomer_needs_a_signup_code(settings, company, member):
    settings.COMPANY_SIGNUP = "code"
    # A manager signed in to the dashboard but owning nothing.
    manager = member(company, "Manager")
    client = bearer(manager.user)

    assert client.get(INFO).json()["needs_code"] is True
    refused = client.post(NEW, {"name": "My own shop"}, format="json")
    assert refused.status_code == 400 and "signup code" in refused.json()["detail"]
    assert (
        client.post(
            NEW, {"name": "My own shop", "signup_code": "AAAA-BBBB"}, format="json"
        ).status_code
        == 400
    )

    _code, raw = signup.create_code()
    created = client.post(NEW, {"name": "My own shop", "signup_code": raw.lower()}, format="json")
    assert created.status_code == 201
    assert signup.find(raw) is None  # used up


def test_off_mode_refuses_everyone_but_platform_admins(settings, owner, owner_api):
    settings.COMPANY_SIGNUP = "off"

    info = owner_api(owner).get(INFO).json()
    assert info["allowed"] is False and info["reason"]
    assert owner_api(owner).post(NEW, {"name": "Nope"}, format="json").status_code == 400


def test_the_per_person_limit(settings, owner, owner_api):
    settings.MAX_COMPANIES_PER_USER = 1

    assert owner_api(owner).get(INFO).json()["allowed"] is False
    response = owner_api(owner).post(NEW, {"name": "One too many"}, format="json")
    assert response.status_code == 400 and "most one person can" in response.json()["detail"]


def test_bad_input(owner, owner_api):
    assert owner_api(owner).post(NEW, {"name": ""}, format="json").status_code == 400
    assert (
        owner_api(owner)
        .post(NEW, {"name": "X", "timezone": "Mars/Base"}, format="json")
        .status_code
        == 400
    )
    assert (
        owner_api(owner).post(NEW, {"name": "X", "language": "de"}, format="json").status_code
        == 400
    )


def test_needs_an_owner_token(client, api_as, owner):
    assert client.post(NEW, {"name": "X"}, format="json").status_code == 401
    assert api_as(owner).post(NEW, {"name": "X"}, format="json").status_code == 401


def bearer(user):
    from rest_framework.test import APIClient

    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {OwnerAccessToken.for_user(user)}")
    return api


def test_create_company_for_is_the_bot_path_too(settings):
    settings.COMPANY_SIGNUP = "open"
    user = UserFactory(first_name="Malika")

    company, copied = services.create_company_for(
        user, name="Malika's pharmacy", timezone="Asia/Samarkand"
    )

    assert copied == {}
    assert company.timezone == "Asia/Samarkand"
    assert Membership.objects.get(company=company, user=user).role.is_owner
