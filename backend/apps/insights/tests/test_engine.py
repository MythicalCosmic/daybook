"""The engine around the rules: occurrences coming back, dismissing, urgent ones in the owner bot
outside the quiet hours, the beat's slots, and the buttons of the Telegram copy."""

from datetime import time, timedelta

import pytest

from apps.inbox.models import Notification
from apps.inbox.services import run_action
from apps.insights import conf, engine, notify
from apps.insights.models import Insight, InsightSettings
from apps.insights.tests.conftest import NOW, TODAY, days_before, mln
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db


@pytest.fixture
def late_bill(books):
    """A supplier bill 3 days late: a warning about overdue payables (cash is fine)."""
    books.income(mln(50), days_before(70), category="other_income")
    supplier = books.party("Tolzor Farm")
    return books.owed("payable", mln(4), days_before(20), days_before(3), supplier)


@pytest.fixture
def running_out(books):
    """Cash below zero in five days: an urgent cash insight."""
    books.income(mln(5), days_before(70), category="other_income")
    supplier = books.party("Oqtosh Med")
    return books.owed("payable", mln(8), days_before(20), TODAY + timedelta(days=5), supplier)


def payables(company) -> Insight:
    return Insight.objects.get(company=company, kind=Insight.Kind.OVERDUE_PAYABLES)


def test_a_dismissed_insight_stays_dismissed_while_true(shop, books, owner, late_bill):
    from apps.insights import services

    engine.run(shop, NOW, notify=False)
    services.dismiss(payables(shop), by=owner, reason="Agreed with Tolzor")
    engine.run(shop, NOW + timedelta(days=2), notify=False)
    insight = payables(shop)
    assert insight.status == Insight.Status.DISMISSED
    assert insight.dismissed_reason == "Agreed with Tolzor"
    assert insight.resolved_at is None


def test_a_resolved_one_comes_back_after_the_cooldown(shop, books, late_bill):
    engine.run(shop, NOW, notify=False)
    books.pay(late_bill, mln(4), days_before(0))
    engine.run(shop, NOW + timedelta(hours=1), notify=False)
    assert payables(shop).status == Insight.Status.RESOLVED

    supplier = books.party("Ko‘kterak Farm")
    books.owed("payable", mln(5), days_before(20), days_before(2), supplier)
    engine.run(shop, NOW + timedelta(hours=2), notify=False)
    assert payables(shop).status == Insight.Status.RESOLVED  # within the cooldown: no flapping
    result = engine.run(shop, NOW + timedelta(days=2), notify=False)
    insight = payables(shop)
    assert result["reopened"] == 1
    assert insight.status == Insight.Status.OPEN
    assert insight.detected_at == NOW + timedelta(days=2)
    assert insight.metrics["value"] == "5000000.00"


def test_a_dismissed_one_that_went_away_can_happen_again(shop, books, owner, late_bill):
    from apps.insights import services

    engine.run(shop, NOW, notify=False)
    services.dismiss(payables(shop), by=owner)
    books.pay(late_bill, mln(4), days_before(0))
    engine.run(shop, NOW + timedelta(hours=1), notify=False)
    assert payables(shop).resolved_at is not None
    supplier = books.party("Ko‘kterak Farm")
    books.owed("payable", mln(5), days_before(20), days_before(2), supplier)
    engine.run(shop, NOW + timedelta(days=2), notify=False)
    assert payables(shop).status == Insight.Status.OPEN


def test_an_urgent_insight_reaches_the_owner_once(shop, owner, running_out, manager):
    result = engine.run(shop, NOW)
    assert result["notified"] == 1
    insight = Insight.objects.get(company=shop, kind=Insight.Kind.CASH_LOW)
    assert insight.notified_at == NOW
    [message] = Notification.objects.filter(kind=notify.KIND)
    assert message.recipient == owner  # the manager doesn't see finance
    assert message.severity == "critical"
    assert message.url == f"/c/{shop.pk}/owner?insight={insight.pk}"
    assert [action["key"] for action in message.actions] == ["seen", "task"]
    assert "Cash runs out" in message.title
    engine.run(shop, NOW + timedelta(hours=6))
    assert Notification.objects.filter(kind=notify.KIND).count() == 1


def test_quiet_hours_hold_it_until_morning(shop, owner, running_out):
    night = NOW.replace(hour=23)
    assert engine.run(shop, night)["notified"] == 0
    assert not Notification.objects.filter(kind=notify.KIND).exists()
    assert engine.notify_pending(shop, NOW.replace(hour=7, minute=30) + timedelta(days=1)) == 0
    assert engine.notify_pending(shop, NOW.replace(hour=8, minute=5) + timedelta(days=1)) == 1


