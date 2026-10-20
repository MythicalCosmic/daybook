"""Bootstraps the backend's Django project so the bot can use its models and services."""

import os
import sys
from pathlib import Path

import django

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"


def setup_django() -> None:
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    django.setup()
