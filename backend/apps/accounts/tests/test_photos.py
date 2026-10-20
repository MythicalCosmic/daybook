"""Telegram profile photos cached as avatars (`accounts.tasks.refresh_telegram_photos`)."""

import io
from datetime import timedelta

import pytest
from django.utils import timezone
from PIL import Image

from apps.accounts import photos, tasks
from apps.accounts.models import User
from apps.members.models import Membership

pytestmark = pytest.mark.django_db


def picture(size=(640, 640)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (122, 138, 94)).save(out, "PNG")
    return out.getvalue()


@pytest.fixture
def telegram(settings):
    settings.TELEGRAM_DRY_RUN = False
    settings.EMPLOYEE_BOT_TOKEN = "42:TEST"
    return settings


@pytest.fixture
def downloads(monkeypatch):
    """What Telegram "returns" per telegram id; ids missing here act like a refusal."""
    answers: dict[int, bytes] = {}
    asked: list[list[int]] = []

    async def fake(token, telegram_ids):
        asked.append(list(telegram_ids))
        return {tid: answers[tid] for tid in telegram_ids if tid in answers}

    monkeypatch.setattr(photos, "download_all", fake)
    return answers, asked


def test_only_working_people_who_are_due_are_refreshed(company, member):
    working = member(company, "Employee", user__telegram_id=9001)
    member(company, "Employee", status=Membership.Status.LEFT, user__telegram_id=9002)
    fresh = member(company, "Employee", user__telegram_id=9003)
    User.objects.filter(pk=fresh.user_id).update(photo_checked_at=timezone.now())
    stale = member(company, "Employee", user__telegram_id=9004)
    User.objects.filter(pk=stale.user_id).update(
        photo_checked_at=timezone.now() - timedelta(days=8)
    )

    due = {user.telegram_id for user in photos.due(timezone.now())}

    assert due == {working.user.telegram_id, stale.user.telegram_id}


def test_photos_are_reencoded_small_and_old_ones_replaced(company, member, telegram, downloads):
    person = member(company, "Employee", user__telegram_id=9101)
    answers, _asked = downloads
    answers[9101] = picture()

    assert photos.refresh() == 1

    user = User.objects.get(pk=person.user_id)
    assert user.photo.name.startswith("avatars/") and user.photo.name.endswith(".jpg")
    with Image.open(user.photo.path) as image:
        assert max(image.size) == photos.AVATAR_SIDE
    assert user.photo_checked_at is not None


def test_no_photo_on_telegram_clears_the_avatar(company, member, telegram, downloads):
    person = member(company, "Employee", user__telegram_id=9201)
    answers, _asked = downloads
    answers[9201] = picture()
    photos.refresh()
    User.objects.filter(pk=person.user_id).update(photo_checked_at=None)
    answers[9201] = photos.NO_PHOTO

    photos.refresh()

    assert not User.objects.get(pk=person.user_id).photo


def test_refusals_keep_the_old_avatar_and_wait_a_week(company, member, telegram, downloads):
    person = member(company, "Employee", user__telegram_id=9301)
    answers, _asked = downloads
    answers[9301] = picture()
    photos.refresh()
    before = User.objects.get(pk=person.user_id)
    User.objects.filter(pk=person.user_id).update(
        photo_checked_at=timezone.now() - timedelta(days=8)
    )
    del answers[9301]  # Telegram refuses this time

    photos.refresh()

    user = User.objects.get(pk=person.user_id)
    assert user.photo.name == before.photo.name  # the old avatar stays
    assert user.photo_checked_at > timezone.now() - timedelta(minutes=1)
    assert person.user_id not in {u.pk for u in photos.due(timezone.now())}
    assert person.user_id in {u.pk for u in photos.due(timezone.now() + timedelta(days=7))}


def test_people_never_checked_come_first(company, member, monkeypatch):
    monkeypatch.setattr(photos, "BATCH", 2)
    stale = []
    for index in range(3):
        person = member(company, "Employee", user__telegram_id=9310 + index)
        User.objects.filter(pk=person.user_id).update(
            photo_checked_at=timezone.now() - timedelta(days=30 - index)
        )
        stale.append(person)
    newcomer = member(company, "Employee", user__telegram_id=9320)

    due = [user.pk for user in photos.due(timezone.now())]

    assert due == [newcomer.user_id, stale[0].user_id]


def test_something_that_is_not_a_picture_is_ignored(company, member, telegram, downloads):
    person = member(company, "Employee", user__telegram_id=9401)
    answers, _asked = downloads
    answers[9401] = b"<html>not a picture</html>"

    photos.refresh()

    user = User.objects.get(pk=person.user_id)
    assert not user.photo and user.photo_checked_at is not None


def test_dry_run_and_missing_tokens_do_nothing(company, member, settings, downloads):
    member(company, "Employee", user__telegram_id=9501)
    _answers, asked = downloads
    settings.TELEGRAM_DRY_RUN = True
    assert tasks.refresh_telegram_photos() == 0

    settings.TELEGRAM_DRY_RUN = False
    settings.EMPLOYEE_BOT_TOKEN = ""
    settings.OWNER_BOT_TOKEN = ""
    assert photos.refresh() == 0
    assert asked == []


def test_the_weekly_schedule_runs_the_task():
    from apps.accounts.beat import SCHEDULE

    entry = SCHEDULE["accounts-refresh-telegram-photos"]
    assert entry["task"] == "apps.accounts.tasks.refresh_telegram_photos"
    assert entry["schedule"].day_of_week == {0}  # Sunday