def test_no_bot_messages_when_the_company_says_so(shop, owner, running_out):
    row = conf.get_settings(shop)
    row.notify_critical_via_bot = False
    row.save()
    assert engine.run(shop, NOW)["notified"] == 0


def test_warnings_never_go_to_the_bot(shop, owner, late_bill):
    assert engine.run(shop, NOW)["notified"] == 0


def test_turning_urgent_notifies_again(shop, books, owner):
    row = conf.get_settings(shop)
    row.min_cash_buffer = mln(10)
    row.save()
    books.income(mln(5), days_before(70), category="other_income")
    engine.run(shop, NOW)
    insight = Insight.objects.get(company=shop, kind=Insight.Kind.CASH_LOW)
    assert insight.severity == "warning"
    assert not Notification.objects.filter(kind=notify.KIND).exists()
    supplier = books.party("Oqtosh Med")
    books.owed("payable", mln(8), days_before(20), TODAY + timedelta(days=5), supplier)
    engine.run(shop, NOW + timedelta(hours=3))
    insight.refresh_from_db()
    assert insight.severity == "critical"
    assert Notification.objects.filter(kind=notify.KIND).count() == 1


def test_got_it_in_telegram_marks_it_seen(shop, owner, running_out):
    engine.run(shop, NOW)
    message = Notification.objects.get(kind=notify.KIND)
    assert run_action(message.pk, "seen", by=owner) == "Marked as seen."
    insight = Insight.objects.get(company=shop, kind=Insight.Kind.CASH_LOW)
    assert insight.status == Insight.Status.ACKNOWLEDGED
    assert insight.acknowledged_by == owner.user


def test_make_it_a_task_in_telegram(shop, owner, running_out):
    engine.run(shop, NOW)
    message = Notification.objects.get(kind=notify.KIND)
    answer = run_action(message.pk, "task", by=owner)
    insight = Insight.objects.get(company=shop, kind=Insight.Kind.CASH_LOW)
    task = Task.objects.get(pk=insight.task_id)
    assert answer == f"Task added: {task.title}"
    assert task.assignee == owner
    assert task.priority == "high"
    assert "Move a supplier payment" in task.description


def test_resolving_closes_the_telegram_buttons(shop, books, owner, running_out):
    engine.run(shop, NOW)
    books.income(mln(100), days_before(60), category="other_income")
    engine.run(shop, NOW + timedelta(hours=2))
    message = Notification.objects.get(kind=notify.KIND)
    assert message.acted_at is not None


def test_quiet_hours_across_midnight():
    row = InsightSettings(quiet_from=time(22), quiet_to=time(8))
    assert engine.in_quiet_hours(row, time(23, 30))
    assert engine.in_quiet_hours(row, time(7, 59))
    assert not engine.in_quiet_hours(row, time(8, 0))
    assert not engine.in_quiet_hours(row, time(21, 59))
    day = InsightSettings(quiet_from=time(13), quiet_to=time(14))
    assert engine.in_quiet_hours(day, time(13, 30))
    assert not engine.in_quiet_hours(day, time(14, 30))


def test_the_beat_runs_each_slot_once(shop, owner, late_bill):
    early = NOW.replace(hour=6, minute=35)
    assert engine.tick(early)["ran"] == 0  # before the first slot of the day
    seven = NOW.replace(hour=7, minute=5)
    assert engine.tick(seven)["ran"] == 1
    assert engine.tick(seven + timedelta(minutes=30))["ran"] == 0
    assert engine.tick(NOW.replace(hour=13, minute=5))["ran"] == 1
    assert payables(shop).status == Insight.Status.OPEN


def test_a_failing_rule_leaves_its_insights_alone(shop, books, late_bill, monkeypatch):
    engine.run(shop, NOW, notify=False)
    from apps.insights import detectors

    rule = detectors.DETECTORS[Insight.Kind.OVERDUE_PAYABLES]

    def broken(ctx):
        raise RuntimeError("boom")

    monkeypatch.setitem(
        detectors.DETECTORS,
        Insight.Kind.OVERDUE_PAYABLES,
        detectors.Detector(rule.kind, rule.domain, rule.feature, broken),
    )
    result = engine.run(shop, NOW + timedelta(hours=1), notify=False)
    assert result["failed"] == 1
    assert payables(shop).status == Insight.Status.OPEN
