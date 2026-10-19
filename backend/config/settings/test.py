from .base import *

SECRET_KEY = "django-insecure-test-only-key-not-for-production"
DEBUG = False
ALLOWED_HOSTS = ["testserver"]

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Per-process cache, so throttling counters never leak between runs.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Tests never reach Telegram, whatever .env says.
EMPLOYEE_BOT_TOKEN = ""
OWNER_BOT_TOKEN = ""
EMPLOYEE_BOT_USERNAME = ""
EMPLOYEE_MINIAPP_URL = ""
PLATFORM_ADMIN_TG_IDS = []
BOT_FSM_REDIS_URL = ""
