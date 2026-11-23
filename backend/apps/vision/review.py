"""Moments worth a look (docs/KOZ.md §6.9): sales voided and cash paid out of a till in a minute
when the till's camera saw nobody at the counter (`queue_max == 0` on that camera and minute).
A moment whose minute the camera has no numbers for isn't listed: nobody can say who was there.

The till's camera is the one mapped to the till's register, else the branch's first enabled
counter camera (as for a sale's video receipt). Payouts are the till's `payout` movements
(cash taken out for an expense); moving cash to the safe or the bank isn't one.
"""

from __future__ import annotations

from datetime import date, datetime

from apps.members import scope
from apps.vision import analytics, queries
from apps.vision.models import Camera, Clip, MinuteStat


def _cameras(company) -> tuple[dict, dict]:
    """(register id -> camera, branch id -> first enabled counter camera)."""
    mapped, counters = {}, {}
    rows = Camera.objects.filter(company=company).order_by("-enabled", "pk")
    for camera in rows:
        if camera.register_id and camera.register_id not in mapped:
            mapped[camera.register_id] = camera
        if camera.enabled and camera.role == Camera.Role.COUNTER:
            counters.setdefault(camera.branch_id, camera)
    return mapped, counters


def _minute(moment: datetime) -> datetime:
    return moment.replace(second=0, microsecond=0)


def items(company, *, branch_ids, day: date) -> dict:
    from apps.sales.models import CashMovement, Sale

    start, end = analytics.bounds(company, day)
    mapped, counters = _cameras(company)

    def camera_of(register_id, branch_id) -> Camera | None:
        return mapped.get(register_id) or counters.get(branch_id)

    moments = []
    voids = scope.restrict(
        Sale.objects.filter(
            company=company, voided_at__gte=start, voided_at__lt=end, kind=Sale.Kind.SALE
        ).select_related("cashier"),
        branch_ids,
    )
    for sale in voids:
        moments.append(
            (
                "void",
                sale.voided_at,
                sale.total,
                sale,
                None,
                sale.cashier,
                camera_of(sale.register_id, sale.branch_id),
            )
        )
    payouts = scope.restrict(
        CashMovement.objects.filter(
            company=company,
            kind=CashMovement.Kind.PAYOUT,
            voided_at__isnull=True,
            created_at__gte=start,
            created_at__lt=end,
        ).select_related("created_by"),
        branch_ids,
    )
    for movement in payouts:
        moments.append(
            (
                "payout",
                movement.created_at,
                movement.amount,
                None,
                movement,
                movement.created_by,
                camera_of(movement.register_id, movement.branch_id),
            )
        )
    keyed = {
        (camera.pk, _minute(at)) for _kind, at, *_rest, camera in moments if camera is not None
    }
    stats = {}
    if keyed:
        for camera_id, minute, queue_max in MinuteStat.objects.filter(
            camera_id__in={camera_id for camera_id, _minute_at in keyed},
            minute__in={minute for _camera_id, minute in keyed},
        ).values_list("camera_id", "minute", "queue_max"):
            stats[(camera_id, minute)] = queue_max
    found = []
    for kind, at, amount, sale, movement, cashier, camera in sorted(moments, key=lambda m: m[1]):
        if camera is None or stats.get((camera.pk, _minute(at))) != 0:
            continue
        clip = _clip(camera, at, sale)
        found.append(
            {
                "kind": kind,
                "at": queries.iso(at),
                "amount": str(amount),
                "sale_id": sale.pk if sale else None,
                "cash_movement_id": movement.pk if movement else None,
                "cashier": queries.person(cashier),
                "camera": queries.ref(camera),
                "queue_max": 0,
                "clip": {"id": clip.pk, "state": clip.state} if clip else None,
            }
        )
    return {"items": found}


def _clip(camera: Camera, at: datetime, sale) -> Clip | None:
    rows = Clip.objects.filter(camera=camera, start__lte=at, end__gte=at)
    found = rows.order_by("-created_at", "-pk").first()
    if found is None and sale is not None:
        found = Clip.objects.filter(sale=sale).order_by("-created_at", "-pk").first()
    return found
