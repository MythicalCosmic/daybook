"""The sessions page: list, sign one browser out, log out everywhere (§4.3, §7.3)."""

import pytest
from django.test import RequestFactory
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from apps.signin import services
from apps.signin.models import DeviceSession
from apps.signin.tests.factories import DeviceSessionFactory
from apps.signin.tokens import OwnerAccessToken

pytestmark = pytest.mark.django_db

SESSIONS = "/api/v1/owner/auth/sessions/"
REFRESH = "/api/v1/owner/auth/refresh/"
DASHBOARD = {"HTTP_X_REQUESTED_WITH": "dashboard", "HTTP_ORIGIN": "http://testserver"}
CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/141.0 Safari/537.36"
IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) Version/18.6 Mobile Safari/604.1"


@pytest.fixture
def owner(company, member):
    return member(company, "Owner")


def signed_in(user, agent=CHROME, ip="213.230.86.14") -> tuple[APIClient, services.IssuedSession]:
    """A browser with its own cookie and access token."""
    request = RequestFactory().post("/", HTTP_USER_AGENT=agent, REMOTE_ADDR=ip)
    issued = services.issue_session(user, request)
    client = APIClient()
    client.cookies[services.REFRESH_COOKIE] = issued.refresh
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issued.access}")
    return client, issued


def test_lists_active_sessions_with_this_browser_first(owner):
    laptop, issued = signed_in(owner.user)
    signed_in(owner.user, IPHONE, "84.54.71.203")
    DeviceSessionFactory(user=owner.user, revoked_at="2026-10-01T10:00:00Z")
    DeviceSessionFactory()  # someone else's

    response = laptop.get(SESSIONS)

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    assert rows[0]["id"] == issued.session.pk and rows[0]["current"] is True
    assert rows[0]["device"] == {
        "label": "Chrome · Windows",
        "browser": "Chrome",
        "system": "Windows",
        "kind": "desktop",
    }
    assert rows[0]["ip"] == "213.230.x.x"
    assert rows[1]["device"]["kind"] == "phone" and rows[1]["device"]["system"] == "iOS"
    assert rows[1]["current"] is False


def test_signing_one_other_browser_out(owner):
    laptop, _ = signed_in(owner.user)
    phone, phone_session = signed_in(owner.user, IPHONE)

    response = laptop.post(f"{SESSIONS}{phone_session.session.pk}/revoke/")

    assert response.status_code == 200
    assert response.json() == {"revoked": 1, "signed_out": False}
    assert "owner_refresh" not in response.cookies
    assert DeviceSession.objects.get(pk=phone_session.session.pk).revoked_at is not None
    # The phone's refresh now fails; the laptop's still works.
    assert phone.post(REFRESH, **DASHBOARD).status_code == 401
    assert laptop.post(REFRESH, **DASHBOARD).status_code == 200


def test_signing_this_browser_out_clears_its_cookie(owner):
    laptop, issued = signed_in(owner.user)

    response = laptop.post(f"{SESSIONS}{issued.session.pk}/revoke/")

    assert response.json() == {"revoked": 1, "signed_out": True}
    assert response.cookies["owner_refresh"].value == ""


def test_someone_elses_session_is_not_found(owner, company, member):
    laptop, _ = signed_in(owner.user)
    other = DeviceSessionFactory()

    assert laptop.post(f"{SESSIONS}{other.pk}/revoke/").status_code == 404
    assert DeviceSession.objects.get(pk=other.pk).revoked_at is None


def test_log_out_everywhere_blacklists_every_outstanding_token(owner):
    laptop, _ = signed_in(owner.user)
    phone, _ = signed_in(owner.user, IPHONE)

    response = laptop.post(f"{SESSIONS}revoke-all/", {}, format="json")

    assert response.json() == {"revoked": 2, "signed_out": True}
    assert response.cookies["owner_refresh"].value == ""
    outstanding = OutstandingToken.objects.filter(user=owner.user)
    assert outstanding.count() == 2
    assert BlacklistedToken.objects.filter(token__in=outstanding).count() == 2
    assert laptop.post(REFRESH, **DASHBOARD).status_code == 401
    assert phone.post(REFRESH, **DASHBOARD).status_code == 401


def test_log_out_every_other_device_keeps_this_one(owner):
    laptop, issued = signed_in(owner.user)
    phone, _ = signed_in(owner.user, IPHONE)
    tablet, _ = signed_in(owner.user, "Mozilla/5.0 (iPad; CPU OS 18_6) Version/18.6 Safari")

    response = laptop.post(f"{SESSIONS}revoke-all/", {"keep_current": True}, format="json")

    assert response.json() == {"revoked": 2, "signed_out": False}
    assert list(DeviceSession.objects.filter(revoked_at__isnull=True)) == [issued.session]
    assert phone.post(REFRESH, **DASHBOARD).status_code == 401
    assert tablet.post(REFRESH, **DASHBOARD).status_code == 401
    assert laptop.post(REFRESH, **DASHBOARD).status_code == 200


def test_inside_telegram_keep_current_still_logs_out_everywhere(owner):
    # A Telegram token names no session, so there is nothing to keep.
    signed_in(owner.user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {OwnerAccessToken.for_user(owner.user)}")

    response = client.post(f"{SESSIONS}revoke-all/", {"keep_current": True}, format="json")

    assert response.json()["signed_out"] is True
    assert not DeviceSession.objects.filter(revoked_at__isnull=True).exists()
    assert client.get(SESSIONS).json() == []


def test_sessions_need_an_owner_token(owner, api_as, client):
    assert client.get(SESSIONS).status_code == 401
    assert api_as(owner).get(SESSIONS).status_code == 401
