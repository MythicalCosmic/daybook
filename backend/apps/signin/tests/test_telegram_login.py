"""Signing in inside Telegram with Mini App initData (§7.2): a session whose refresh token comes
in the body (no cookie), kept alive by `telegram/refresh/` after the hour initData is good for."""

import time
from datetime import timedelta

import pytest
from django.test import RequestFactory
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

from apps.accounts.tests.telegram import signed_init_data
from apps.davomat import conf as davomat_conf
from apps.signin import services
from apps.signin.models import DeviceSession
from apps.signin.services import REFRESH_COOKIE
from apps.signin.tokens import OwnerAccessToken, OwnerRefreshToken

pytestmark = pytest.mark.django_db

URL = "/api/v1/owner/auth/telegram/"
TELEGRAM_REFRESH = "/api/v1/owner/auth/telegram/refresh/"
REFRESH = "/api/v1/owner/auth/refresh/"
LOGOUT = "/api/v1/owner/auth/logout/"
SESSIONS = "/api/v1/owner/auth/sessions/"
IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Mobile/15E148"
)
ANDROID = (
    "Mozilla/5.0 (Linux; Android 14; SM-A515F) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Mobile Safari/537.36 Telegram-Android/11.4.2 (Samsung SM-A515F; Android 14)"
)
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


def login(client, init_data, **headers):
    return client.post(URL, {"init_data": init_data}, content_type="application/json", **headers)


def refresh(client, token, **headers):
    return client.post(
        TELEGRAM_REFRESH, {"refresh": token}, content_type="application/json", **headers
    )


def signed_in(client, telegram_id=7710001, **headers) -> dict:
    response = login(client, signed_init_data(telegram_id, token=OWNER_TOKEN), **headers)
    assert response.status_code == 200, response.content
    return response.json()


def is_blacklisted(raw: str) -> bool:
    jti = OwnerRefreshToken(raw, verify=False)["jti"]
    return BlacklistedToken.objects.filter(token__jti=jti).exists()


def test_owner_bot_init_data_signs_in_with_a_session_and_no_cookie(client, tokens, owner):
    response = login(client, signed_init_data(7710001, token=OWNER_TOKEN), HTTP_USER_AGENT=IPHONE)

    assert response.status_code == 200
    body = response.json()
    token = OwnerAccessToken(body["access"])
    assert str(token["user_id"]) == str(owner.user_id)
    # A real session, its refresh token in the body (Telegram Web never sends a cookie back).
    session = DeviceSession.objects.get()
    assert token["sid"] == session.pk and session.user_id == owner.user_id
    assert session.user_agent == f"Telegram Mini App {IPHONE}"
    refresh_token = OwnerRefreshToken(body["refresh"])
    assert refresh_token["sid"] == session.pk and refresh_token["via"] == "telegram"
    assert REFRESH_COOKIE not in response.cookies
    owner.user.refresh_from_db()
    assert owner.user.last_login is not None


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

    answer = client.post(
        URL,
        {"init_data": signed_init_data(7710001, token=OWNER_TOKEN)},
        content_type="application/json",
        REMOTE_ADDR="10.0.0.7",
    )

    assert answer.status_code == 200


# The session keeps itself alive (telegram/refresh/) -------------------------------------------


def test_the_refresh_token_outlives_the_initdata_hour(client, tokens, owner):
    first = signed_in(client)
    # The same launch data is too old to sign in with now; the session doesn't need it.
    tokens.OWNER_INIT_DATA_MAX_AGE = 0
    assert login(client, signed_init_data(7710001, token=OWNER_TOKEN)).status_code == 401

    response = refresh(client, first["refresh"])

    assert response.status_code == 200, response.content
    body = response.json()
    session = DeviceSession.objects.get()
    assert OwnerAccessToken(body["access"])["sid"] == session.pk
    # Rotated: a new refresh token, the old one blacklisted.
    assert body["refresh"] != first["refresh"]
    assert OwnerRefreshToken(body["refresh"])["via"] == "telegram"
    assert is_blacklisted(first["refresh"])
    assert refresh(client, body["refresh"]).status_code == 200


