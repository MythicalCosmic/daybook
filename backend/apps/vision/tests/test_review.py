"""The review list (docs/KOZ.md §6.9): voids and payouts in a minute the till's camera saw nobody
at the counter; moments with someone there, or without the camera's numbers, aren't listed."""

from datetime import timedelta
from decimal import Decimal

import pytest

from apps.vision import services
from apps.vision.models import Camera, Clip
from apps.vision.tests.conftest import DAY, local
from apps.vision.tests.factories import sale, stat
from apps.vision.tests.helpers import owner_url

pytestmark = pytest.mark.django_db


def payout(register, by, at, amount=48_000):
    from apps.sales.models import CashMovement

    movement = CashMovement.objects.create(
        company=register.company,
        branch=register.branch,
        register=register,
        kind=CashMovement.Kind.PAYOUT,
        amount=Decimal(amount),
        reason="Ichimlik suvi",
        created_by=by,
    )
    CashMovement.objects.filter(pk=movement.pk).update(created_at=at)
    movement.refresh_from_db()
    return movement


def void(found, at):
    from apps.sales.models import Sale

    Sale.objects.filter(pk=found.pk).update(voided_at=at, void_reason="Xato")


def items(owner_api, person, company, **params):
    params.setdefault("day", DAY.isoformat())
    response = owner_api(person).get(owner_url(company, "review/"), params)
    assert response.status_code == 200, response.content
    return response.json()["items"]


def test_voids_and_payouts_with_nobody_at_the_counter(
    owner_api, people, cameras, register, chilonzor, freeze
):
    freeze(local(DAY, 23, 0))
    lonely = sale(chilonzor, at=local(DAY, 19, 0), register=register, cashier=people.ali)
    busy = sale(chilonzor, at=local(DAY, 19, 2), register=register)
    blind = sale(chilonzor, at=local(DAY, 19, 4), register=register)
    void(lonely, local(DAY, 20, 10) + timedelta(seconds=40))
    void(busy, local(DAY, 20, 11))
    void(blind, local(DAY, 20, 30))  # the camera has no numbers for that minute
    stat(cameras.counter, local(DAY, 20, 10), queue_max=0, people_avg=1)
    stat(cameras.counter, local(DAY, 20, 11), queue_max=2)
    cash = payout(register, people.vali, local(DAY, 21, 5))
    stat(cameras.counter, local(DAY, 21, 5), queue_max=0)
    clip = services.request_clip(
        cameras.counter,
        by=people.manager,
        start=local(DAY, 21, 4) + timedelta(seconds=55),
        end=local(DAY, 21, 5) + timedelta(seconds=20),
        reason=Clip.Reason.MANUAL,
    )

    found = items(owner_api, people.manager, chilonzor.company)

    assert found == [
        {
            "kind": "void",
            "at": "2026-10-21T15:10:40Z",
            "amount": "55000.00",
            "sale_id": lonely.pk,
            "cash_movement_id": None,
            "cashier": {"id": people.ali.pk, "name": people.ali.full_name},
            "camera": {"id": cameras.counter.pk, "name": "Kassa 1"},
            "queue_max": 0,
            "clip": None,
        },
        {
            "kind": "payout",
            "at": "2026-10-21T16:05:00Z",
            "amount": "48000.00",
            "sale_id": None,
            "cash_movement_id": cash.pk,
            "cashier": {"id": people.vali.pk, "name": people.vali.full_name},
            "camera": {"id": cameras.counter.pk, "name": "Kassa 1"},
            "queue_max": 0,
            "clip": {"id": clip.pk, "state": "pending"},
        },
    ]


def test_a_till_without_its_camera_uses_the_branchs_counter(
    owner_api, people, cameras, register, chilonzor, freeze
):
    freeze(local(DAY, 23, 0))
    Camera.objects.filter(pk=cameras.counter.pk).update(register=None)
    found = sale(chilonzor, at=local(DAY, 19, 0), register=register)
    void(found, local(DAY, 20, 10))
    stat(cameras.counter, local(DAY, 20, 10), queue_max=0)

    [item] = items(owner_api, people.manager, chilonzor.company)

    assert item["camera"]["id"] == cameras.counter.pk


def test_the_review_needs_vision_video_and_keeps_to_the_branches(
    owner_api, people, cameras, register, chilonzor, yunusobod, freeze
):
    from apps.sales.models import Register

    freeze(local(DAY, 23, 0))
    other = Register.objects.filter(branch=yunusobod).first()
    found = sale(yunusobod, at=local(DAY, 19, 0), register=other)
    void(found, local(DAY, 20, 10))

    company = chilonzor.company
    assert owner_api(people.reader).get(owner_url(company, "review/")).status_code == 403
    assert items(owner_api, people.head, company) == []
    assert (
        owner_api(people.head).get(owner_url(company, "review/"), {"branch": yunusobod.pk})
    ).status_code == 404
