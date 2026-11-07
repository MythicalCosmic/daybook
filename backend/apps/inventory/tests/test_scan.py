"""The daily scan: each expiry step once per batch as one digest per branch, the monthly shelf
check once per branch through create_system_task, the mandatory list, destruction and
controlled-register reminders."""

from datetime import date, datetime, timedelta

import pytest

from apps.inbox.models import Notification
from apps.inventory import scan, services
from apps.inventory.models import BatchStock, MissingRequest
from apps.inventory.tests.conftest import DAY, TZ, D, opening
from apps.inventory.tests.factories import ProductFactory
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db


def digests(branch=None):
    rows = Notification.objects.filter(kind="inventory.expiry_digest")
    if branch is not None:
        rows = rows.filter(target_id=branch.pk)
    return rows


def run(freeze, day: date, hour: int = 7, *, capture):
    freeze(datetime.combine(day, datetime.min.time(), tzinfo=TZ).replace(hour=hour))
    with capture(execute=True):
        return scan.daily_scan()


def test_each_step_once_per_batch(
    shop, owner, head, chilonzor, yunusobod, product, freeze, django_capture_on_commit_callbacks
):
    capture = django_capture_on_commit_callbacks
    soon = opening(chilonzor, product, "S", expires_on=DAY + timedelta(days=25), quantity=4)
    opening(chilonzor, product, "L", expires_on=DAY + timedelta(days=400), quantity=4)
    opening(yunusobod, product, "Y", expires_on=DAY + timedelta(days=80), quantity=4)

    assert run(freeze, DAY, hour=5, capture=capture) == 0  # before 06:00 nothing happens
    assert run(freeze, DAY, capture=capture) == 1
    assert BatchStock.objects.get(batch=soon).notified_step == 30
    assert digests(chilonzor).count() == 2  # owner and the head of Chilonzor
    assert {row.recipient_id for row in digests(yunusobod)} == {owner.pk}
    assert run(freeze, DAY, hour=9, capture=capture) == 0  # once per company day

    before = digests().count()
    run(freeze, DAY + timedelta(days=1), capture=capture)
    assert digests().count() == before  # no new step reached
    run(freeze, DAY + timedelta(days=26), capture=capture)  # expired the day after
    assert BatchStock.objects.get(batch=soon).notified_step == 0
    assert digests(chilonzor).count() == 4
    assert "expiry" in digests(chilonzor).order_by("-pk").first().title.lower()


def test_the_monthly_shelf_check(
    shop, head, chilonzor, yunusobod, product, freeze, nigora, django_capture_on_commit_callbacks
):
    capture = django_capture_on_commit_callbacks
    yunusobod.manager = nigora
    yunusobod.save()
    for index in range(35):
        opening(
            chilonzor,
            product,
            f"S{index}",
            expires_on=date(2027, 1, 1) + timedelta(days=index),
            quantity=1,
        )
    opening(yunusobod, product, "Y", expires_on=date(2028, 1, 1), quantity=1)
    run(freeze, date(2026, 12, 1), capture=capture)
    tasks = Task.objects.filter(company=shop, title__startswith="Expiry shelf check")
    assert tasks.count() == 1  # Yunusobod has nothing within 90 days
    [task] = tasks
    assert task.assignee_id == head.pk and task.created_by_id is None
    assert task.checklist.count() == 30
    scan.shelf_checks(shop, date(2026, 12, 1), shop.stock_settings)
    assert tasks.count() == 1  # once a month


def test_mandatory_medicines_missing(
    shop, owner, chilonzor, yunusobod, freeze, django_capture_on_commit_callbacks
):
    must = ProductFactory(company=shop, name="Ketorolak 10 mg tabletka №10", mandatory_list=True)
    opening(yunusobod, must, "M", expires_on=date(2028, 1, 1), quantity=2)
    run(freeze, DAY, capture=django_capture_on_commit_callbacks)
    [request] = MissingRequest.objects.filter(source="mandatory")
    assert request.branch_id == chilonzor.pk and request.product_id == must.pk
    assert "mandatory" in digests(chilonzor).get(recipient=owner).title.lower()
    run(freeze, DAY + timedelta(days=1), capture=django_capture_on_commit_callbacks)
    assert MissingRequest.objects.filter(source="mandatory").count() == 1


def test_destruction_reminders(
    shop, owner, chilonzor, product, freeze, django_capture_on_commit_callbacks
):
    old = opening(chilonzor, product, "E", expires_on=date(2026, 10, 1), quantity=2)
    writeoff = services.propose_writeoff(
        shop, by=owner, branch=chilonzor, reason="expired", lines=[{"batch": old, "quantity": 2}]
    )
    services.approve_writeoff(writeoff, by=owner)
    run(freeze, DAY + timedelta(days=20), capture=django_capture_on_commit_callbacks)
    run(freeze, DAY + timedelta(days=30), capture=django_capture_on_commit_callbacks)
    run(freeze, DAY + timedelta(days=31), capture=django_capture_on_commit_callbacks)
    keys = sorted(
        Notification.objects.filter(kind="inventory.destroy_due").values_list(
            "dedupe_key", flat=True
        )
    )
    assert keys == [
        f"inventory.destroy_due:{writeoff.pk}:due",
        f"inventory.destroy_due:{writeoff.pk}:soon",
    ]


def test_the_controlled_month_reminders(
    shop, owner, nigora, yunusobod, freeze, django_capture_on_commit_callbacks
):
    drug = ProductFactory(company=shop, control_class="narcotic", rx_required=True)
    freeze(datetime(2026, 10, 15, 12, tzinfo=TZ))
    opening(yunusobod, drug, "N", expires_on=date(2028, 1, 1), quantity=D(3))
    run(freeze, date(2026, 11, 1), capture=django_capture_on_commit_callbacks)
    run(freeze, date(2026, 11, 3), capture=django_capture_on_commit_callbacks)
    run(freeze, date(2026, 11, 4), capture=django_capture_on_commit_callbacks)
    keys = set(
        Notification.objects.filter(
            kind="inventory.controlled_close_due", recipient=nigora
        ).values_list("dedupe_key", flat=True)
    )
    assert keys == {
        f"inventory.controlled_close_due:{yunusobod.pk}:2026-10-01:remind",
        f"inventory.controlled_close_due:{yunusobod.pk}:2026-10-01:late",
    }
