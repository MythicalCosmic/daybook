"""Desktop sessions: refresh rotation, reuse detection, logout (docs/PLAN-OWNER.md §7.3)."""

from datetime import timedelta

import pytest
from django.test import RequestFactory
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from apps.signin import services
from apps.signin.models import DeviceSession
from apps.signin.tokens import OwnerAccessToken, OwnerRefreshToken

pytestmark = pytest.mark.django_db

REFRESH = "/api/v1/owner/auth/refresh/"
LOGOUT = "/api/v1/owner/auth/logout/"
DASHBOARD = {"HTTP_X_REQUESTED_WITH": "dashboard", "HTTP_ORIGIN": "http://testserver"}


@pytest.fixture
def owner(company, member):
    return member(company, "Owner")


def sign_in(client, user) -> services.IssuedSession:
    request = RequestFactory().post("/", HTTP_USER_AGENT="Chrome on Windows", REMOTE_ADDR="10.0.0.9")
    issued = services.issue_session(user, request)
    client.cookies[services.REFRESH_COOKIE] = issued.refresh
    return issued


def refresh(client, **headers):
    return client.post(REFRESH, **(DASHBOARD | headers))


def is_blacklisted(raw: str) -> bool:
    jti = OwnerRefreshToken(raw, verify=False)["jti"]
    return BlacklistedToken.objects.filter(token__jti=jti).exists()


def test_a_session_has_a_device_row_and_tokens_that_name_it(client, owner):
    issued = sign_in(client, owner.user)

    session = DeviceSession.objects.get(user=owner.user)
    assert issued.session == session
    assert session.user_agent == "Chrome on Windows"
    assert session.ip == "10.0.0.9"
    assert OwnerAccessToken(issued.access)["sid"] == session.pk
    assert OwnerRefreshToken(issued.refresh)["jti"] == session.refresh_jti


def test_refresh_rotates_the_cookie_and_returns_an_access_token(client, owner, owner_api):
    first = sign_in(client, owner.user)

    response = refresh(client)

    assert response.status_code == 200
    access = OwnerAccessToken(response.data["access"])
    assert access["sid"] == first.session.pk
    cookie = response.cookies[services.REFRESH_COOKIE]
    assert cookie.value and cookie.value != first.refresh
    assert cookie["httponly"]
    assert cookie["samesite"] == "Strict"
    assert cookie["path"] == "/api/v1/owner/auth/"
    assert cookie["secure"]  # DEBUG is off
    session = DeviceSession.objects.get(pk=first.session.pk)
    assert session.refresh_jti == OwnerRefreshToken(cookie.value)["jti"]
    assert session.previous_jti == OwnerRefreshToken(first.refresh, verify=False)["jti"]
    assert is_blacklisted(first.refresh)


def test_the_new_access_token_opens_owner_endpoints(client, owner):
    sign_in(client, owner.user)
    access = refresh(client).data["access"]

    response = client.get("/api/v1/owner/me/", HTTP_AUTHORIZATION=f"Bearer {access}")

    assert response.status_code == 200


def test_refresh_needs_the_dashboard_header(client, owner):
    sign_in(client, owner.user)

    assert client.post(REFRESH, HTTP_ORIGIN="http://testserver").status_code == 403


def test_refresh_needs_a_same_origin_request(client, owner):
    sign_in(client, owner.user)

    assert refresh(client, HTTP_ORIGIN="https://evil.example").status_code == 403
    assert client.post(REFRESH, HTTP_X_REQUESTED_WITH="dashboard").status_code == 403


def test_a_trusted_origin_may_refresh(client, owner, settings):
    settings.CSRF_TRUSTED_ORIGINS = ["http://localhost:28174"]
    sign_in(client, owner.user)

    assert refresh(client, HTTP_ORIGIN="http://localhost:28174").status_code == 200


def test_refresh_without_a_cookie_is_401(client):
    response = refresh(client)

    assert response.status_code == 401
    assert response.data["code"] == "session_ended"


