"""Ko‘z's owner endpoints (docs/KOZ.md §6): permissions, branch scope and the module switch, the
cameras and their zones, snapshots, the frame and its watch mark, settings, boxes and pairing,
alerts and the live page."""

import base64

import pytest
from django.core.cache import cache

from apps.audit.models import AuditLog
from apps.vision import live
from apps.vision.audit_actions import VisionAction
from apps.vision.models import Agent, Camera, VisionSettings
from apps.vision.tests.conftest import DAY, local, pair_box
from apps.vision.tests.factories import make_alert, make_camera
from apps.vision.tests.helpers import DEVICE, jpeg, owner_url, upload

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def fresh_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def yunusobod_box(yunusobod):
    agent, _token = pair_box(yunusobod, name="Yunusobod qutisi")
    make_camera(agent, key="nvr:2", name="Yunusobod kassa")
    return agent


READS = ["overview/", "live/", "cameras/", "alerts/", "settings/"]


# Who may -----------------------------------------------------------------------------------


@pytest.mark.parametrize("path", READS)
def test_reading_needs_vision_view(owner_api, people, cameras, path):
    company = cameras.counter.company
    assert owner_api(people.reader).get(owner_url(company, path)).status_code == 200
    assert owner_api(people.manager).get(owner_url(company, path)).status_code == 200
    assert owner_api(people.accountant).get(owner_url(company, path)).status_code == 403


@pytest.mark.parametrize("path", ["agents/", "review/"])
def test_boxes_and_review_need_more(owner_api, people, cameras, path):
    company = cameras.counter.company
    assert owner_api(people.reader).get(owner_url(company, path)).status_code == 403
    assert owner_api(people.manager).get(owner_url(company, path)).status_code == 200


@pytest.mark.parametrize("path", [*READS, "agents/", "review/"])
def test_everything_answers_404_while_koz_is_off(owner_api, people, cameras, path):
    company = cameras.counter.company
    company.features = ["sales", "attendance"]
    company.save(update_fields=["features"])

    assert owner_api(people.owner).get(owner_url(company, path)).status_code == 404


def test_another_company_answers_404(owner_api, people, cameras, other_company, member):
    stranger = member(other_company, "Owner")

    response = owner_api(stranger).get(owner_url(cameras.counter.company, "cameras/"))

    assert response.status_code == 404


def test_writes_need_vision_manage(owner_api, people, cameras):
    company = cameras.counter.company
    camera = owner_url(company, f"cameras/{cameras.counter.pk}/")

    assert owner_api(people.reader).patch(camera, {"name": "X"}, format="json").status_code == 403
    assert (
        owner_api(people.reader)
        .patch(owner_url(company, "settings/"), {"queue_people": 4}, format="json")
        .status_code
        == 403
    )
    assert owner_api(people.manager).patch(camera, {"name": "X"}, format="json").status_code == 200


# Branch scope ------------------------------------------------------------------------------


def test_a_branch_head_sees_only_their_branch(owner_api, people, cameras, yunusobod_box):
    company = cameras.counter.company
    head = owner_api(people.head)

    names = {row["name"] for row in head.get(owner_url(company, "cameras/")).json()}
    assert names == {"Kirish", "Kassa 1", "Zal"}
    everyone = {
        row["name"] for row in owner_api(people.manager).get(owner_url(company, "cameras/")).json()
    }
    assert "Yunusobod kassa" in everyone
    theirs = Camera.objects.get(name="Yunusobod kassa")
    assert head.get(owner_url(company, f"cameras/{theirs.pk}/frame/")).status_code == 404
    assert (
        head.patch(
            owner_url(company, f"cameras/{theirs.pk}/"), {"name": "X"}, format="json"
        ).status_code
        == 404
    )
    assert (
        head.get(owner_url(company, "overview/"), {"branch": yunusobod_box.branch_id}).status_code
        == 404
    )
    assert [row["name"] for row in head.get(owner_url(company, "agents/")).json()] == [
        "Asosiy qutisi"
    ]


def test_the_branch_filter(owner_api, people, cameras, yunusobod_box):
    company = cameras.counter.company
    rows = (
        owner_api(people.manager)
        .get(owner_url(company, "cameras/"), {"branch": yunusobod_box.branch_id})
        .json()
    )

    assert [row["name"] for row in rows] == ["Yunusobod kassa"]
    assert (
        owner_api(people.manager).get(owner_url(company, "cameras/"), {"branch": "x"}).status_code
        == 400
    )
    assert (
        owner_api(people.manager)
        .get(owner_url(company, "cameras/"), {"branch": 999999})
        .status_code
        == 404
    )


