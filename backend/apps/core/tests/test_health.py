import pytest
import redis

pytestmark = pytest.mark.django_db


def test_health_reports_ok(client):
    response = client.get("/health/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


def test_health_reports_redis_outage(client, monkeypatch):
    def broken_ping(self):
        raise redis.ConnectionError("down")

    monkeypatch.setattr(redis.Redis, "ping", broken_ping)

    response = client.get("/health/")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "checks": {"database": "ok", "redis": "error"}}
