"""The employee mini app keeps itself signed in (`auth/telegram/refresh/`): its refresh token
rotates and is blacklisted after use, and the mini app's and the dashboard's tokens never open
each other's refresh."""

import pytest
from django.core.cache import cache
from django.test import RequestFactory
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.accounts.tests.telegram import BOT_TOKEN, signed_init_data
from apps.signin import services as signin
from apps.signin.tokens import OwnerRefreshToken

pytestmark = pytest.mark.django_db

SIGN_IN = "/api/v1/auth/telegram/"
REFRESH = "/api/v1/auth/telegram/refresh/"
OWNER_TELEGRAM_REFRESH = "/api/v1/owner/auth/telegram/refresh/"
OWNER_REFRESH = "/api/v1/owner/auth/refresh/"
DASHBOARD = {"HTTP_X_REQUESTED_WITH": "dashboard", "HTTP_ORIGIN": "http://testserver"}


@pytest.fixture(autouse=True)
def bot(settings):
    settings.EMPLOYEE_BOT_TOKEN = BOT_TOKEN
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api():
    return APIClient()


def signed_in(api) -> dict:
    response = api.post(SIGN_IN, {"init_data": signed_init_data(user_id=42)}, format="json")
    assert response.status_code == 200, response.content
    return response.data


def refresh(api, token: str):
    return api.post(REFRESH, {"refresh": token}, format="json")


def test_the_refresh_token_gives_the_next_access_token_and_rotates(api):
    first = signed_in(api)

    response = refresh(api, first["refresh"])

    assert response.status_code == 200, response.content
    assert set(response.data) == {"access", "refresh"}
    assert response.data["refresh"] != first["refresh"]
    jti = RefreshToken(first["refresh"], verify=False)["jti"]
    assert BlacklistedToken.objects.filter(token__jti=jti).exists()
    me = APIClient()
    me.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    assert me.get("/api/v1/me/").data["telegram_id"] == 42
    assert refresh(api, response.data["refresh"]).status_code == 200


def test_a_spent_refresh_token_is_refused(api):
    first = signed_in(api)
    refresh(api, first["refresh"])

    assert refresh(api, first["refresh"]).status_code == 401


def test_a_switched_off_account_cant_refresh(api):
    token = signed_in(api)["refresh"]
    User.objects.filter(telegram_id=42).update(is_active=False)

    assert refresh(api, token).status_code == 401


def test_bad_input(api):
    assert api.post(REFRESH, {}, format="json").status_code == 400
    assert refresh(api, "not a token").status_code == 401
    token = signed_in(api)["access"]
    assert refresh(api, token).status_code == 401  # an access token is no refresh token


def test_a_dashboard_token_never_refreshes_here(api, company, member):
    owner = member(company, "Owner", user__telegram_id=4201)
    desktop = signin.issue_session(owner.user, _request())
    telegram = signin.issue_session(owner.user, _request(), telegram=True)

    assert refresh(api, desktop.refresh).status_code == 401
    assert refresh(api, telegram.refresh).status_code == 401
    assert refresh(api, str(OwnerRefreshToken.for_user(owner.user))).status_code == 401


def test_a_mini_app_token_never_refreshes_the_dashboard(api):
    token = signed_in(api)["refresh"]

    assert api.post(OWNER_TELEGRAM_REFRESH, {"refresh": token}, format="json").status_code == 401
    api.cookies[signin.REFRESH_COOKIE] = token
    assert api.post(OWNER_REFRESH, **DASHBOARD).status_code == 401
    # Neither attempt spent it.
    assert refresh(api, token).status_code == 200


def test_refreshes_are_limited_per_person(api, monkeypatch):
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "telegram_auth", "2/min")
    token = signed_in(api)["refresh"]
    for _ in range(2):
        token = refresh(api, token).data["refresh"]

    assert refresh(api, token).status_code == 429


def _request():
    return RequestFactory().post("/", HTTP_USER_AGENT="Chrome on Windows", REMOTE_ADDR="10.0.0.9")