# Cameras -----------------------------------------------------------------------------------


def test_the_camera_list_shape(owner_api, people, cameras, register):
    company = cameras.counter.company
    rows = owner_api(people.manager).get(owner_url(company, "cameras/")).json()

    counter = next(row for row in rows if row["key"] == "nvr:3")
    assert counter == {
        "id": cameras.counter.pk,
        "key": "nvr:3",
        "name": "Kassa 1",
        "role": "counter",
        "enabled": True,
        "branch": {"id": cameras.counter.branch_id, "name": "Chilonzor"},
        "agent_id": cameras.counter.agent_id,
        "source": "nvr",
        "channel": 3,
        "w": 1920,
        "h": 1080,
        "online": True,
        "last_seen_at": counter["last_seen_at"],
        "zones": cameras.counter.zones,
        "register": {"id": register.pk, "name": register.name},
        "snapshot_url": None,
        "snapshot_at": None,
    }


def test_zones_are_checked_and_their_changes_audited(owner_api, people, cameras):
    company = cameras.counter.company
    url = owner_url(company, f"cameras/{cameras.floor.pk}/")
    good = [
        {"id": "f1", "kind": "floor", "points": [[0, 0], [1, 0], [1, 1], [0, 1]]},
        {"id": "m1", "kind": "mask", "points": [[0.85, 0], [1, 0], [1, 0.3]]},
        {"id": "l1", "kind": "line", "points": [[0.1, 0.6], [0.9, 0.62]], "in": "right"},
    ]

    saved = owner_api(people.manager).patch(url, {"zones": good}, format="json")

    assert saved.status_code == 200
    assert saved.json()["zones"][2] == {
        "id": "l1",
        "kind": "line",
        "points": [[0.1, 0.6], [0.9, 0.62]],
        "in": "right",
    }
    log = AuditLog.objects.get(action=VisionAction.ZONES_CHANGED)
    assert log.details["after"] == ["f1", "m1", "l1"]
    bad = [
        [{"id": "x", "kind": "door", "points": [[0, 0], [1, 0], [1, 1]]}],
        [{"id": "x", "kind": "queue", "points": [[0, 0], [1, 0]]}],
        [{"id": "x", "kind": "queue", "points": [[0, 0], [1.2, 0], [1, 1]]}],
        [{"id": "x", "kind": "line", "points": [[0, 0], [1, 1]]}],
        [{"id": "x", "kind": "line", "points": [[0, 0], [1, 1], [1, 0]], "in": "left"}],
        [{"id": "a", "kind": "floor", "points": [[0, 0], [1, 0], [1, 1]]}] * 2,
        [{"id": "Q 1", "kind": "floor", "points": [[0, 0], [1, 0], [1, 1]]}],
        [{"id": f"z{n}", "kind": "floor", "points": [[0, 0], [1, 0], [1, 1]]} for n in range(9)],
        "not a list",
    ]
    for zones in bad:
        response = owner_api(people.manager).patch(url, {"zones": zones}, format="json")
        assert response.status_code == 400, zones
        assert response.json()["zones"], zones
    cameras.floor.refresh_from_db()
    assert [zone["id"] for zone in cameras.floor.zones] == ["f1", "m1", "l1"]


def test_renaming_and_mapping_a_camera(owner_api, people, cameras, register, yunusobod):
    company = cameras.counter.company
    url = owner_url(company, f"cameras/{cameras.door.pk}/")

    changed = owner_api(people.manager).patch(
        url,
        {"name": "Eshik", "role": "counter", "enabled": False, "register_id": register.pk},
        format="json",
    )

    assert changed.status_code == 200
    body = changed.json()
    assert (body["name"], body["role"], body["enabled"]) == ("Eshik", "counter", False)
    assert body["register"]["id"] == register.pk
    cameras.door.refresh_from_db()
    assert cameras.door.renamed is True
    log = AuditLog.objects.get(action=VisionAction.CAMERA_CHANGED)
    assert log.details["changes"]["name"] == ["Kirish", "Eshik"]
    from apps.sales.models import Register

    elsewhere = Register.objects.filter(branch=yunusobod).first()
    if elsewhere is not None:
        wrong = owner_api(people.manager).patch(url, {"register_id": elsewhere.pk}, format="json")
        assert (wrong.status_code, wrong.json()["code"]) == (400, "register")
    cleared = owner_api(people.manager).patch(url, {"register_id": None}, format="json")
    assert cleared.json()["register"] is None


