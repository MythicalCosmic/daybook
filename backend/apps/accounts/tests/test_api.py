import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
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


def test_init_data_is_exchanged_for_an_access_token_only(api, settings):
    settings.EMPLOYEE_BOT_TOKEN = BOT_TOKEN

    response = api.post(
        "/api/v1/auth/telegram/", {"init_data": signed_init_data(user_id=42)}, format="json"
    )

    assert response.status_code == 200
    assert set(response.data) == {"access"}
    assert not OutstandingToken.objects.exists()  # no blacklist row per app launch
    user = User.objects.get(telegram_id=42)
    assert user.telegram_username == "ali"

    me = APIClient()
    me.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    response = me.get("/api/v1/me/")
    assert response.status_code == 200
    assert response.data["telegram_id"] == 42


def test_the_refresh_route_is_gone(api):
    assert api.post("/api/v1/auth/refresh/", {"refresh": "x"}, format="json").status_code == 404


def test_init_data_from_the_owner_bot_does_not_open_the_mini_app(api, settings):
    settings.EMPLOYEE_BOT_TOKEN = BOT_TOKEN
    settings.OWNER_BOT_TOKEN = "777:OWNER-BOT"

    response = api.post(
        "/api/v1/auth/telegram/",
        {"init_data": signed_init_data(token="777:OWNER-BOT")},
        format="json",
    )

    assert response.status_code == 401


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


@pytest.mark.parametrize(
    ("language", "expected"),
    [("ru", "Вы уже прошли регистрацию."), ("uz", "Siz allaqachon ro‘yxatdan o‘tgansiz.")],
)
def test_the_api_answers_in_the_persons_language(api, language, expected):
    membership = MembershipFactory(
        status=Membership.Status.APPROVED,
        onboarded_at="2026-01-01T00:00Z",
        user__language=language,
        user__phone="+998901234567",
    )
    authenticate(api, membership.user)

    response = api.post(
        f"/api/v1/companies/{membership.company_id}/onboarding/",
        {"first_name": "Ali", "last_name": "Valiyev"},
        format="json",
    )

    assert response.status_code == 400
    assert response.data["detail"] == expected
    assert response["Content-Language"] == language