def test_the_access_token_from_a_refresh_opens_the_owner_api(client, tokens, owner, company):
    access = refresh(client, signed_in(client)["refresh"]).json()["access"]

    response = client.get(
        f"/api/v1/owner/companies/{company.pk}/pulse/", HTTP_AUTHORIZATION=f"Bearer {access}"
    )

    assert response.status_code == 200


def test_two_refreshes_at_once_keep_the_token_the_page_has(client, tokens, owner):
    token = signed_in(client)["refresh"]
    newest = refresh(client, token).json()["refresh"]

    # The same token again within the grace: an access token, no new refresh token.
    again = refresh(client, token)

    assert again.status_code == 200
    assert again.json()["refresh"] is None and again.json()["access"]
    assert refresh(client, newest).status_code == 200


def test_a_replayed_token_ends_the_session(client, tokens, owner):
    token = signed_in(client)["refresh"]
    newest = refresh(client, token).json()["refresh"]
    DeviceSession.objects.update(rotated_at=timezone.now() - timedelta(minutes=5))

    response = refresh(client, token)

    assert response.status_code == 401
    assert response.json()["code"] == "session_ended"
    assert DeviceSession.objects.get().revoked_at is not None
    assert refresh(client, newest).status_code == 401


def test_a_session_revoked_from_the_devices_list_cant_refresh(client, tokens, owner):
    token = signed_in(client)["refresh"]
    services.revoke_session(DeviceSession.objects.get())

    response = refresh(client, token)

    assert response.status_code == 401
    assert response.json()["code"] == "session_ended"


def test_losing_dashboard_access_stops_refreshing(client, tokens, owner):
    token = signed_in(client)["refresh"]
    owner.status = owner.Status.SUSPENDED
    owner.save(update_fields=["status"])

    assert refresh(client, token).status_code == 401


def test_the_two_kinds_of_refresh_token_stay_apart(client, tokens, owner):
    telegram = signed_in(client)["refresh"]
    desktop = services.issue_session(owner.user, _request(IPHONE))

    # A Telegram token in the cookie, a desktop one in the body: both refused, nothing ended.
    client.cookies[REFRESH_COOKIE] = telegram
    assert client.post(REFRESH, **DASHBOARD).status_code == 401
    del client.cookies[REFRESH_COOKIE]
    assert refresh(client, desktop.refresh).status_code == 401
    assert not DeviceSession.objects.filter(revoked_at__isnull=False).exists()
    assert refresh(client, telegram).status_code == 200


def test_bad_refresh_input(client, tokens, owner):
    assert client.post(TELEGRAM_REFRESH, {}, content_type="application/json").status_code == 400
    assert refresh(client, "not a token").status_code == 401
    token = signed_in(client)["refresh"]
    assert refresh(client, token[:-2] + "xx").status_code == 401


def test_logout_with_the_kept_token_ends_the_telegram_session(client, tokens, owner):
    token = signed_in(client)["refresh"]

    response = client.post(LOGOUT, {"refresh": token}, content_type="application/json", **DASHBOARD)

    assert response.status_code == 204
    assert DeviceSession.objects.get().revoked_at is not None
    assert is_blacklisted(token)
    assert refresh(client, token).status_code == 401


def test_logout_prefers_the_cookie(client, tokens, owner):
    telegram = signed_in(client)["refresh"]
    desktop = services.issue_session(owner.user, _request(IPHONE))
    client.cookies[REFRESH_COOKIE] = desktop.refresh

    client.post(LOGOUT, {"refresh": telegram}, content_type="application/json", **DASHBOARD)

    assert DeviceSession.objects.get(pk=desktop.session.pk).revoked_at is not None
    assert DeviceSession.objects.exclude(pk=desktop.session.pk).get().revoked_at is None


def test_the_devices_list_names_telegram(client, tokens, owner):
    body = signed_in(client, HTTP_USER_AGENT=IPHONE)
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {body['access']}")

    [row] = api.get(SESSIONS).json()

    assert row["device"] == {
        "label": "Telegram · iOS",
        "browser": "Telegram",
        "system": "iOS",
        "kind": "phone",
    }
    assert row["current"] is True
    # Rotation keeps the mark, whatever the webview says now.
    refresh(client, body["refresh"], HTTP_USER_AGENT=ANDROID)
    assert DeviceSession.objects.get().user_agent == f"Telegram Mini App {ANDROID}"