def test_snapshots_asked_for_and_shown(owner_api, people, cameras, device):
    company = cameras.counter.company
    url = owner_url(company, f"cameras/{cameras.door.pk}/snapshot/")

    assert owner_api(people.manager).get(url).status_code == 404  # none yet
    asked = owner_api(people.manager).post(url)
    assert asked.status_code == 202
    assert asked.json()["snapshot_requested_at"].endswith("Z")
    assert owner_api(people.reader).post(url).status_code == 403

    device.post(f"{DEVICE}cameras/nvr:1/snapshot/", {"image": upload(jpeg(1920, 1080))})
    shown = owner_api(people.manager).get(url)
    assert shown.status_code == 200
    assert shown["Content-Type"] == "image/jpeg"
    assert shown["X-Content-Type-Options"] == "nosniff"
    assert shown.content.startswith(b"\xff\xd8")
    assert owner_api(people.reader).get(url).status_code == 403  # view alone doesn't show it
    row = next(
        row
        for row in owner_api(people.manager).get(owner_url(company, "cameras/")).json()
        if row["key"] == "nvr:1"
    )
    assert row["snapshot_url"].startswith("/api/v1/files/")


def test_the_live_view_marks_the_camera_watched_and_audits_the_first_look(
    owner_api, people, cameras
):
    company = cameras.counter.company
    url = owner_url(company, f"cameras/{cameras.counter.pk}/frame/")

    assert owner_api(people.reader).get(url).status_code == 403
    for _poll in range(3):
        assert owner_api(people.manager).get(url).status_code == 204
    assert live.watched([cameras.counter.pk]) == {cameras.counter.pk}
    assert AuditLog.objects.filter(action=VisionAction.LIVE_VIEWED).count() == 1
    owner_api(people.head).get(url)
    assert AuditLog.objects.filter(action=VisionAction.LIVE_VIEWED).count() == 2

    live.put_frame(
        cameras.counter.pk,
        {"at": "2026-10-21T13:31:05.400Z", "w": 960, "h": 540, "people": [], "jpeg": b"\xff\xd8x"},
    )
    body = owner_api(people.manager).get(url).json()
    assert base64.b64decode(body["image_b64"]) == b"\xff\xd8x"


# Settings ----------------------------------------------------------------------------------


def test_settings_have_their_defaults_ranges_and_audit(owner_api, people, cameras):
    company = cameras.counter.company
    url = owner_url(company, "settings/")

    assert owner_api(people.reader).get(url).json() == {
        "queue_people": 3,
        "queue_wait_s": 120,
        "unattended_s": 90,
        "clear_after_s": 15,
        "cooldown_s": 120,
        "analysis_fps": 2,
        "live_fps": 2,
        "privacy_blur": False,
        "alert_photo": True,
        "record_counter": True,
        "record_hours": 24,
        "notify_on_shift": True,
        "notify_managers": True,
        "stats_keep_days": 400,
        "photos_keep_days": 30,
        "clips_keep_days": 30,
    }
    changed = owner_api(people.manager).patch(
        url, {"queue_people": 4, "privacy_blur": True}, format="json"
    )
    assert changed.status_code == 200
    assert (changed.json()["queue_people"], changed.json()["privacy_blur"]) == (4, True)
    log = AuditLog.objects.get(action=VisionAction.SETTINGS_CHANGED)
    assert log.details["changes"] == {"queue_people": [3, 4], "privacy_blur": [False, True]}
    for field, value in VisionSettings.RANGES.items():
        low, high = value
        for wrong in (low - 1, high + 1):
            response = owner_api(people.manager).patch(url, {field: wrong}, format="json")
            assert response.status_code == 400, (field, wrong)


# Boxes -------------------------------------------------------------------------------------


def test_adding_a_box_gives_its_pairing_code_and_command(
    owner_api, people, cameras, chilonzor, settings
):
    settings.DASHBOARD_URL = "https://daybook.example/dashboard/"
    company = cameras.counter.company

    made = owner_api(people.manager).post(
        owner_url(company, "agents/"),
        {"name": "Ikkinchi quti", "branch_id": chilonzor.pk},
        format="json",
    )

    assert made.status_code == 201
    body = made.json()
    code = body["pairing"]["code"]
    assert body["pairing"]["command"] == f"koz-agent pair https://daybook.example {code}"
    assert body["agent"]["paired"] is False and body["agent"]["cameras"] == 0
    agent = Agent.objects.get(pk=body["agent"]["id"])
    assert AuditLog.objects.filter(action=VisionAction.BOX_ADDED, target_id=agent.pk).exists()

    again = owner_api(people.manager).post(owner_url(company, f"agents/{agent.pk}/pairing/"))
    assert again.status_code == 200 and again.json()["code"] != code
    assert AuditLog.objects.filter(action=VisionAction.PAIRING_CODE).exists()


