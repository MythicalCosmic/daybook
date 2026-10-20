"""Dev login exists only with DEBUG and DASHBOARD_DEV_LOGIN (docs/PLAN-OWNER.md §7.3)."""

import pytest

from apps.signin import services
from apps.signin.models import DeviceSession
from apps.signin.tokens import OwnerAccessToken

pytestmark = pytest.mark.django_db

DEV_LOGIN = "/api/v1/owner/auth/dev-login/"
DASHBOARD = {"HTTP_X_REQUESTED_WITH": "dashboard", "HTTP_ORIGIN": "http://testserver"}


@pytest.fixture
def enabled(settings):
    settings.DEBUG = True
    settings.DASHBOARD_DEV_LOGIN = True


def dev_login(client, telegram_id, **headers):
    return client.post(
        DEV_LOGIN, {"telegram_id": telegram_id}, content_type="application/json", **headers
    )


def test_dev_login_is_off_by_default(client, company, member, settings):
    owner = member(company, "Owner")
    assert settings.DASHBOARD_DEV_LOGIN is False

    assert dev_login(client, owner.user.telegram_id, **DASHBOARD).status_code == 404


def test_dev_login_needs_debug_too(client, company, member, settings):
    owner = member(company, "Owner")
    settings.DASHBOARD_DEV_LOGIN = True
    settings.DEBUG = False

    assert dev_login(client, owner.user.telegram_id, **DASHBOARD).status_code == 404


def test_dev_login_needs_the_flag_too(client, company, member, settings):
    owner = member(company, "Owner")
    settings.DEBUG = True
    settings.DASHBOARD_DEV_LOGIN = False

    assert dev_login(client, owner.user.telegram_id, **DASHBOARD).status_code == 404


@pytest.mark.usefixtures("enabled")
def test_dev_login_starts_a_desktop_session(client, company, member):
    owner = member(company, "Owner")

    response = dev_login(client, owner.user.telegram_id, **DASHBOARD)

    assert response.status_code == 200
    session = DeviceSession.objects.get(user=owner.user)
    assert OwnerAccessToken(response.data["access"])["sid"] == session.pk
    assert response.cookies[services.REFRESH_COOKIE]["httponly"]
    assert not response.cookies[services.REFRESH_COOKIE]["secure"]  # DEBUG: plain http works


@pytest.mark.usefixtures("enabled")
def test_dev_login_refuses_people_without_dashboard_access(client, company, member):
    employee = member(company, "Employee")

    assert dev_login(client, employee.user.telegram_id, **DASHBOARD).status_code == 403
    assert dev_login(client, 999_999_999, **DASHBOARD).status_code == 403
    assert not DeviceSession.objects.exists()


@pytest.mark.usefixtures("enabled")
def test_dev_login_comes_from_the_dashboard_only(client, company, member):
    owner = member(company, "Owner")

    assert dev_login(client, owner.user.telegram_id).status_code == 403
