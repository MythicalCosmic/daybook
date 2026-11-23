"""The demo (docs/KOZ.md §9): each pharmacy's box and cameras, stats that agree with the receipts
(55 to 80 % a day, an evening peak with long waits and people leaving), one to three alerts a
day with drawn photos, and a live page that moves with the clock."""

from datetime import time, timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.attendance import demo as attendance_demo
from apps.companies.models import Feature
from apps.core.management.commands.ensure_company_defaults import ensure_company_defaults
from apps.core.management.commands.seed_demo import Command
from apps.timeoff import demo as timeoff_demo
from apps.vision import analytics, demo, demo_live, queries, zones
from apps.vision.models import Agent, Alert, Camera, MinuteStat
from apps.vision.tests.conftest import DAY, local

pytestmark = pytest.mark.django_db


@pytest.fixture
def pharmacy(freeze):
    freeze(local(DAY, 15, 30))
    now = timezone.now()
    company, people = Command()._build_pharmacy(now)
    company.features = list(Feature.values)
    company.save()
    ensure_company_defaults(company)
    timeoff_demo.seed(company, people, now)
    attendance_demo.seed(company, people, now)
    # Receipts as the sales demo leaves them: every open hour of the last two weeks.
    from decimal import Decimal

    from apps.sales.models import Sale

    receipts = [
        Sale(
            company=company,
            branch=branch,
            sold_at=local(day, hour, minute),
            business_day=day,
            total=Decimal(55_000),
            source=Sale.Source.IMPORT,
        )
        for branch in company.branches.all()
        for day in (DAY - timedelta(days=back) for back in range(1, demo.DAYS + 1))
        for hour in demo._hours(branch)
        for minute in range(0, 60, 7)
    ]
    Sale.objects.bulk_create(receipts, batch_size=2000)
    demo.seed(company, people, now)
    demo.finish(company, people, now)
    cache.clear()
    return company, people, now


def test_each_pharmacy_has_a_box_and_four_cameras(pharmacy):
    company, _people, _now = pharmacy
    boxes = Agent.objects.filter(company=company)
    assert boxes.count() == company.branches.count() == 2
    for box in boxes:
        assert box.demo and box.paired and box.version == "0.1.0"
        cameras = {camera.name: camera for camera in box.cameras.all()}
        assert {name: camera.role for name, camera in cameras.items()} == {
            "Kirish": "entrance",
            "Kassa 1": "counter",
            "Zal": "floor",
            "Ombor": "storeroom",
        }
        for camera in cameras.values():
            assert camera.enabled and camera.online and camera.snapshot
            assert zones.clean(camera.zones) == camera.zones
        assert cameras["Kassa 1"].register is not None
        assert cameras["Kassa 1"].register.branch_id == box.branch_id
        assert zones.has(cameras["Kassa 1"].zones, "queue")
        assert zones.has(cameras["Kassa 1"].zones, "staff")
        assert zones.has(cameras["Zal"].zones, "mask")


def test_the_numbers_agree_with_the_receipts(pharmacy):
    company, _people, now = pharmacy
    for branch in company.branches.all():
        for back in range(1, demo.DAYS + 1):
            day = DAY - timedelta(days=back)
            hours, totals = analytics.day_numbers(company, branch_ids=[branch.pk], day=day, now=now)
            assert 0.55 <= totals["conversion"] <= 0.80, (branch.name, day, totals)
            assert all(
                row["visitors"] >= row["receipts"] for row in hours if row["receipts"] is not None
            )
            evening = [row for row in hours if 17 <= row["hour"] < 20]
            midday = [row for row in hours if 11 <= row["hour"] < 14]
            gone = sum(row["visitors"] - row["receipts"] for row in evening)
            assert gone > sum(row["visitors"] - row["receipts"] for row in midday)
    # Today runs up to the build, without receipts yet.
    stats = MinuteStat.objects.filter(company=company)
    assert stats.filter(minute__gte=local(DAY, 0, 0)).exists()
    assert not stats.filter(minute__gt=now).exists()


def test_the_evening_queue_grows(pharmacy):
    company, _people, _now = pharmacy
    counter = Camera.objects.filter(company=company, role="counter").first()
    rows = MinuteStat.objects.filter(camera=counter, minute__lt=local(DAY, 0, 0))

    def average_wait(start, end):
        found = [
            row.wait_max_s
            for row in rows
            if time(start) <= timezone.localtime(row.minute).time() < time(end)
        ]
        return sum(found) / len(found)

    assert average_wait(18, 20) > 1.3 * average_wait(11, 13)


def test_one_to_three_alerts_a_day_with_drawn_photos(pharmacy):
    company, _people, _now = pharmacy
    alerts = Alert.objects.filter(company=company)
    assert alerts.exists()
    per_day = {}
    for alert in alerts:
        assert alert.photo and alert.state == "resolved" and alert.duration_s > 0
        key = (alert.branch_id, timezone.localtime(alert.started_at).date())
        per_day[key] = per_day.get(key, 0) + 1
    assert max(per_day.values()) <= 3
    assert len(per_day) >= demo.DAYS  # most days of both pharmacies have one
    assert alerts.filter(acknowledged_by__isnull=False).exists()
    assert {"queue"} <= set(alerts.values_list("kind", flat=True))


def test_the_live_page_moves_with_the_clock(pharmacy, freeze, owner_api):
    company, people, now = pharmacy
    owner = people["owner"]

    first = queries.live_page(company, branch_ids=None, user=owner.user, now=now)
    later = queries.live_page(
        company, branch_ids=None, user=owner.user, now=now + timedelta(minutes=47)
    )

    assert all(not camera["stale"] and camera["online"] for camera in first["cameras"])
    assert first["today"]["visitors"] > 0
    assert later["today"]["visitors"] > first["today"]["visitors"]
    numbers = lambda page: [(c["queue"], c["people"], c["wait_s"]) for c in page["cameras"]]  # noqa: E731
    assert numbers(first) != numbers(later)
    counter = Camera.objects.filter(company=company, role="counter").first()
    frame = demo_live.frame(counter, now)
    assert frame["jpeg"].startswith(b"\xff\xd8")
    assert (frame["w"], frame["h"]) == (960, 540)
    assert all(len(person["box"]) == 4 for person in frame["people"])
    response = owner_api(owner).get(
        f"/api/v1/owner/companies/{company.pk}/vision/cameras/{counter.pk}/frame/"
    )
    assert response.status_code == 200 and response.json()["image_b64"]