def test_a_branch_head_adds_boxes_only_to_their_branch(owner_api, people, cameras, yunusobod):
    response = owner_api(people.head).post(
        owner_url(cameras.counter.company, "agents/"),
        {"name": "Quti", "branch_id": yunusobod.pk},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["branch_id"]


def test_the_box_list_and_removing_one(owner_api, people, box, cameras, device):
    company = box.company
    device.post(f"{DEVICE}live/", {"agent": {"version": "0.1.0"}, "cameras": []}, format="json")

    [row] = owner_api(people.manager).get(owner_url(company, "agents/")).json()
    assert row["online"] is True and row["paired"] is True and row["cameras"] == 3
    assert row["host"] == {"hostname": "KASSA-PC", "os": "Windows 11"}
    assert row["version"] == "0.1.0"

    gone = owner_api(people.manager).delete(owner_url(company, f"agents/{box.pk}/"))
    assert gone.status_code == 204
    assert owner_api(people.manager).get(owner_url(company, "agents/")).json() == []
    # Its cameras stay, with their history.
    assert len(owner_api(people.manager).get(owner_url(company, "cameras/")).json()) == 3
    assert (
        owner_api(people.manager).post(owner_url(company, f"agents/{box.pk}/pairing/")).status_code
        == 404
    )


# Alerts and the live page ------------------------------------------------------------------


def test_the_alert_list_filters_and_pages(owner_api, people, cameras, yunusobod_box, freeze):
    freeze(local(DAY, 20, 0))
    company = cameras.counter.company
    make_alert(
        cameras.counter,
        started_at=local(DAY, 18, 0),
        state="resolved",
        resolved_at=local(DAY, 18, 5),
    )
    make_alert(cameras.counter, kind="unattended", started_at=local(DAY, 19, 0))
    elsewhere = make_alert(yunusobod_box.cameras.get(), started_at=local(DAY, 19, 30))

    body = owner_api(people.manager).get(owner_url(company, "alerts/")).json()
    assert body["count"] == 3
    assert [row["started_at"] for row in body["results"]] == [
        "2026-10-21T14:30:00Z",
        "2026-10-21T14:00:00Z",
        "2026-10-21T13:00:00Z",
    ]
    first = body["results"][-1]
    assert first["duration_s"] == 300 and first["state"] == "resolved"
    assert first["camera"] == {"id": cameras.counter.pk, "name": "Kassa 1"}
    alerts = owner_url(company, "alerts/")
    assert owner_api(people.manager).get(alerts, {"state": "open"}).json()["count"] == 2
    assert owner_api(people.manager).get(alerts, {"kind": "unattended"}).json()["count"] == 1
    assert owner_api(people.manager).get(alerts, {"from": "2026-10-22"}).json()["count"] == 0
    assert owner_api(people.manager).get(alerts, {"to": "2026-10-21"}).json()["count"] == 3
    assert owner_api(people.head).get(alerts).json()["count"] == 2
    assert (
        owner_api(people.head).get(owner_url(company, f"alerts/{elsewhere.pk}/")).status_code == 404
    )


def test_the_live_page(owner_api, people, cameras, device, freeze):
    freeze(local(DAY, 18, 40))
    company = cameras.counter.company
    device.post(
        f"{DEVICE}live/",
        {
            "cameras": [
                {
                    "key": "nvr:3",
                    "online": True,
                    "fps": 2.0,
                    "people": 4,
                    "queue": 3,
                    "staff": 1,
                    "wait_s": 70,
                }
            ]
        },
        format="json",
    )
    make_alert(cameras.counter, started_at=local(DAY, 18, 38))

    body = owner_api(people.manager).get(owner_url(company, "live/")).json()

    assert body["at"] == "2026-10-21T13:40:00Z"
    counter = next(row for row in body["cameras"] if row["id"] == cameras.counter.pk)
    assert counter == {
        "id": cameras.counter.pk,
        "name": "Kassa 1",
        "role": "counter",
        "branch_id": cameras.counter.branch_id,
        "online": True,
        "stale": False,
        "people": 4,
        "queue": 3,
        "staff": 1,
        "wait_s": 70,
        "fps": 2.0,
    }
    door = next(row for row in body["cameras"] if row["id"] == cameras.door.pk)
    assert door["stale"] is True and door["people"] is None
    assert len(body["open_alerts"]) == 1
    assert body["today"] == {"visitors": 0, "receipts": None}
