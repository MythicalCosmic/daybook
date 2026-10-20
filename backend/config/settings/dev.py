from .base import *

SECRET_KEY = env("DJANGO_SECRET_KEY", default="django-insecure-dev-only-key-not-for-production")
DEBUG = env.bool("DJANGO_DEBUG", default=True)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# Run Celery tasks inline when no worker is running.
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
