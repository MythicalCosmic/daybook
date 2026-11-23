"""The boxes' device API (docs/KOZ.md §5): pairing, the token, config and its version, the
inventory, snapshots, live reports and frames in the cache, the watch marks, minute stats."""

import json
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.vision import live, pairing, services
from apps.vision.audit_actions import VisionAction
from apps.vision.models import Agent, Camera, MinuteStat
from apps.vision.tests.conftest import DAY, device_client, local, pair_box
from apps.vision.tests.helpers import DEVICE, jpeg, upload

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    """The box before it has a token: DRF's client, which sends JSON."""
    return APIClient()


@pytest.fixture(autouse=True)
def fresh_cache():
    cache.clear()
    yield
    cache.clear()


def pair_call(client, code, **host):
    return client.post(
        f"{DEVICE}pair/",
        {"code": code, "host": {"hostname": "KASSA-PC", "os": "Windows 11", **host}},
        format="json",
    )


# Pairing -----------------------------------------------------------------------------------


def test_a_code_pairs_the_box_once(client, people, chilonzor, freeze):
    freeze(local(DAY, 9, 0))
    agent, code = services.create_agent(
        chilonzor.company, by=people.manager, name="Asosiy qutisi", branch=chilonzor
    )
    assert pairing.normalize(code.code) is not None
    assert code.code.startswith("KOZ-") and len(code.code) == 13

    response = pair_call(client, code.code, version="0.1.0")

    assert response.status_code == 200
    body = response.json()
    assert body["token"].startswith("koz_") and len(body["token"]) == 44
    assert body["agent"] == {
        "id": agent.pk,
        "name": "Asosiy qutisi",
        "company": {"id": chilonzor.company_id, "name": chilonzor.company.name},
        "branch": {"id": chilonzor.pk, "name": "Chilonzor"},
    }
    assert body["server_time"].endswith("Z")
    agent.refresh_from_db()
    # Only hashes are kept: neither the token nor the code is in the database.
    assert agent.token_hash == pairing.token_hash(body["token"])
    assert body["token"] not in agent.token_hash
    assert agent.pairing_hash == "" and agent.pairing_expires_at is None
    assert (agent.hostname, agent.os, agent.version) == ("KASSA-PC", "Windows 11", "0.1.0")
    assert AuditLog.objects.filter(action=VisionAction.BOX_PAIRED, target_id=agent.pk).exists()

    again = pair_call(client, code.code)
    assert again.status_code == 400
    assert again.json()["code"] == "bad_code"


def test_a_code_reads_the_same_typed_any_way(client, people, chilonzor):
    _agent, code = services.create_agent(
        chilonzor.company, by=people.manager, name="Quti", branch=chilonzor
    )
    typed = code.code.lower().replace("-", " ").replace("0", "o").replace("1", "l")

    assert pair_call(client, typed).status_code == 200


def test_an_expired_or_unknown_code_is_refused(client, people, chilonzor, freeze):
    freeze(local(DAY, 9, 0))
    _agent, code = services.create_agent(
        chilonzor.company, by=people.manager, name="Quti", branch=chilonzor
    )

    freeze(local(DAY, 9, 16))
    late = pair_call(client, code.code)
    unknown = pair_call(client, "KOZ-AAAA-AAAA")
    nonsense = pair_call(client, "hello")

    for response in (late, unknown, nonsense):
        assert response.status_code == 400
        assert response.json()["code"] == "bad_code"
        assert response.json()["detail"]


def test_a_new_code_replaces_the_old_one(client, people, chilonzor):
    agent, first = services.create_agent(
        chilonzor.company, by=people.manager, name="Quti", branch=chilonzor
    )
    second = services.new_pairing(agent, by=people.manager)

    assert pair_call(client, first.code).json()["code"] == "bad_code"
    assert pair_call(client, second.code).status_code == 200


