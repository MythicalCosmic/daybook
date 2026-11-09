from .base import *

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")

# WhiteNoise serves the collected static files (admin, Swagger UI), the built mini app
# at /app/ and the dashboard's assets at /dashboard/assets/, right after SecurityMiddleware.
MIDDLEWARE.insert(
    MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,
    "apps.core.spa.SpaWhiteNoiseMiddleware",
)
WHITENOISE_INDEX_FILE = True

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# TLS terminates at the reverse proxy, which must set (and strip client-sent) X-Forwarded-Proto.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=False)
# Face ID terminals may only speak plain HTTP and can't follow a redirect with their event.
SECURE_REDIRECT_EXEMPT = [r"^api/v1/devices/"]
SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default=0)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
