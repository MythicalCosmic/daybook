"""Retention (docs/KOZ.md §6.7, §8): minute stats and alerts after `stats_keep_days`, alert photos
after `photos_keep_days`, clips with their video and poster after `clips_keep_days`. Files go
from the storage too."""

from datetime import timedelta

import pytest
from django.core.files.base import ContentFile

from apps.vision import services
from apps.vision.models import Alert, AlertEvent, Clip, MinuteStat, VisionSettings
from apps.vision.tests.conftest import DAY, local
from apps.vision.tests.factories import make_alert, stat
from apps.vision.tests.helpers import jpeg, mp4

pytestmark = pytest.mark.django_db


def test_old_numbers_photos_and_clips_go(cameras, freeze, private_media):
    company = cameras.counter.company
    VisionSettings.objects.filter(company=company).update(
        stats_keep_days=30, photos_keep_days=7, clips_keep_days=10
    )
    now = freeze(local(DAY, 3, 50))
    stat(cameras.door, now - timedelta(days=31), entered=3)
    kept_stat = stat(cameras.door, now - timedelta(days=29), entered=3)

    old_alert = make_alert(cameras.counter, started_at=now - timedelta(days=40))
    photo_alert = make_alert(cameras.counter, started_at=now - timedelta(days=8))
    photo_alert.photo.save("x.jpg", ContentFile(jpeg()), save=True)
    fresh_alert = make_alert(cameras.counter, started_at=now - timedelta(days=2))
    fresh_alert.photo.save("y.jpg", ContentFile(jpeg()), save=True)
    old_photo = photo_alert.photo.name

    old_clip = Clip.objects.create(
        company=company,
        camera=cameras.counter,
        reason="manual",
        start=now - timedelta(days=12),
        end=now - timedelta(days=12) + timedelta(seconds=15),
        alert=old_alert,
    )
    Clip.objects.filter(pk=old_clip.pk).update(created_at=now - timedelta(days=12))
    old_clip.refresh_from_db()
    old_clip.video.save("v.mp4", ContentFile(mp4()), save=True)
    video = old_clip.video.name
    kept_clip = Clip.objects.create(
        company=company,
        camera=cameras.counter,
        reason="manual",
        start=now - timedelta(days=1),
        end=now - timedelta(days=1) + timedelta(seconds=15),
    )
    AlertEvent.objects.create(
        agent=cameras.counter.agent, event_id="1b9e0000-0000-4000-8000-000000000001", phase="start"
    )
    AlertEvent.objects.filter().update(received_at=now - timedelta(days=8))

    counts = services.prune(now)

    assert counts == {"stats": 1, "alerts": 1, "photos": 1, "clips": 1}
    assert list(MinuteStat.objects.values_list("pk", flat=True)) == [kept_stat.pk]
    assert not Alert.objects.filter(pk=old_alert.pk).exists()
    photo_alert.refresh_from_db()
    assert not photo_alert.photo
    assert not (private_media / old_photo).exists()
    fresh_alert.refresh_from_db()
    assert fresh_alert.photo
    assert list(Clip.objects.values_list("pk", flat=True)) == [kept_clip.pk]
    assert not (private_media / video).exists()
    assert not AlertEvent.objects.exists()


def test_the_nightly_job_prunes_every_company(cameras, freeze):
    from apps.vision import tasks

    now = freeze(local(DAY, 3, 50))
    stat(cameras.door, now - timedelta(days=500))

    assert tasks.prune()["stats"] == 1