def test_pairing_is_throttled_per_address(client, people, chilonzor):
    _agent, code = services.create_agent(
        chilonzor.company, by=people.manager, name="Quti", branch=chilonzor
    )
    for _try in range(10):
        assert pair_call(client, "KOZ-AAAA-AAAA").status_code == 400

    blocked = pair_call(client, code.code)

    assert blocked.status_code == 429
    assert blocked.json()["code"] == "throttled"
    assert int(blocked["Retry-After"]) > 0
    # Another address still pairs.
    other = client.post(
        f"{DEVICE}pair/", {"code": code.code}, format="json", REMOTE_ADDR="10.1.2.3"
    )
    assert other.status_code == 200


def test_pairing_again_revokes_the_old_token(client, people, chilonzor, box):
    old = device_client(box.token)
    assert old.get(f"{DEVICE}config/").status_code == 200
    code = services.new_pairing(box, by=people.manager)

    # Until the new code is used, the old token keeps working.
    assert old.get(f"{DEVICE}config/").status_code == 200
    token = pair_call(client, code.code).json()["token"]

    refused = old.get(f"{DEVICE}config/")
    assert refused.status_code == 401
    assert refused.json()["code"] == "revoked"
    assert device_client(token).get(f"{DEVICE}config/").status_code == 200


# The token ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "header", [None, "Bearer koz_" + "x" * 40, "Bearer nonsense", "Basic dXNlcjpwYXNz"]
)
def test_a_wrong_or_missing_token_is_revoked(client, box, header):
    if header:
        client.credentials(HTTP_AUTHORIZATION=header)

    response = client.get(f"{DEVICE}config/")

    assert response.status_code == 401
    assert response.json()["code"] == "revoked"
    assert response.json()["detail"]


def test_a_removed_box_is_revoked_and_keeps_its_cameras(device, box, people, cameras):
    services.remove_agent(box, by=people.manager)

    response = device.post(f"{DEVICE}live/", {"cameras": []}, format="json")

    assert response.status_code == 401
    assert response.json()["code"] == "revoked"
    assert Camera.objects.filter(agent=box).count() == 3
    assert not Camera.objects.filter(agent=box, online=True).exists()
    assert AuditLog.objects.filter(action=VisionAction.BOX_REMOVED, target_id=box.pk).exists()


def test_a_box_of_a_company_with_koz_off_is_refused(device, box):
    company = box.company
    company.features = ["sales", "attendance"]
    company.save(update_fields=["features"])

    response = device.get(f"{DEVICE}config/")

    assert response.status_code == 403
    assert response.json()["code"] == "module_off"


# Config ------------------------------------------------------------------------------------


def test_the_config_tells_the_box_its_rules_and_cameras(device, box, cameras, chilonzor):
    body = device.get(f"{DEVICE}config/").json()

    assert body["agent"] == {
        "id": box.pk,
        "name": "Asosiy qutisi",
        "branch": {"id": chilonzor.pk, "name": "Chilonzor"},
        "timezone": "Asia/Tashkent",
    }
    assert body["rules"] == {
        "queue_people": 3,
        "queue_wait_s": 120,
        "unattended_s": 90,
        "clear_after_s": 15,
        "analysis_fps": 2,
        "live_fps": 2,
        "privacy_blur": False,
        "alert_photo": True,
        "record_counter": True,
        "record_hours": 24,
    }
    counter = next(camera for camera in body["cameras"] if camera["key"] == "nvr:3")
    assert counter == {
        "id": cameras.counter.pk,
        "key": "nvr:3",
        "name": "Kassa 1",
        "role": "counter",
        "enabled": True,
        "zones": cameras.counter.zones,
        "register_id": cameras.counter.register_id,
    }
    assert body["snapshot_requested"] == []
    assert len(body["config_version"]) == 8


def test_the_config_version_changes_only_with_the_config(device, cameras, people):
    first = device.get(f"{DEVICE}config/").json()["config_version"]
    assert device.get(f"{DEVICE}config/").json()["config_version"] == first

    services.update_camera(cameras.floor, by=people.manager, changes={"name": "Savdo zali"})
    renamed = device.get(f"{DEVICE}config/").json()["config_version"]
    assert renamed != first

    services.request_snapshot(cameras.door, by=people.manager)
    asked = device.get(f"{DEVICE}config/").json()
    assert asked["snapshot_requested"] == ["nvr:1"]
    assert asked["config_version"] != renamed


