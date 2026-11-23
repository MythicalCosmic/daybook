"""Ko‘z rows for tests that need them without going through a box (the bots' tests, say)."""

import itertools

from django.utils import timezone

from apps.vision import pairing
from apps.vision.models import Agent, Alert, AlertMessage, Camera

ZONES = [
    {"id": "q1", "kind": "queue", "points": [[0.1, 0.55], [0.6, 0.55], [0.7, 0.98], [0.05, 0.98]]},
    {"id": "s1", "kind": "staff", "points": [[0.1, 0.2], [0.8, 0.2], [0.8, 0.45], [0.1, 0.45]]},
]
_message_ids = itertools.count(500)


def make_box(branch, *, name: str = "Asosiy qutisi") -> Agent:
    return Agent.objects.create(
        company=branch.company,
        branch=branch,
        name=name,
        token_hash=pairing.token_hash(pairing.new_token()),
        paired_at=timezone.now(),
    )


def make_camera(agent: Agent, *, key: str = "nvr:3", name: str = "Kassa 1", **fields) -> Camera:
    values = {"role": Camera.Role.COUNTER, "enabled": True, "zones": ZONES, "online": True}
    values.update(fields)
    return Camera.objects.create(
        company=agent.company, agent=agent, branch=agent.branch, key=key, name=name, **values
    )


def make_alert(camera: Camera, *, kind: str = Alert.Kind.QUEUE, **fields) -> Alert:
    now = timezone.now()
    values = {
        "started_at": now,
        "last_event_at": now,
        "announced_at": now,
        "queue": 3,
        "wait_s": 130,
        "staff": 1,
        "peak_queue": 3,
        "peak_wait_s": 130,
    }
    values.update(fields)
    return Alert.objects.create(
        company=camera.company,
        kind=kind,
        branch=camera.branch,
        agent=camera.agent,
        camera=camera,
        **values,
    )


def copy_to(alert: Alert, member, *, reason: str = "on_shift", bot: str = "employee"):
    return AlertMessage.objects.create(
        alert=alert,
        member=member,
        reason=reason,
        bot=bot,
        chat_id=member.user.telegram_id,
        message_id=next(_message_ids),
    )


def stat(camera: Camera, minute, **values):
    """One minute of a camera's numbers (zeros unless given)."""
    from apps.vision.models import MinuteStat

    fields = {"frames": 120}
    fields.update(values)
    return MinuteStat.objects.create(company=camera.company, camera=camera, minute=minute, **fields)


def sale(branch, *, at, register=None, total=55_000, **fields):
    """A receipt as the dashboard would book it (no money moves in these tests)."""
    from decimal import Decimal

    from apps.sales.models import Sale

    values = {"kind": Sale.Kind.SALE, "source": Sale.Source.DASHBOARD}
    values.update(fields)
    return Sale.objects.create(
        company=branch.company,
        branch=branch,
        register=register,
        sold_at=at,
        business_day=at.date(),
        total=Decimal(total),
        **values,
    )
