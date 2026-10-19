import redis
from django.conf import settings
from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def health(request):
    checks = {"database": _check_database(), "redis": _check_redis()}
    healthy = all(result == "ok" for result in checks.values())
    return JsonResponse(
        {"status": "ok" if healthy else "error", "checks": checks},
        status=200 if healthy else 503,
    )


def _check_database() -> str:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        return "error"
    return "ok"


def _check_redis() -> str:
    try:
        with redis.Redis.from_url(settings.REDIS_URL, socket_timeout=2) as client:
            client.ping()
    except redis.RedisError:
        return "error"
    return "ok"