# Inventory ---------------------------------------------------------------------------------


def test_the_inventory_adds_updates_and_never_deletes(device, box, people, freeze):
    freeze(local(DAY, 9, 0))
    first = device.post(
        f"{DEVICE}cameras/",
        {
            "cameras": [
                {
                    "key": "nvr:3",
                    "name": "Kamera 03",
                    "source": "nvr",
                    "channel": 3,
                    "w": 1920,
                    "h": 1080,
                    "online": True,
                },
                {"key": "rtsp:zal", "name": "Zal", "source": "rtsp", "w": 1280, "h": 720},
            ]
        },
        format="json",
    )
    assert first.status_code == 200
    ids = {row["key"]: row["id"] for row in first.json()["cameras"]}
    new = Camera.objects.get(pk=ids["nvr:3"])
    assert (new.role, new.enabled, new.name, new.channel) == ("other", False, "Kamera 03", 3)
    assert new.branch_id == box.branch_id

    services.update_camera(new, by=people.manager, changes={"name": "Kassa 1"})
    second = device.post(
        f"{DEVICE}cameras/",
        {"cameras": [{"key": "nvr:3", "name": "Kamera 03 (yangi)", "w": 2560, "h": 1440}]},
        format="json",
    )

    assert second.json()["cameras"] == [{"key": "nvr:3", "id": ids["nvr:3"]}]
    new.refresh_from_db()
    assert (new.name, new.width, new.online) == ("Kassa 1", 2560, True)
    gone = Camera.objects.get(pk=ids["rtsp:zal"])
    assert gone.online is False and gone.name == "Zal"


def test_the_inventory_checks_keys(device, box):
    bad = device.post(f"{DEVICE}cameras/", {"cameras": [{"key": "NVR 3"}]}, format="json")
    twice = device.post(
        f"{DEVICE}cameras/", {"cameras": [{"key": "nvr:3"}, {"key": "nvr:3"}]}, format="json"
    )

    assert bad.status_code == 400 and bad.json()["code"] == "invalid"
    assert twice.status_code == 400
    assert not Camera.objects.filter(agent=box).exists()


# Snapshots ---------------------------------------------------------------------------------


def test_a_snapshot_is_kept_and_answers_the_request(device, cameras, people):
    services.request_snapshot(cameras.door, by=people.manager)

    response = device.post(f"{DEVICE}cameras/nvr:1/snapshot/", {"image": upload(jpeg(1920, 1080))})

    assert response.status_code == 204
    cameras.door.refresh_from_db()
    assert cameras.door.snapshot.name.startswith(f"vision/snapshots/{cameras.door.company_id}/")
    assert cameras.door.snapshot_at is not None
    assert device.get(f"{DEVICE}config/").json()["snapshot_requested"] == []


def test_a_snapshot_must_be_a_small_jpeg(device, cameras):
    big = device.post(
        f"{DEVICE}cameras/nvr:1/snapshot/", {"image": upload(b"\xff\xd8\xff" + b"0" * 1_600_000)}
    )
    text = device.post(
        f"{DEVICE}cameras/nvr:1/snapshot/", {"image": upload(b"<svg></svg>", "x.svg")}
    )
    unknown = device.post(f"{DEVICE}cameras/nvr:9/snapshot/", {"image": upload(jpeg())})

    assert (big.status_code, big.json()["code"]) == (413, "too_large")
    assert (text.status_code, text.json()["code"]) == (400, "bad_image")
    assert (unknown.status_code, unknown.json()["code"]) == (404, "unknown_camera")


# Live reports and frames -------------------------------------------------------------------


def live_report(**camera):
    return {
        "at": "2026-10-21T13:31:05Z",
        "agent": {"version": "0.1.0", "fps": 7.8, "cpu": 23},
        "cameras": [
            {
                "key": "nvr:3",
                "online": True,
                "fps": 2.0,
                "people": 3,
                "queue": 2,
                "staff": 1,
                "wait_s": 45,
                "error": None,
                **camera,
            }
        ],
    }


