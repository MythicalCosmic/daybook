"""award(): the points ledger, once per key (PLAN-LEARNING §7.1, §10)."""

import threading

import pytest
from django.db import connection

from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.recognition import conf, services
from apps.recognition.models import PointsEntry
from apps.recognition.tests.factories import PointsEntryFactory

pytestmark = pytest.mark.django_db


def test_award_uses_the_table_and_happens_once(shop, ali):
    first = services.award(ali, reason="quiz", key=f"quiz:7:{ali.pk}")
    assert first is not None and first.points == 20 and first.reason == "quiz"
    assert services.award(ali, reason="quiz", key=f"quiz:7:{ali.pk}") is None
    assert services.award(ali, reason="quiz", key=f"quiz:7:{ali.pk}", points=99) is None
    assert PointsEntry.objects.filter(membership=ali).count() == 1


def test_company_points_and_explicit_points(shop, ali):
    settings = conf.get_settings(shop)
    settings.points_table = {"lesson": 12}
    settings.save()
    assert services.award(ali, reason="lesson", key="lesson:1:x").points == 12
    assert services.award(ali, reason="daily", key="daily:3", points=1).points == 1


def test_nothing_while_the_module_is_off_or_for_people_not_working(shop, ali, member):
    shop.features = ["learning"]
    shop.save(update_fields=["features"])
    assert services.award(ali, reason="lesson", key="lesson:1:a") is None
    assert services.touch_streak(ali, services.local_today(shop)) is None
    shop.features = ["recognition"]
    shop.save(update_fields=["features"])
    pending = member(shop, "Employee", status="pending")
    assert services.award(pending, reason="lesson", key="lesson:1:b") is None
    assert not PointsEntry.objects.exists()


def test_points_off_keeps_the_fact_worth_nothing(shop, ali):
    settings = conf.get_settings(shop)
    settings.points_enabled = False
    settings.save()
    assert services.award(ali, reason="lesson", key="lesson:1:a") is None
    entry = PointsEntry.objects.get(key="lesson:1:a")
    assert entry.points == 0  # the badge "first lesson" still sees it
    settings.points_enabled = True
    settings.save()
    assert services.award(ali, reason="lesson", key="lesson:1:a") is None  # no points later


def test_zero_rows_count_for_nothing(shop, ali):
    settings = conf.get_settings(shop)
    settings.points_table = {"lesson": 0}
    settings.save()
    assert services.award(ali, reason="lesson", key="lesson:9:a") is None
    assert PointsEntry.objects.get(key="lesson:9:a").points == 0


def test_bad_calls_are_bugs(shop, ali):
    with pytest.raises(ValueError):
        services.award(ali, reason="nope", key="x:1")
    with pytest.raises(ValueError):
        services.award(ali, reason="lesson", key="")
    with pytest.raises(ValueError):
        services.award(ali, reason="lesson", key="k" * 81)


def test_a_key_already_taken_is_refused_by_the_database(shop, ali):
    PointsEntryFactory(membership=ali, key="quiz:1:1")
    assert services.award(ali, reason="quiz", key="quiz:1:1") is None
    assert PointsEntry.objects.filter(key="quiz:1:1").count() == 1


@pytest.mark.django_db(transaction=True)
def test_award_once_under_concurrency(shop, ali):
    results = []
    barrier = threading.Barrier(4)

    def run():
        barrier.wait()
        try:
            results.append(services.award(ali, reason="course", key=f"course:{ali.pk}"))
        finally:
            connection.close()

    threads = [threading.Thread(target=run) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len([entry for entry in results if entry is not None]) == 1
    assert PointsEntry.objects.filter(key=f"course:{ali.pk}").count() == 1


def test_adjust_needs_the_owner_a_note_and_is_audited(shop, owner, head, ali):
    with pytest.raises(Exception, match="Only owners"):
        services.adjust(ali, points=50, note="Helped at the inspection", by=head)
    with pytest.raises(DomainError):
        services.adjust(ali, points=50, note="  ", by=owner)
    with pytest.raises(DomainError):
        services.adjust(ali, points=0, note="x", by=owner)
    with pytest.raises(DomainError):
        services.adjust(ali, points=20000, note="x", by=owner)
    entry = services.adjust(ali, points=-30, note="Counted twice", by=owner)
    assert entry.points == -30 and entry.reason == "adjust" and entry.by == owner
    assert entry.key.startswith("adjust:")
    log = AuditLog.objects.get(action="recognition.points_adjusted")
    assert log.details["points"] == -30 and log.target_id == ali.pk
