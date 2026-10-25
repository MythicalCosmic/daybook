import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import environ
from celery.schedules import crontab
from django.core.exceptions import ImproperlyConfigured

from apps.core.collect import collect
from apps.core.schema import enum_name_overrides

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ROOT_DIR = BASE_DIR.parent

env = environ.Env()
environ.Env.read_env(ROOT_DIR / ".env")

CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    "unfold",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "corsheaders",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "drf_spectacular",
    "apps.core",
    "apps.accounts",
    "apps.companies",
    "apps.members",
    "apps.notifications",
    "apps.tasks",
    "apps.reminders",
    "apps.groups",
    "apps.audit",
    "apps.reports",
    "apps.timeoff",
    "apps.announcements",
    # Owner console, money, HR and AI (docs/PLAN-OWNER.md)
    "apps.console",
    "apps.inbox",
    "apps.exports",
    "apps.signin",
    "apps.finance",
    "apps.sales",
    "apps.inventory",
    "apps.attendance",
    "apps.hr",
    "apps.payroll",
    "apps.ai",
    "apps.insights",
    "apps.briefings",
    "apps.recognition",
    "apps.projects",
    "apps.lifecycle",
    "apps.knowledge",
    "apps.agenda",
    "apps.crm",
]

AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en"
LANGUAGES = [("uz", "O'zbekcha"), ("ru", "Русский"), ("en", "English")]
# Translations for the backend and the bots; `make messages` collects them.
LOCALE_PATHS = [BASE_DIR / "locale"]
# Display default only: data is stored in UTC and every company has its own timezone.
TIME_ZONE = "Asia/Tashkent"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# The built mini app (miniapp/dist), served at /app/ in production.
MINIAPP_DIST = Path(env("MINIAPP_DIST", default=str(ROOT_DIR / "miniapp" / "dist")))
# The built owner dashboard (dashboard/dist): assets at /dashboard/assets/, every other
# /dashboard/ path answers with its index.html (apps.core.spa).
DASHBOARD_DIST = Path(env("DASHBOARD_DIST", default=str(ROOT_DIR / "dashboard" / "dist")))
# Public address of the dashboard, for "Open dashboard" buttons in the bots.
DASHBOARD_URL = env("DASHBOARD_URL", default="")
# POST /api/v1/owner/auth/dev-login/ (only together with DEBUG).
DASHBOARD_DEV_LOGIN = env.bool("DASHBOARD_DEV_LOGIN", default=False)
MEDIA_URL = "media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", default=str(BASE_DIR / "media")))
# Receipts, documents, exports and PDFs: never served directly, only through signed links.
PRIVATE_MEDIA_ROOT = Path(env("PRIVATE_MEDIA_ROOT", default=str(BASE_DIR / "private_media")))

REDIS_URL = env("REDIS_URL")
# Added to every key apps.core.redis writes, so several runs can share one Redis.
REDIS_KEY_PREFIX = env("REDIS_KEY_PREFIX", default="")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

CELERY_BROKER_URL = env("CELERY_BROKER_URL")
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TASK_IGNORE_RESULT = True
CELERY_TIMEZONE = TIME_ZONE
# AI calls never block the default queue (the ai-worker service consumes "ai").
CELERY_TASK_ROUTES = {"apps.ai.tasks.*": {"queue": "ai"}}
CELERY_BEAT_SCHEDULE = {
    # Idempotent, so running often just picks up new templates and members sooner.
    "generate-daily-tasks": {
        "task": "apps.tasks.tasks.generate_daily_tasks",
        "schedule": crontab(minute="*/10"),
    },
    "send-due-reminders": {
        "task": "apps.reminders.tasks.send_due_reminders",
        "schedule": crontab(),  # every minute
    },
    # Each report goes out once a day, in the first run after the company's report time.
    "send-group-reports": {
        "task": "apps.groups.tasks.send_daily_reports",
        "schedule": crontab(minute="*/5"),
    },
    # Once per person per day, in the first run after the company's morning report time.
    "send-morning-digests": {
        "task": "apps.reports.tasks.send_morning_digests",
        "schedule": crontab(minute="*/5"),
    },
    # One reminder for unread announcements, then a summary for their authors.
    "follow-up-announcements": {
        "task": "apps.announcements.tasks.follow_up_announcements",
        "schedule": crontab(minute="*/15"),
    },
    # Monday mornings only; once per person per week.
    "send-weekly-reports": {
        "task": "apps.reports.tasks.send_weekly_reports",
        "schedule": crontab(minute="*/15", day_of_week="mon"),
    },
}
# Plus every app's own entries (apps/<app>/beat.py); a key used twice stops the settings.
CELERY_BEAT_SCHEDULE = collect("beat.py", "SCHEDULE", CELERY_BEAT_SCHEDULE)