def test_a_live_report_lives_in_the_cache(device, box, cameras):
    response = device.post(f"{DEVICE}live/", live_report(), format="json")

    assert response.status_code == 200
    body = response.json()
    assert body["watch"] == [] and body["jobs"] == 0
    assert body["config_version"] == device.get(f"{DEVICE}config/").json()["config_version"]
    report = live.reports([cameras.counter.pk])[cameras.counter.pk]
    assert (report["people"], report["queue"], report["staff"], report["wait_s"]) == (3, 2, 1, 45)
    assert live.agent_report(box.pk) == {"version": "0.1.0", "fps": 7.8, "cpu": 23}


def test_last_seen_is_written_at_most_once_a_minute(device, box, cameras, freeze):
    freeze(local(DAY, 18, 0))
    device.post(f"{DEVICE}live/", live_report(), format="json")
    box.refresh_from_db()
    first = box.last_seen_at
    assert first == local(DAY, 18, 0)
    assert box.version == "0.1.0"

    freeze(local(DAY, 18, 0) + timedelta(seconds=5))
    device.post(f"{DEVICE}live/", live_report(), format="json")
    box.refresh_from_db()
    assert box.last_seen_at == first

    live.forget_seen(box.pk)  # the minute has passed
    freeze(
        local(
            DAY,
            18,
            1,
        )
    )
    device.post(f"{DEVICE}live/", live_report(online=False), format="json")
    box.refresh_from_db()
    cameras.counter.refresh_from_db()
    assert box.last_seen_at == local(DAY, 18, 1)
    assert cameras.counter.online is False


def test_watching_a_camera_turns_its_frames_on(device, cameras, owner_api, people):
    assert device.post(f"{DEVICE}live/", live_report(), format="json").json()["watch"] == []
    company = cameras.counter.company
    frame_url = f"/api/v1/owner/companies/{company.pk}/vision/cameras/{cameras.counter.pk}/frame/"

    assert owner_api(people.manager).get(frame_url).status_code == 204  # no frame yet

    assert device.post(f"{DEVICE}live/", live_report(), format="json").json()["watch"] == ["nvr:3"]
    meta = {
        "at": "2026-10-21T13:31:05.400Z",
        "w": 960,
        "h": 540,
        "people": [
            {
                "track": 17,
                "box": [0.31, 0.22, 0.12, 0.55],
                "role": "customer",
                "zone": "q1",
                "wait_s": 45,
            }
        ],
    }
    picture = jpeg(960, 540)
    sent = device.post(
        f"{DEVICE}frames/nvr:3/", {"image": upload(picture), "meta": json.dumps(meta)}
    )
    assert sent.status_code == 204

    shown = owner_api(people.manager).get(frame_url)
    assert shown.status_code == 200
    body = shown.json()
    assert (body["at"], body["w"], body["h"]) == ("2026-10-21T13:31:05.400Z", 960, 540)
    assert body["people"] == meta["people"]
    import base64

    assert base64.b64decode(body["image_b64"]) == picture


def test_frames_of_a_camera_nobody_watches_are_dropped(device, cameras):
    meta = {"at": "2026-10-21T13:31:05Z", "w": 960, "h": 540, "people": []}

    sent = device.post(
        f"{DEVICE}frames/nvr:3/", {"image": upload(jpeg(960, 540)), "meta": json.dumps(meta)}
    )

    assert sent.status_code == 204
    assert live.frame(cameras.counter.pk) is None


def test_a_frame_is_a_small_narrow_jpeg(device, cameras):
    live.watch(cameras.counter.pk)
    meta = json.dumps({"at": "2026-10-21T13:31:05Z", "w": 960, "h": 540})

    wide = device.post(f"{DEVICE}frames/nvr:3/", {"image": upload(jpeg(1280, 720)), "meta": meta})
    heavy = device.post(
        f"{DEVICE}frames/nvr:3/",
        {"image": upload(b"\xff\xd8\xff" + b"1" * 420_000), "meta": meta},
    )
    no_meta = device.post(f"{DEVICE}frames/nvr:3/", {"image": upload(jpeg(960, 540))})

    assert (wide.status_code, wide.json()["code"]) == (400, "bad_image")
    assert (heavy.status_code, heavy.json()["code"]) == (413, "too_large")
    assert no_meta.status_code == 400


