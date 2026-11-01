import json

import pytest
import redis
from django.conf import settings

pytestmark = pytest.mark.django_db


def test_health_reports_ok(client):
    response = client.get("/health/")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": settings.APP_VERSION,
        "checks": {"database": "ok", "redis": "ok"},
    }


def test_one_release_number_everywhere():
    """pyproject.toml holds the release; the API schema and both apps' package.json say the same."""
    assert settings.SPECTACULAR_SETTINGS["VERSION"] == settings.APP_VERSION
    for app in ("miniapp", "dashboard"):
        package = json.loads((settings.ROOT_DIR / app / "package.json").read_text())
        assert package["version"] == settings.APP_VERSION, app


def test_health_reports_redis_outage(client, monkeypatch):
    def broken_ping(self):
        raise redis.ConnectionError("down")

    monkeypatch.setattr(redis.Redis, "ping", broken_ping)

    response = client.get("/health/")

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "version": settings.APP_VERSION,
        "checks": {"database": "ok", "redis": "error"},
    }
