"""Rate limits behind carrier-grade NAT (apps.core.throttles): per person once we know who it is,
per address only a ceiling that a whole shift on one mobile operator's address never reaches."""

import pytest
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory
from rest_framework.settings import api_settings
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from apps.accounts.tests.telegram import BOT_TOKEN, signed_init_data
from apps.core.throttles import AddressRateThrottle
from apps.signin import services as signin
from apps.signin.services import REFRESH_COOKIE
from apps.tasks.api import ParseThrottle
from config.settings.base import rate_overrides

pytestmark = pytest.mark.django_db

APP_SIGN_IN = "/api/v1/auth/telegram/"
DASH_SIGN_IN = "/api/v1/owner/auth/telegram/"
REFRESH = "/api/v1/owner/auth/refresh/"
DASHBOARD = {"HTTP_X_REQUESTED_WITH": "dashboard", "HTTP_ORIGIN": "http://testserver"}
# Caddy's address, and the one public address a mobile operator gives a whole shift.
CADDY = "172.18.0.4"
CARRIER = "213.230.80.1"


@pytest.fixture(autouse=True)
def fresh_throttles(settings):
    settings.EMPLOYEE_BOT_TOKEN = BOT_TOKEN
    settings.OWNER_BOT_TOKEN = ""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def rate(monkeypatch):
    """Set one scope's rate for a test (DRF reads the rates when it counts)."""

    def set_rate(scope: str, value: str) -> None:
        monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, scope, value)

    return set_rate


def behind_carrier(client: APIClient, path: str, data: dict, address: str = CARRIER, **extra):
    """A request as Caddy forwards it: from Caddy, with the client's address as the last hop."""
    return client.post(
        path, data, format="json", REMOTE_ADDR=CADDY, HTTP_X_FORWARDED_FOR=address, **extra
    )


def test_a_whole_shift_behind_one_address_signs_in_to_the_mini_app():
    client = APIClient()
    statuses = [
        behind_carrier(
            client, APP_SIGN_IN, {"init_data": signed_init_data(user_id=8_000_000 + n)}
        ).status_code
        for n in range(300)
    ]

    assert statuses == [200] * 300


def test_one_person_is_limited_whatever_address_they_come_from(rate):
    rate("telegram_auth", "5/min")
    client = APIClient()
    sign_in = {"init_data": signed_init_data(user_id=8_100_001)}

    for n in range(5):
        assert behind_carrier(client, APP_SIGN_IN, sign_in, f"84.54.70.{n}").status_code == 200
    refused = behind_carrier(client, APP_SIGN_IN, sign_in, "84.54.70.99")
    someone_else = behind_carrier(
        client, APP_SIGN_IN, {"init_data": signed_init_data(user_id=8_100_002)}, "84.54.70.99"
    )

    assert refused.status_code == 429
    assert int(refused["Retry-After"]) > 0
    assert someone_else.status_code == 200


def test_the_address_ceiling_still_stops_a_flood(rate):
    rate("telegram_auth_address", "5/min")
    client = APIClient()

    for _ in range(5):
        assert behind_carrier(client, APP_SIGN_IN, {"init_data": "forged"}).status_code == 401
    flooded = behind_carrier(client, APP_SIGN_IN, {"init_data": "forged"})
    # A first hop the client wrote itself changes nothing: Caddy's last hop is what counts.
    spoofed = behind_carrier(client, APP_SIGN_IN, {"init_data": "forged"}, f"10.9.9.9, {CARRIER}")
    elsewhere = behind_carrier(client, APP_SIGN_IN, {"init_data": "forged"}, "84.54.70.2")

    assert flooded.status_code == 429
    assert spoofed.status_code == 429
    assert elsewhere.status_code == 401