def test_a_garbage_or_mini_app_cookie_is_401(client, owner):
    client.cookies[services.REFRESH_COOKIE] = "not-a-token"
    assert refresh(client).status_code == 401

    client.cookies[services.REFRESH_COOKIE] = str(RefreshToken.for_user(owner.user))
    response = refresh(client)
    assert response.status_code == 401
    assert response.cookies[services.REFRESH_COOKIE].value == ""  # cleared


def test_reusing_a_replaced_token_ends_the_session(client, owner):
    stolen = sign_in(client, owner.user)
    newest = refresh(client).cookies[services.REFRESH_COOKIE].value
    DeviceSession.objects.filter(pk=stolen.session.pk).update(
        rotated_at=timezone.now() - services.REUSE_GRACE - timedelta(seconds=1)
    )

    client.cookies[services.REFRESH_COOKIE] = stolen.refresh
    assert refresh(client).status_code == 401

    session = DeviceSession.objects.get(pk=stolen.session.pk)
    assert session.revoked_at is not None
    assert is_blacklisted(newest)
    client.cookies[services.REFRESH_COOKIE] = newest
    assert refresh(client).status_code == 401  # the rightful holder must sign in again too


def test_two_tabs_refreshing_at_once_both_succeed(client, owner):
    first = sign_in(client, owner.user)
    rotated = refresh(client)
    assert rotated.status_code == 200

    client.cookies[services.REFRESH_COOKIE] = first.refresh  # the slower tab's request
    response = refresh(client)

    assert response.status_code == 200
    assert OwnerAccessToken(response.data["access"])["sid"] == first.session.pk
    assert services.REFRESH_COOKIE not in response.cookies  # keeps the newest cookie
    assert DeviceSession.objects.get(pk=first.session.pk).revoked_at is None


def test_a_revoked_session_cant_refresh(client, owner):
    issued = sign_in(client, owner.user)
    services.revoke_session(issued.session)

    assert refresh(client).status_code == 401
    assert is_blacklisted(issued.refresh)


def test_losing_dashboard_access_stops_refreshing(client, owner, company):
    sign_in(client, owner.user)
    owner.status = owner.Status.BLOCKED
    owner.save()

    assert refresh(client).status_code == 401


def test_logout_ends_the_session_and_clears_the_cookie(client, owner):
    issued = sign_in(client, owner.user)

    response = client.post(LOGOUT, **DASHBOARD)

    assert response.status_code == 204
    assert response.cookies[services.REFRESH_COOKIE].value == ""
    assert DeviceSession.objects.get(pk=issued.session.pk).revoked_at is not None
    assert is_blacklisted(issued.refresh)
    client.cookies[services.REFRESH_COOKIE] = issued.refresh
    assert refresh(client).status_code == 401


def test_logout_without_a_session_still_clears_the_cookie(client):
    response = client.post(LOGOUT, **DASHBOARD)

    assert response.status_code == 204


def test_logout_needs_the_dashboard_header(client, owner):
    issued = sign_in(client, owner.user)

    assert client.post(LOGOUT).status_code == 403
    assert DeviceSession.objects.get(pk=issued.session.pk).revoked_at is None


def test_log_out_everywhere_ends_every_session_and_token(client, owner):
    first = sign_in(client, owner.user)
    second = sign_in(client, owner.user)

    assert services.revoke_all(owner.user) == 2

    assert not DeviceSession.objects.filter(user=owner.user, revoked_at__isnull=True).exists()
    assert is_blacklisted(first.refresh) and is_blacklisted(second.refresh)
    assert not OutstandingToken.objects.filter(
        user=owner.user, blacklistedtoken__isnull=True
    ).exists()


def test_telegram_sign_in_gets_an_access_token_without_a_session(owner):
    access = OwnerAccessToken(services.issue_access(owner.user))

    assert "sid" not in access
    assert not DeviceSession.objects.exists()
    assert not OutstandingToken.objects.exists()
