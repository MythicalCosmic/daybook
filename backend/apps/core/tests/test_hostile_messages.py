"""People type `<`, `>` and `&` into names, titles, comments and reasons ("Harorat < 8 °C").
Everything the backend sends is HTML, so each of them must reach Telegram escaped, or Telegram
refuses the whole message. The whole demo gets such a text at the end of every name, title,
note and reason, then every scheduled job runs through a working Monday; the `sent_messages`
fixture fails the test on any message Telegram would refuse
(apps.notifications.tests.telegram_checks)."""

from datetime import datetime, time
from importlib import import_module
from io import StringIO
from zoneinfo import ZoneInfo

import pytest
from django.apps import apps
from django.conf import settings as django_settings
from django.core.management import call_command
from django.db import models
from django.db.models.functions import Concat, Left
from django.utils import timezone

from apps.companies.models import Company
from apps.core.demo_time import moment
from apps.core.management.commands import seed_demo

pytestmark = pytest.mark.django_db

HOSTILE = " <b>&amp; < 8 °C & <Ali>"
# Free text people type, in every app. Codes, slugs, keys and phone numbers stay as they are.
TYPED = {
    "name",
    "title",
    "first_name",
    "last_name",
    "description",
    "reason",
    "note",
    "comment",
    "text",
    "proof_text",
    "blocker_note",
    "extension_note",
    "returned_reason",
    "decision_note",
    "label",
}
# Already Telegram HTML, kept to its tags when saved (announcements' telegram_html, the
# knowledge base's sanitize), and the AI app another package builds.
STORED_AS_HTML = {("announcements", "announcement", "text")}
SKIP_APPS = {"ai", "audit"}
# Jobs that reach the network (exchange rates, Telegram photos) or only tidy files and tokens.
SKIP_JOBS = {
    "accounts-refresh-telegram-photos",
    "finance-fetch-exchange-rates",
    "exports-prune",
    "signin-flush-expired-tokens",
    "tasks-backfill-proof-thumbs",
}
DAY = (time(7, 55), time(8, 35), time(9, 5), time(13, 5), time(18, 5), time(20, 35), time(22, 5))


def make_hostile() -> int:
    """Append HOSTILE to every typed text of every app's rows; returns how many columns."""
    columns = 0
    for model in apps.get_models():
        label = model._meta.app_label
        if not model.__module__.startswith("apps.") or label in SKIP_APPS:
            continue
        fields = [
            field
            for field in model._meta.concrete_fields
            if isinstance(field, models.CharField | models.TextField)
            and field.name in TYPED
            and not field.choices
            and (label, model._meta.model_name, field.name) not in STORED_AS_HTML
        ]
        if not fields:
            continue
        changes = {}
        for field in fields:
            value = Concat(models.F(field.name), models.Value(HOSTILE))
            if field.max_length:
                value = Left(value, field.max_length)
            changes[field.name] = value
        model._base_manager.update(**changes)
        columns += len(fields)
    return columns


def jobs() -> list:
    found = []
    for key, entry in django_settings.CELERY_BEAT_SCHEDULE.items():
        if key in SKIP_JOBS:
            continue
        path, _dot, name = entry["task"].rpartition(".")
        found.append((key, getattr(import_module(path), name), entry.get("args", ())))
    return found


def test_every_scheduled_message_escapes_what_people_typed(settings, sent_messages):
    settings.DEBUG = True
    call_command("seed_demo", stdout=StringIO())
    settings.DEBUG = False
    assert make_hostile() > 40

    pharmacy = Company.objects.get(slug=seed_demo.SLUG)
    tz = ZoneInfo(pharmacy.timezone)
    today = timezone.localtime(timezone.now(), tz).date()
    for at in DAY:
        with moment(datetime.combine(today, at, tzinfo=tz)):
            for _key, job, args in jobs():
                job(*args)

    # Digests, weekly reports, shift nudges, event reminders, inbox warnings, group posts…
    # (63 on 2026-11-02), every one checked by `sent_messages` when the test ends.
    texts = [message["text"] for message in sent_messages]
    assert len(texts) > 30
    assert sum("&lt;Ali&gt;" in text for text in texts) > 20  # the typed text, escaped
