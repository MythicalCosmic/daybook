"""Fixtures of the Ko‘z tests: attendance's shop (Chilonzor and Yunusobod and their people, a clock
that can be frozen; Wednesday 21 October 2026, Asia/Tashkent) with Ko‘z, sales and attendance on;
a paired box at Chilonzor with three cameras (an entrance, a counter with its zones and till, the
sales floor); a client for the box's device API; and a Telegram outbox that keeps message ids."""

import itertools
from datetime import time
from types import SimpleNamespace

import pytest
from rest_framework.test import APIClient

from apps.attendance.tests.conftest import (  # noqa: F401 (fixtures)
    CHILONZOR,
    DAY,
    YUNUSOBOD,
    chilonzor,
    freeze,
    local,
    staff,
    yunusobod,
)
from apps.companies.models import Branch
from apps.members.models import AccessRole
from apps.members.permissions import Perm
from apps.notifications.tests.telegram_checks import report, sent_problems, text_problems
from apps.vision import services
from apps.vision.models import Camera

QUEUE_ZONES = [
    {"id": "q1", "kind": "queue", "points": [[0.1, 0.55], [0.6, 0.55], [0.7, 0.98], [0.05, 0.98]]},
    {"id": "s1", "kind": "staff", "points": [[0.1, 0.2], [0.8, 0.2], [0.8, 0.45], [0.1, 0.45]]},
]
LINE = [{"id": "l1", "kind": "line", "points": [[0.1, 0.6], [0.9, 0.62]], "in": "left"}]


@pytest.fixture
def shop(company):
    """Attendance's shop, with Ko‘z, sales and attendance on."""
    company.features = ["sales", "attendance", "vision"]
    company.save(update_fields=["features"])
    first = company.branches.order_by("order", "pk").first()
    first.name, first.code = "Chilonzor", "CHL"
    first.latitude, first.longitude = CHILONZOR
    first.opens_at, first.closes_at = time(9, 0), time(21, 0)
    first.save()
    Branch.objects.create(
        company=company,
        name="Yunusobod",
        code="YNS",
        latitude=YUNUSOBOD[0],
        longitude=YUNUSOBOD[1],
        opens_at=time(10, 0),
        closes_at=time(22, 0),
        order=1,
    )
    return company


@pytest.fixture
def people(staff, member, chilonzor):  # noqa: F811 (fixtures by name)
    """attendance's staff, plus a Chilonzor head who sees only Chilonzor's Ko‘z and a reader who
    sees Ko‘z but may not watch it."""
    company = staff.ali.company
    AccessRole.objects.create(
        company=company,
        name="Chilonzor head",
        permissions=[
            Perm.DASHBOARD_ACCESS,
            Perm.VISION_VIEW,
            Perm.VISION_VIDEO,
            Perm.VISION_MANAGE,
        ],
    )
    AccessRole.objects.create(
        company=company,
        name="Ko‘z reader",
        permissions=[Perm.DASHBOARD_ACCESS, Perm.VISION_VIEW, Perm.BRANCHES_ALL],
    )
    head = member.registered(company, "Chilonzor head", first_name="Hamid", home_branch=chilonzor)
    head.branches.add(chilonzor)
    reader = member.registered(company, "Ko‘z reader", first_name="Rano")
    owner = member.registered(company, "Owner", first_name="Olim")
    return SimpleNamespace(**vars(staff), head=head, reader=reader, owner=owner)


def pair_box(branch, *, name="Asosiy qutisi", by=None):
    agent, pairing = services.create_agent(branch.company, by=by, name=name, branch=branch)
    agent, token = services.pair(pairing.code, host={"hostname": "KASSA-PC", "os": "Windows 11"})
    return agent, token


@pytest.fixture
def box(people, chilonzor):  # noqa: F811
    agent, token = pair_box(chilonzor, by=people.manager)
    agent.token = token
    return agent


def device_client(token: str) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.fixture
def device(box):
    return device_client(box.token)


@pytest.fixture
def register(people, chilonzor):  # noqa: F811
    """Chilonzor's till (the one the sales defaults make)."""
    from apps.finance import defaults as finance_defaults
    from apps.sales import defaults as sales_defaults
    from apps.sales.models import Register

    finance_defaults.ensure(chilonzor.company)
    sales_defaults.ensure(chilonzor.company)
    return Register.objects.filter(branch=chilonzor).order_by("pk").first()


@pytest.fixture
def cameras(box, register):
    """The box's inventory: `nvr:1` the entrance, `nvr:3` the counter (queue and staff zones,
    mapped to the till), `nvr:5` the sales floor; all switched on."""
    services.inventory(
        box,
        [
            {
                "key": "nvr:1",
                "name": "Kirish",
                "source": "nvr",
                "channel": 1,
                "w": 1920,
                "h": 1080,
            },
            {
                "key": "nvr:3",
                "name": "Kassa 1",
                "source": "nvr",
                "channel": 3,
                "w": 1920,
                "h": 1080,
            },
            {"key": "nvr:5", "name": "Zal", "source": "nvr", "channel": 5, "w": 1280, "h": 720},
        ],
    )
    found = {camera.key: camera for camera in box.cameras.all()}
    Camera.objects.filter(pk=found["nvr:1"].pk).update(
        role=Camera.Role.ENTRANCE, enabled=True, zones=LINE
    )
    Camera.objects.filter(pk=found["nvr:3"].pk).update(
        role=Camera.Role.COUNTER, enabled=True, zones=QUEUE_ZONES, register=register
    )
    Camera.objects.filter(pk=found["nvr:5"].pk).update(role=Camera.Role.FLOOR, enabled=True)
    rows = {camera.key: camera for camera in box.cameras.all()}
    return SimpleNamespace(door=rows["nvr:1"], counter=rows["nvr:3"], floor=rows["nvr:5"])


@pytest.fixture
def outbox(monkeypatch):
    """Telegram calls recorded instead of made; sends answer message ids 100, 101, … A message
    Telegram would refuse fails the test."""
    numbers = itertools.count(100)
    found = SimpleNamespace(sent=[], edits=[])
    problems = []

    def send(bot, chat_id, text, reply_markup=None, photo=None, photo_storage="default"):
        problems.extend(sent_problems(text, reply_markup, photo))
        message_id = next(numbers)
        found.sent.append(
            {
                "bot": bot,
                "chat_id": chat_id,
                "text": text,
                "reply_markup": reply_markup,
                "photo": photo,
                "photo_storage": photo_storage,
                "message_id": message_id,
            }
        )
        return message_id

    def edit(bot, chat_id, message_id, text, reply_markup=None):
        problems.extend(text_problems(text, limit=1024))
        found.edits.append(
            {
                "bot": bot,
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "reply_markup": reply_markup,
            }
        )

    monkeypatch.setattr("apps.notifications.telegram.send_message", send)
    monkeypatch.setattr("apps.notifications.telegram.edit_message", edit)
    yield found
    assert not problems, report(problems)


def buttons(markup) -> list[str]:
    if not markup:
        return []
    return [button["text"] for row in markup.get("inline_keyboard", []) for button in row]