def test_the_address_ceiling_counts_every_request_of_a_burst_once(rate):
    """A fixed window counted with one increment: no lost or doubled counts."""
    rate("telegram_auth_address", "50/min")
    view = APIView()
    view.address_throttle_scope = "telegram_auth_address"
    request = RequestFactory().post(APP_SIGN_IN, REMOTE_ADDR=CADDY, HTTP_X_FORWARDED_FOR=CARRIER)

    allowed = [AddressRateThrottle().allow_request(request, view) for _ in range(60)]

    assert allowed == [True] * 50 + [False] * 10


def test_managers_behind_one_address_open_the_dashboard_in_telegram(company, member):
    managers = [member(company, "Manager", user__telegram_id=8_200_000 + n) for n in range(40)]
    client = APIClient()

    statuses = [
        behind_carrier(
            client, DASH_SIGN_IN, {"init_data": signed_init_data(m.user.telegram_id)}
        ).status_code
        for m in managers
    ]

    assert statuses == [200] * 40


def test_the_dashboard_in_telegram_is_limited_per_person(company, member, rate):
    rate("owner_telegram", "3/min")
    boss = member(company, "Manager", user__telegram_id=8_300_001)
    other = member(company, "Manager", user__telegram_id=8_300_002)
    client = APIClient()

    for _ in range(3):
        sign_in = {"init_data": signed_init_data(boss.user.telegram_id)}
        assert behind_carrier(client, DASH_SIGN_IN, sign_in).status_code == 200
    refused = behind_carrier(
        client, DASH_SIGN_IN, {"init_data": signed_init_data(boss.user.telegram_id)}
    )
    other_in = behind_carrier(
        client, DASH_SIGN_IN, {"init_data": signed_init_data(other.user.telegram_id)}
    )

    assert refused.status_code == 429
    assert other_in.status_code == 200


def _desktop(company, member, telegram_id) -> APIClient:
    """A browser signed in to the dashboard: its refresh cookie names its session."""
    person = member(company, "Manager", user__telegram_id=telegram_id)
    request = RequestFactory().post(REFRESH, REMOTE_ADDR=CADDY, HTTP_X_FORWARDED_FOR=CARRIER)
    issued = signin.issue_session(person.user, request)
    client = APIClient()
    client.cookies[REFRESH_COOKIE] = issued.refresh
    return client


def test_dashboard_refreshes_count_per_session_not_per_office(company, member, rate):
    rate("owner_refresh", "4/min")
    tabs = _desktop(company, member, 8_400_001)
    colleague = _desktop(company, member, 8_400_002)

    for _ in range(4):
        assert behind_carrier(tabs, REFRESH, {}, **DASHBOARD).status_code == 200
    refused = behind_carrier(tabs, REFRESH, {}, **DASHBOARD)
    next_desk = behind_carrier(colleague, REFRESH, {}, **DASHBOARD)

    assert refused.status_code == 429
    assert next_desk.status_code == 200


def test_rates_suit_a_shift_behind_one_address():
    """The shipped numbers: hundreds of people per address, per person far above human use."""

    def per_minute(scope: str) -> int:
        count, period = api_settings.DEFAULT_THROTTLE_RATES[scope].split("/")
        assert period == "min"
        return int(count)

    for scope in ("telegram_auth_address", "owner_telegram_address", "owner_auth_address"):
        assert per_minute(scope) >= 1000
    assert per_minute("login_link") >= 300
    for scope in ("telegram_auth", "owner_telegram", "owner_refresh"):
        assert per_minute(scope) >= 30
    assert ParseThrottle().rate == api_settings.DEFAULT_THROTTLE_RATES["task_parse"]
    assert per_minute("task_parse") >= 240


def test_rates_can_be_overridden_from_the_environment():
    assert rate_overrides("") == {}
    assert rate_overrides(" telegram_auth_address = 2000/min , login_link=600/minute ,") == {
        "telegram_auth_address": "2000/min",
        "login_link": "600/minute",
    }
    with pytest.raises(ImproperlyConfigured):
        rate_overrides("telegram_auth=lots")
    with pytest.raises(ImproperlyConfigured):
        rate_overrides("=60/min")
