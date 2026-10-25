"""Signing in inside Telegram with Mini App initData (§7.2): no cookie, no session."""

import time

import pytest
from rest_framework.throttling import SimpleRateThrottle

from apps.accounts.tests.telegram import signed_init_data
from apps.signin.models import DeviceSession
from apps.signin.services import REFRESH_COOKIE
from apps.signin.tokens import OwnerAccessToken

pytestmark = pytest.mark.django_db

URL = "/api/v1/owner/auth/telegram/"
REFRESH = "/api/v1/owner/auth/refresh/"
DASHBOARD = {"HTTP_X_REQUESTED_WITH": "dashboard", "HTTP_ORIGIN": "http://testserver"}
OWNER_TOKEN = "43:OWNER-TEST"
EMPLOYEE_TOKEN = "42:EMPLOYEE-TEST"


@pytest.fixture
def tokens(settings):
    settings.OWNER_BOT_TOKEN = OWNER_TOKEN
    settings.EMPLOYEE_BOT_TOKEN = EMPLOYEE_TOKEN
    settings.OWNER_INIT_DATA_MAX_AGE = 3600
    return settings


@pytest.fixture
def owner(company, member):
    return member(company, "Owner", user__telegram_id=7710001)


def login(client, init_data):
    return client.post(URL, {"init_data": init_data}, content_type="application/json")


def test_owner_bot_init_data_signs_in_without_a_cookie(client, tokens, owner):
    response = login(client, signed_init_data(7710001, token=OWNER_TOKEN))

    assert response.status_code == 200
    token = OwnerAccessToken(response.json()["access"])
    assert str(token["user_id"]) == str(owner.user_id)
    assert "sid" not in token
    assert REFRESH_COOKIE not in response.cookies
    assert DeviceSession.objects.count() == 0


def test_employee_bot_init_data_works_as_a_fallback(client, tokens, owner):
    response = login(client, signed_init_data(7710001, token=EMPLOYEE_TOKEN))

    assert response.status_code == 200


def test_it_works_with_only_the_employee_bot_configured(client, tokens, owner):
    tokens.OWNER_BOT_TOKEN = ""

    assert login(client, signed_init_data(7710001, token=EMPLOYEE_TOKEN)).status_code == 200


def test_init_data_older_than_the_owner_limit_is_refused(client, tokens, owner):
    # A day-old launch would still open the mini app (24 h); the dashboard allows an hour.
    old = int(time.time()) - 3601

    response = login(client, signed_init_data(7710001, auth_date=old, token=OWNER_TOKEN))

    assert response.status_code == 401
    assert response.json()["code"] == "init_data_invalid"


def test_a_forged_signature_is_refused(client, tokens, owner):
    response = login(client, signed_init_data(7710001, token="999:SOMEONE-ELSE"))

    assert response.status_code == 401


def test_people_without_dashboard_access_are_refused(client, tokens, company, member):
    member(company, "Employee", user__telegram_id=7710002)

    response = login(client, signed_init_data(7710002, token=OWNER_TOKEN))

    assert response.status_code == 403
    assert response.json()["code"] == "no_access"


def test_unknown_telegram_users_are_refused_and_not_created(client, tokens, django_user_model):
    before = django_user_model.objects.count()

    response = login(client, signed_init_data(7719999, token=OWNER_TOKEN))

    assert response.status_code == 403
    assert django_user_model.objects.count() == before


def test_the_access_token_opens_the_owner_api(client, tokens, owner, company):
    access = login(client, signed_init_data(7710001, token=OWNER_TOKEN)).json()["access"]

    response = client.get(
        f"/api/v1/owner/companies/{company.pk}/pulse/", HTTP_AUTHORIZATION=f"Bearer {access}"
    )

    assert response.status_code == 200


def test_bad_input(client, tokens):
    assert client.post(URL, {}, content_type="application/json").status_code == 400
    assert login(client, "not init data").status_code == 401


def test_it_is_throttled_per_client_ip(client, tokens, owner, monkeypatch):
    """A flood ceiling per address (behind the proxy the client is the last forwarded hop),
    lowered here; the shipped one fits a shift behind one carrier address and the limit per
    person is apps/core/tests/test_throttles.py's."""
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "owner_telegram_address", "30/min")
    for _ in range(30):
        assert (
            client.post(
                URL, {"init_data": "x"}, content_type="application/json", REMOTE_ADDR="10.0.0.9"
            ).status_code
            == 401
        )

    blocked = client.post(
        URL, {"init_data": "x"}, content_type="application/json", REMOTE_ADDR="10.0.0.9"
    )
    elsewhere = client.post(
        URL,
        {"init_data": signed_init_data(7710001, token=OWNER_TOKEN)},
        content_type="application/json",
        REMOTE_ADDR="10.0.0.9",
        HTTP_X_FORWARDED_FOR="84.54.70.2",
    )

    assert blocked.status_code == 429
    assert elsewhere.status_code == 200


def test_it_counts_apart_from_the_dashboards_cookie_endpoints(client, tokens, owner, monkeypatch):
    """Refresh, logout and the dev login share `owner_auth_address`; this has its own."""
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "owner_auth_address", "30/min")
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "owner_telegram_address", "30/min")
    for _ in range(30):
        client.post(REFRESH, REMOTE_ADDR="10.0.0.7", **DASHBOARD)
    assert client.post(REFRESH, REMOTE_ADDR="10.0.0.7", **DASHBOARD).status_code == 429

    signed_in = client.post(
        URL,
        {"init_data": signed_init_data(7710001, token=OWNER_TOKEN)},
        content_type="application/json",
        REMOTE_ADDR="10.0.0.7",
    )

    assert signed_in.status_code == 200
