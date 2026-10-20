from .base import *

SECRET_KEY = "django-insecure-test-only-key-not-for-production"
DEBUG = False
ALLOWED_HOSTS = ["testserver"]

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Several test runs at once (one per engineer or agent) each get their own database:
# PYTEST_DB=finance uv run pytest backend/apps/finance
PYTEST_DB = env("PYTEST_DB", default="")
if PYTEST_DB:
    DATABASES["default"]["TEST"] = {"NAME": f"test_trello_{PYTEST_DB}"}

# Per-process cache, so throttling counters never leak between runs. Keys carry the run's
# name too, like everything apps.core.redis writes, so parallel runs never share keys.
_key_prefix = f"t:{PYTEST_DB or 'default'}:"
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "KEY_PREFIX": _key_prefix,
    }
}
REDIS_KEY_PREFIX = _key_prefix

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Tests never reach Telegram, whatever .env says.
EMPLOYEE_BOT_TOKEN = ""
OWNER_BOT_TOKEN = ""
EMPLOYEE_BOT_USERNAME = ""
OWNER_BOT_USERNAME = ""
EMPLOYEE_MINIAPP_URL = ""
PLATFORM_ADMIN_TG_IDS = []
BOT_FSM_REDIS_URL = ""

# ...nor Anthropic: AI tests use the scripted fake client (apps/ai/fakes.py).
ANTHROPIC_API_KEY = ""
AI_FAKE = False

DASHBOARD_DEV_LOGIN = False
DASHBOARD_URL = ""
SCHEMA_AUDIENCE = ""
COMPANY_SIGNUP = "code"

# Fixed keys, never used outside tests.
FIELD_ENCRYPTION_KEY = "o9Dz7N2qHkqmC1bG4WbC0yQ8yC8kq2ZqN8bq0bJXwUo="
FIELD_HASH_KEY = "test-only-field-hash-key-not-for-production"