def test_a_new_launch_replaces_the_same_devices_telegram_session(client, tokens, owner):
    first = signed_in(client, HTTP_USER_AGENT=IPHONE)
    desktop = services.issue_session(owner.user, _request(IPHONE))
    other_phone = signed_in(client, HTTP_USER_AGENT=ANDROID)

    second = signed_in(client, HTTP_USER_AGENT=IPHONE)

    active = DeviceSession.objects.filter(revoked_at__isnull=True)
    assert set(active.values_list("pk", flat=True)) == {
        desktop.session.pk,
        OwnerAccessToken(other_phone["access"])["sid"],
        OwnerAccessToken(second["access"])["sid"],
    }
    assert refresh(client, first["refresh"]).status_code == 401
    assert refresh(client, second["refresh"]).status_code == 200


def test_refreshes_are_throttled_per_session(client, tokens, owner, monkeypatch):
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "owner_refresh", "2/min")
    token = signed_in(client)["refresh"]
    for _ in range(2):
        token = refresh(client, token).json()["refresh"]

    assert refresh(client, token).status_code == 429


def _request(agent: str):
    return RequestFactory().post("/", HTTP_USER_AGENT=agent, REMOTE_ADDR="10.0.0.9")


# The Davomat edition: the organization's own bot opens the web app ---------------------------

DAVOMAT_TOKEN = "7701234567:AAFakeDavomatTokenForTestsOnly-abcdefgh"


def _save_bot_token(company) -> None:
    row = davomat_conf.get_settings(company)
    row.bot_token, row.bot_username = DAVOMAT_TOKEN, "namuna_davomat_bot"
    row.save(update_fields=["bot_token", "bot_username"])


@pytest.fixture
def davomat(settings, company):
    """Davomat with its bot connected in Settings, and no Daybook bot tokens at all."""
    settings.EDITION = "davomat"
    settings.OWNER_BOT_TOKEN = settings.EMPLOYEE_BOT_TOKEN = ""
    settings.OWNER_INIT_DATA_MAX_AGE = 3600
    _save_bot_token(company)
    return settings


def test_in_davomat_its_own_bot_signs_in_and_the_session_lives_on(client, davomat, owner):
    names = (owner.user.first_name, owner.user.last_name)

    response = login(client, signed_init_data(7710001, token=DAVOMAT_TOKEN))

    assert response.status_code == 200, response.content
    body = response.json()
    assert str(OwnerAccessToken(body["access"])["user_id"]) == str(owner.user_id)
    # The names the administrator typed stay (Telegram calls this person "Ali Valiyev").
    owner.user.refresh_from_db()
    assert (owner.user.first_name, owner.user.last_name) == names
    davomat.OWNER_INIT_DATA_MAX_AGE = 0
    assert refresh(client, body["refresh"]).status_code == 200


def test_in_davomat_the_other_bots_still_work_after_it(client, davomat, owner):
    davomat.OWNER_BOT_TOKEN = OWNER_TOKEN

    assert login(client, signed_init_data(7710001, token=OWNER_TOKEN)).status_code == 200


def test_in_davomat_an_unlinked_telegram_has_no_access(client, davomat, owner, company, member):
    member(company, "Employee", user__telegram_id=7710002)

    stranger = login(client, signed_init_data(7719999, token=DAVOMAT_TOKEN))
    employee = login(client, signed_init_data(7710002, token=DAVOMAT_TOKEN))

    assert stranger.status_code == employee.status_code == 403
    assert employee.json()["code"] == "no_access"


def test_in_davomat_a_forged_or_old_launch_is_refused(client, davomat, owner):
    old = int(time.time()) - 3601

    assert login(client, signed_init_data(7710001, token=OWNER_TOKEN)).status_code == 401
    stale = login(client, signed_init_data(7710001, auth_date=old, token=DAVOMAT_TOKEN))
    assert stale.status_code == 401


def test_daybook_never_takes_the_davomat_bots_word(client, tokens, owner, company):
    _save_bot_token(company)

    response = login(client, signed_init_data(7710001, token=DAVOMAT_TOKEN))

    assert response.status_code == 401
    assert response.json()["code"] == "init_data_invalid"
