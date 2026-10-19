import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.accounts.tests.factories import UserFactory
from apps.accounts.tests.telegram import BOT_TOKEN, signed_init_data
from apps.members.models import Membership
from apps.members.tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def api():
    return APIClient()


def authenticate(api: APIClient, user: User) -> APIClient:
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return api


def test_init_data_is_exchanged_for_tokens(api, settings):
    settings.EMPLOYEE_BOT_TOKEN = BOT_TOKEN

    response = api.post(
        "/api/v1/auth/telegram/", {"init_data": signed_init_data(user_id=42)}, format="json"
    )

    assert response.status_code == 200
    assert {"access", "refresh"} <= response.data.keys()
    user = User.objects.get(telegram_id=42)
    assert user.telegram_username == "ali"

    me = authenticate(APIClient(), user).get("/api/v1/me/")
    assert me.status_code == 200
    assert me.data["telegram_id"] == 42


def test_bad_init_data_gets_401(api, settings):
    settings.EMPLOYEE_BOT_TOKEN = BOT_TOKEN

    response = api.post("/api/v1/auth/telegram/", {"init_data": "hash=forged"}, format="json")

    assert response.status_code == 401


def test_me_requires_authentication(api):
    assert api.get("/api/v1/me/").status_code == 401


def test_me_lists_memberships_with_permissions(api, company, member):
    manager = member(company, "Manager")

    response = authenticate(api, manager.user).get("/api/v1/me/")

    [membership] = response.data["memberships"]
    assert membership["company"]["name"] == company.name
    assert membership["status"] == Membership.Status.APPROVED
    assert membership["role"] == "Manager"
    assert "members.approve" in membership["permissions"]
    assert "roles.manage" not in membership["permissions"]
    assert membership["is_onboarded"] is False


def test_pending_membership_has_no_permissions(api, company):
    pending = MembershipFactory(company=company)

    response = authenticate(api, pending.user).get("/api/v1/me/")

    [membership] = response.data["memberships"]
    assert membership["permissions"] == []
    assert membership["role"] is None


def test_me_only_lets_the_language_change(api):
    user = UserFactory(language="uz")

    response = authenticate(api, user).patch(
        "/api/v1/me/", {"language": "ru", "telegram_id": 1, "phone": "+1"}, format="json"
    )

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.language == "ru"
    assert user.telegram_id != 1
    assert user.phone == ""