# Minute stats ------------------------------------------------------------------------------


def minute(key="nvr:3", at="2026-10-21T13:31:00Z", **values):
    return {
        "key": key,
        "minute": at,
        "frames": 118,
        "people_avg": 2.4,
        "people_max": 5,
        "entered": 0,
        "exited": 0,
        "queue_avg": 1.6,
        "queue_max": 3,
        "wait_max_s": 75,
        "staff_seconds": 60,
        **values,
    }


def test_stats_are_upserted_so_a_retry_is_harmless(device, cameras, freeze):
    freeze(local(DAY, 18, 35))
    rows = {"minutes": [minute(), minute(key="nvr:1", entered=4, exited=1)]}

    first = device.post(f"{DEVICE}stats/", rows, format="json")
    again = device.post(f"{DEVICE}stats/", rows, format="json")
    changed = device.post(f"{DEVICE}stats/", {"minutes": [minute(queue_max=4)]}, format="json")

    assert first.json() == {"stored": 2, "skipped": []}
    assert again.json() == {"stored": 2, "skipped": []}
    assert changed.json()["stored"] == 1
    assert MinuteStat.objects.count() == 2
    stat = MinuteStat.objects.get(camera=cameras.counter)
    assert (stat.queue_max, stat.staff_seconds, stat.company_id) == (
        4,
        60,
        cameras.counter.company_id,
    )


def test_unknown_and_old_minutes_come_back_skipped(device, cameras, freeze):
    freeze(local(DAY, 18, 35))
    rows = {
        "minutes": [
            minute(),
            minute(key="nvr:99"),
            minute(at="2026-10-10T08:00:00Z"),
            minute(at="2026-10-21T13:31:59Z", queue_max=2),  # the same minute again
        ]
    }

    body = device.post(f"{DEVICE}stats/", rows, format="json").json()

    assert body["stored"] == 1
    assert [(row["key"], row["reason"]) for row in body["skipped"]] == [
        ("nvr:99", "unknown_camera"),
        ("nvr:3", "too_old"),
    ]
    assert MinuteStat.objects.get().queue_max == 2  # the last copy of a minute wins


def test_at_most_2000_rows_a_call(device, cameras):
    rows = {"minutes": [minute() for _ in range(2001)]}

    response = device.post(f"{DEVICE}stats/", rows, format="json")

    assert response.status_code == 413
    assert response.json()["code"] == "too_large"


def test_stats_values_are_checked(device, cameras):
    response = device.post(
        f"{DEVICE}stats/", {"minutes": [minute(staff_seconds=61)]}, format="json"
    )

    assert response.status_code == 400
    assert not MinuteStat.objects.exists()


def test_the_command_line_pairs_a_box_without_the_dashboard(chilonzor, people, client):
    from io import StringIO

    from django.core.management import call_command

    out = StringIO()
    call_command(
        "vision_agent",
        "create",
        "--company",
        str(chilonzor.company_id),
        "--branch",
        "Chilonzor",
        "--name",
        "Ikkinchi quti",
        stdout=out,
    )
    text = out.getvalue()
    code = next(word for word in text.split() if word.startswith("KOZ-"))
    assert "koz-agent pair" in text
    assert pair_call(client, code).status_code == 200

    listing = StringIO()
    call_command("vision_agent", "list", "--company", str(chilonzor.company_id), stdout=listing)
    assert "Ikkinchi quti" in listing.getvalue()
    assert Agent.objects.get(name="Ikkinchi quti").paired


def test_pairing_with_the_helper_used_by_the_tests(chilonzor, people):
    agent, token = pair_box(chilonzor)
    assert services.authenticate(token) == agent
    assert services.authenticate(token + "x") is None
    assert timezone.now() > agent.paired_at - timedelta(seconds=5)
