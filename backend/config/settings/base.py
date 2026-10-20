from datetime import timedelta
from pathlib import Path

import environ
from celery.schedules import crontab

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
MEDIA_URL = "media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", default=str(BASE_DIR / "media")))

REDIS_URL = env("REDIS_URL")

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
}

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.accounts.authentication.LanguageJWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "apps.core.api.Pagination",
    "EXCEPTION_HANDLER": "apps.core.api.exception_handler",
    "DEFAULT_THROTTLE_RATES": {"telegram_auth": "30/min"},
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=1),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# The mini app is served from its own origin.
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_URLS_REGEX = r"^/api/.*$"

SPECTACULAR_SETTINGS = {
    "TITLE": "911 Trello API",
    "DESCRIPTION": "API for the employee mini app.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    # Several models have a "status"/"kind"; name the enums so generated clients read well.
    "ENUM_NAME_OVERRIDES": {
        "MembershipStatusEnum": "apps.members.models.Membership.Status",
        "TaskStatusEnum": "apps.tasks.models.Task.Status",
        "TaskKindEnum": "apps.tasks.models.Task.Kind",
        "ActivityKindEnum": "apps.tasks.models.Activity.Kind",
        "WeekdayEnum": "apps.tasks.models.Weekday",
    },
}

UNFOLD = {
    "SITE_TITLE": "911 Trello",
    "SITE_HEADER": "911 Trello",
}

# Telegram
EMPLOYEE_BOT_TOKEN = env("EMPLOYEE_BOT_TOKEN", default="")
EMPLOYEE_BOT_USERNAME = env("EMPLOYEE_BOT_USERNAME", default="")
OWNER_BOT_TOKEN = env("OWNER_BOT_TOKEN", default="")
EMPLOYEE_MINIAPP_URL = env("EMPLOYEE_MINIAPP_URL", default="")
# How old mini app launch data may be before login is refused (seconds).
MINIAPP_INIT_DATA_MAX_AGE = env.int("MINIAPP_INIT_DATA_MAX_AGE", default=24 * 60 * 60)
BOT_FSM_REDIS_URL = env("BOT_FSM_REDIS_URL", default="")
# Log outgoing bot messages instead of sending them (local runs with a fake token).
TELEGRAM_DRY_RUN = env.bool("TELEGRAM_DRY_RUN", default=False)
PLATFORM_ADMIN_TG_IDS = env.list("PLATFORM_ADMIN_TG_IDS", cast=int, default=[])

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