def rate_overrides(value: str) -> dict[str, str]:
    """THROTTLE_RATES="telegram_auth=60/min,login_link=200/min" as {scope: rate}."""
    rates = {}
    for item in filter(None, (part.strip() for part in value.split(","))):
        scope, _, rate = (side.strip() for side in item.partition("="))
        if not scope or not re.fullmatch(r"\d+/[smhd][a-z]*", rate):
            raise ImproperlyConfigured(f"THROTTLE_RATES: write {item!r} as name=60/min.")
        rates[scope] = rate
    return rates


REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.accounts.authentication.LanguageJWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "apps.core.api.Pagination",
    "EXCEPTION_HANDLER": "apps.core.api.exception_handler",
    # Per person once we know who it is; per address only a ceiling against floods, sized for
    # hundreds of people behind one carrier-grade NAT address (apps.core.throttles). Override
    # any of them with THROTTLE_RATES="telegram_auth=60/min,login_link=200/min".
    "DEFAULT_THROTTLE_RATES": {
        # Mini app sign-in: per Telegram user (signature checked), and per address.
        "telegram_auth": "60/min",
        "telegram_auth_address": "1200/min",
        # The dashboard inside Telegram: per Telegram user, and per address.
        "owner_telegram": "60/min",
        "owner_telegram_address": "1200/min",
        # Dashboard refresh: per session (its token checked); refresh, logout and the dev
        # login together per address.
        "owner_refresh": "60/min",
        "owner_auth_address": "1200/min",
        # Desktop sign-in links: nobody is known yet, so per address; claims per link too.
        "login_link": "300/min",
        "login_poll": "60/min",
        "login_claim": "10/min",
        "login_claim_address": "300/min",
        # Per signed-in person.
        "task_parse": "300/min",
        "export_create": "10/min",
    }
    | rate_overrides(env("THROTTLE_RATES", default="")),
    # Caddy sits in front: throttles and stored IPs use the client's address, not Caddy's.
    # Caddy replaces any X-Forwarded-For a client sends, so the last hop is the client. Put a
    # CDN or another proxy in front and this must count it too (and Caddy must trust it).
    "NUM_PROXIES": env.int("NUM_PROXIES", default=1),
}

SIMPLE_JWT = {
    # The mini app gets access tokens only; owner refresh tokens rotate and are blacklisted.
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=1),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}
# Owner dashboard tokens (aud="dashboard", apps.signin).
OWNER_ACCESS_TOKEN_LIFETIME = timedelta(minutes=env.int("OWNER_ACCESS_TOKEN_MINUTES", default=15))
# How old the owner bot's Mini App launch data may be before sign-in is refused (seconds).
OWNER_INIT_DATA_MAX_AGE = env.int("OWNER_INIT_DATA_MAX_AGE", default=60 * 60)
# Who may create a company: "code" (a signup code from a platform admin), "open" or "off".
COMPANY_SIGNUP = env("COMPANY_SIGNUP", default="code")
if COMPANY_SIGNUP not in ("code", "open", "off"):
    raise ImproperlyConfigured("COMPANY_SIGNUP must be code, open or off.")
# Companies one person may own, unless they are a platform admin.
MAX_COMPANIES_PER_USER = env.int("MAX_COMPANIES_PER_USER", default=10)

# The mini app is served from its own origin.
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_URLS_REGEX = r"^/api/.*$"

