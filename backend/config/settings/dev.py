from .base import *

SECRET_KEY = env("DJANGO_SECRET_KEY", default="django-insecure-dev-only")
DEBUG = env.bool("DJANGO_DEBUG", default=True)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
