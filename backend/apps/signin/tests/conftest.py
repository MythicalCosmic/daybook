"""Fixtures for the owner sign-in tests."""

import pytest
from django.core.cache import cache

LINKS = "/api/v1/owner/auth/login-links/"
DASHBOARD = {"HTTP_X_REQUESTED_WITH": "dashboard", "HTTP_ORIGIN": "http://testserver"}


@pytest.fixture(autouse=True)
def fresh_throttles():
    """Throttle counters live in the cache; every test starts from zero."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def bots(settings):
    """The employee bot only (no owner bot token), with usernames for deep links."""
    settings.EMPLOYEE_BOT_USERNAME = "daybook_test_bot"
    settings.OWNER_BOT_USERNAME = "owner_test_bot"
    settings.EMPLOYEE_BOT_TOKEN = "42:TEST"
    settings.OWNER_BOT_TOKEN = ""
    return settings


@pytest.fixture
def owner(company, member):
    return member(company, "Owner", user__telegram_id=7700001)


class Browser:
    """A desktop browser going through the login page."""

    def __init__(self, client):
        self.client = client
        self.link = None

    def start(self, **headers) -> dict:
        response = self.client.post(LINKS, **(DASHBOARD | headers))
        assert response.status_code == 201, response.content
        self.link = response.json()
        return self.link

    @property
    def code(self) -> str:
        return self.link["deep_link"].split("start=login_", 1)[1]

    def poll(self, token: str | None = None):
        return self.client.get(
            f"{LINKS}{self.link['id']}/",
            HTTP_X_LOGIN_POLL=self.link["poll_token"] if token is None else token,
        )

    def claim(self, token: str | None = None, **headers):
        return self.client.post(
            f"{LINKS}{self.link['id']}/claim/",
            HTTP_X_LOGIN_POLL=self.link["poll_token"] if token is None else token,
            **(DASHBOARD | headers),
        )


@pytest.fixture
def browser(client, bots):
    return Browser(client)