# Which part of the API `manage.py spectacular` describes: "employee" (the mini app's types),
# "owner" (the dashboard's) or "" (everything, as /api/schema/ serves it).
SCHEMA_AUDIENCE = env("SCHEMA_AUDIENCE", default="")
SPECTACULAR_SETTINGS = {
    "TITLE": "911 Trello API",
    "DESCRIPTION": "API for the employee mini app and the owner dashboard.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    # Several models have a "status"/"kind"; name the enums so generated clients read well.
    # Apps add theirs in apps/<app>/schema_enums.py; a name used twice stops the settings.
    "ENUM_NAME_OVERRIDES": enum_name_overrides(
        {
            "MembershipStatusEnum": "apps.members.models.Membership.Status",
            "TaskStatusEnum": "apps.tasks.models.Task.Status",
            "TaskKindEnum": "apps.tasks.models.Task.Kind",
            "ActivityKindEnum": "apps.tasks.models.Activity.Kind",
            "WeekdayEnum": "apps.tasks.models.Weekday",
            "RepeatEnum": "apps.tasks.models.Repeat",
            "TaskMoveEnum": ["todo", "in_progress", "review", "returned", "done"],
            "TimeOffStatusEnum": "apps.timeoff.models.TimeOff.Status",
            # Currencies with their names, and the bare codes some write serializers accept.
            "CurrencyEnum": "apps.core.money.Currency",
            "CurrencyCodeEnum": ["UZS", "USD"],
        }
    ),
    # `make check` generates both schemas with --fail-on-warn: a component name used twice or
    # an enum named by a hash fails it. Give a generic serializer an app-prefixed
    # `Meta.ref_name` ("SalesReason") and name new enums here or in apps/<app>/schema_enums.py.
    "PREPROCESSING_HOOKS": ["apps.core.schema.split_by_audience"],
}

UNFOLD = {
    "SITE_TITLE": "911 Trello",
    "SITE_HEADER": "911 Trello",
}

# Telegram
EMPLOYEE_BOT_TOKEN = env("EMPLOYEE_BOT_TOKEN", default="")
EMPLOYEE_BOT_USERNAME = env("EMPLOYEE_BOT_USERNAME", default="")
OWNER_BOT_TOKEN = env("OWNER_BOT_TOKEN", default="")
OWNER_BOT_USERNAME = env("OWNER_BOT_USERNAME", default="")
EMPLOYEE_MINIAPP_URL = env("EMPLOYEE_MINIAPP_URL", default="")
# How old mini app launch data may be before login is refused (seconds).
MINIAPP_INIT_DATA_MAX_AGE = env.int("MINIAPP_INIT_DATA_MAX_AGE", default=24 * 60 * 60)
BOT_FSM_REDIS_URL = env("BOT_FSM_REDIS_URL", default="")
# Log outgoing bot messages instead of sending them (local runs with a fake token).
TELEGRAM_DRY_RUN = env.bool("TELEGRAM_DRY_RUN", default=False)
# Threads each bot runs its Django calls on (apps.core.bot_runtime): how many people's updates
# reach the database at once. Each keeps a database connection.
BOT_DB_THREADS = env.int("BOT_DB_THREADS", default=16)
PLATFORM_ADMIN_TG_IDS = env.list("PLATFORM_ADMIN_TG_IDS", cast=int, default=[])

# Field encryption (apps.core.crypto): Fernet keys, comma-separated, newest first, for
# rotation; and the HMAC key for lookup digests of encrypted values.
FIELD_ENCRYPTION_KEY = env("FIELD_ENCRYPTION_KEY", default="")
FIELD_HASH_KEY = env("FIELD_HASH_KEY", default="")

# AI (apps.ai). Without a key every AI surface is hidden and the rest works as usual.
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")
# Canned, deterministic AI answers without a key (development and demos).
AI_FAKE = env.bool("AI_FAKE", default=False)
AI_MODEL_CHAT = env("AI_MODEL_CHAT", default="claude-sonnet-5-5")
AI_MODEL_DEEP = env("AI_MODEL_DEEP", default="claude-opus-5-5")
AI_MODEL_FAST = env("AI_MODEL_FAST", default="claude-haiku-5-5")
# What all tenants together may spend in a month; one key pays for everyone.
AI_GLOBAL_MONTHLY_CAP_USD = Decimal(env("AI_GLOBAL_MONTHLY_CAP_USD", default="200"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "default"},
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
