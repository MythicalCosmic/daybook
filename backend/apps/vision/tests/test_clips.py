"""Video receipts (docs/KOZ.md §5.9, §5.10, §6.5, §6.6): a sale's camera, the window, the same
clip for the same window, the box's jobs, offers again and the timeout, the upload (a 40 MB clip
included) and failures, and the signed links that play it."""

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache

from apps.audit.models import AuditLog
from apps.vision import services
from apps.vision.audit_actions import VisionAction
from apps.vision.models import Camera, Clip
from apps.vision.tests.conftest import DAY, device_client, local, pair_box
from apps.vision.tests.factories import make_alert
from apps.vision.tests.helpers import DEVICE, jpeg, mp4, owner_url, upload

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def fresh_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def evening(freeze):
    return freeze(local(DAY, 18, 40))


def make_sale(branch, *, at, register=None, total=55_000, **fields):
    from apps.sales.models import Sale

    return Sale.objects.create(
        company=branch.company,
        branch=branch,
        register=register,
        sold_at=at,
        business_day=at.date(),
        kind=Sale.Kind.SALE,
        total=Decimal(total),
        source=Sale.Source.DASHBOARD,
        **fields,
    )


def ask(owner_api, person, company, body):
    return owner_api(person).post(owner_url(company, "clips/"), body, format="json")


# Asking ------------------------------------------------------------------------------------


def test_a_sale_is_filmed_by_its_tills_camera(owner_api, people, cameras, register, evening):
    sale = make_sale(cameras.counter.branch, at=local(DAY, 18, 30), register=register)

    response = ask(owner_api, people.manager, sale.company, {"sale_id": sale.pk})

    assert response.status_code == 201
    body = response.json()
    assert body["camera"] == {"id": cameras.counter.pk, "name": "Kassa 1"}
    assert (body["state"], body["reason"], body["sale_id"]) == ("pending", "sale", sale.pk)
    assert body["start"] == "2026-10-21T13:29:50Z"
    assert body["end"] == "2026-10-21T13:30:05Z"
    assert body["video_url"] is None and body["failure"] is None
    log = AuditLog.objects.get(action=VisionAction.CLIP_REQUESTED)
    assert log.details["sale_id"] == sale.pk


def test_without_a_mapped_till_the_branchs_counter_camera_films(
    owner_api, people, cameras, evening
):
    Camera.objects.filter(pk=cameras.counter.pk).update(register=None)
    sale = make_sale(cameras.counter.branch, at=local(DAY, 18, 30))

    body = ask(owner_api, people.manager, sale.company, {"sale_id": sale.pk}).json()

    assert body["camera"]["id"] == cameras.counter.pk


def test_a_branch_without_a_counter_camera_says_so(owner_api, people, cameras, yunusobod, evening):
    sale = make_sale(yunusobod, at=local(DAY, 18, 30))

    response = ask(owner_api, people.manager, sale.company, {"sale_id": sale.pk})

    assert response.status_code == 409
    assert response.json()["code"] == "no_camera"


def test_the_same_window_gives_the_same_clip(owner_api, people, cameras, register, evening):
    sale = make_sale(cameras.counter.branch, at=local(DAY, 18, 30), register=register)
    first = ask(owner_api, people.manager, sale.company, {"sale_id": sale.pk}).json()
    close = ask(
        owner_api,
        people.manager,
        sale.company,
        {
            "camera_id": cameras.counter.pk,
            "at": "2026-10-21T13:30:01Z",
            "before_s": 10,
            "after_s": 5,
        },
    ).json()
    far = ask(
        owner_api,
        people.manager,
        sale.company,
        {"camera_id": cameras.counter.pk, "at": "2026-10-21T13:30:20Z"},
    ).json()

    assert close["id"] == first["id"]
    assert far["id"] != first["id"] and far["reason"] == "manual"
    assert Clip.objects.count() == 2
    # Every request is audited, the repeated one too.
    assert AuditLog.objects.filter(action=VisionAction.CLIP_REQUESTED).count() == 3


def test_a_clip_is_at_most_a_minute_and_of_the_past(owner_api, people, cameras, evening):
    company = cameras.counter.company
    camera = cameras.counter.pk

    long = ask(
        owner_api,
        people.manager,
        company,
        {"camera_id": camera, "at": "2026-10-21T13:30:00Z", "before_s": 40, "after_s": 30},
    )
    future = ask(
        owner_api, people.manager, company, {"camera_id": camera, "at": "2026-10-21T14:30:00Z"}
    )
    nothing = ask(owner_api, people.manager, company, {})

    assert long.status_code == 400
    assert (future.status_code, future.json()["code"]) == (400, "window")
    assert nothing.status_code == 400


def test_an_alert_clip_runs_from_10_s_before_to_its_end(owner_api, people, cameras, evening):
    alert = make_alert(
        cameras.counter,
        started_at=local(DAY, 18, 31),
        resolved_at=local(DAY, 18, 31) + timedelta(seconds=30),
        state="resolved",
    )
    long_one = make_alert(cameras.counter, started_at=local(DAY, 18, 20), state="open")

    body = owner_api(people.manager).post(owner_url(alert.company, f"alerts/{alert.pk}/clip/"))
    longer = owner_api(people.manager).post(owner_url(alert.company, f"alerts/{long_one.pk}/clip/"))

    assert body.status_code == 201
    assert (body.json()["start"], body.json()["end"]) == (
        "2026-10-21T13:30:50Z",
        "2026-10-21T13:31:30Z",
    )
    assert (body.json()["reason"], body.json()["alert_id"]) == ("alert", alert.pk)
    start, end = longer.json()["start"], longer.json()["end"]
    assert (start, end) == ("2026-10-21T13:19:50Z", "2026-10-21T13:20:50Z")  # 60 s at most
    detail = owner_api(people.manager).get(owner_url(alert.company, f"alerts/{alert.pk}/"))
    assert detail.json()["clip"] == {"id": body.json()["id"], "state": "pending"}


def test_clips_need_vision_video(owner_api, people, cameras, register, evening):
    sale = make_sale(cameras.counter.branch, at=local(DAY, 18, 30), register=register)

    assert ask(owner_api, people.reader, sale.company, {"sale_id": sale.pk}).status_code == 403
    assert ask(owner_api, people.lead, sale.company, {"sale_id": sale.pk}).status_code == 403


def test_a_sale_of_a_branch_outside_the_scope_answers_404(
    owner_api, people, cameras, yunusobod, evening
):
    other_box, _token = pair_box(yunusobod, name="Yunusobod qutisi")
    services.inventory(other_box, [{"key": "nvr:1", "name": "Kassa"}])
    Camera.objects.filter(agent=other_box).update(role="counter", enabled=True)
    sale = make_sale(yunusobod, at=local(DAY, 18, 30))

    assert ask(owner_api, people.head, sale.company, {"sale_id": sale.pk}).status_code == 404
    assert ask(owner_api, people.manager, sale.company, {"sale_id": sale.pk}).status_code == 201


# The box's side ----------------------------------------------------------------------------


def request(cameras, *, at=None, by=None):
    at = at or local(DAY, 18, 30)
    return services.request_clip(
        cameras.counter,
        by=by,
        start=at - timedelta(seconds=10),
        end=at + timedelta(seconds=5),
        reason=Clip.Reason.MANUAL,
    )


def test_jobs_hand_out_each_clip_once_and_again_after_five_minutes(device, cameras, freeze):
    freeze(local(DAY, 18, 40))
    clip = request(cameras)
    assert device.post(f"{DEVICE}live/", {"cameras": []}, format="json").json()["jobs"] == 1

    first = device.get(f"{DEVICE}jobs/").json()
    assert first == {
        "clips": [
            {
                "id": clip.pk,
                "key": "nvr:3",
                "start": "2026-10-21T13:29:50Z",
                "end": "2026-10-21T13:30:05Z",
            }
        ],
        "snapshots": [],
    }
    clip.refresh_from_db()
    assert (clip.state, clip.offers) == ("fetching", 1)
    assert device.get(f"{DEVICE}jobs/").json()["clips"] == []

    for offer in (2, 3):
        freeze(local(DAY, 18, 40) + timedelta(minutes=6 * (offer - 1)))
        assert services.expire_offers() == 1
        again = device.get(f"{DEVICE}jobs/").json()["clips"]
        assert [row["id"] for row in again] == [clip.pk]
        clip.refresh_from_db()
        assert clip.offers == offer

    freeze(local(DAY, 19, 0))
    services.expire_offers()
    clip.refresh_from_db()
    assert (clip.state, clip.failure) == ("failed", "agent_timeout")
    assert device.get(f"{DEVICE}jobs/").json()["clips"] == []


def test_jobs_carry_the_snapshots_asked_for(device, cameras, people, evening):
    services.request_snapshot(cameras.door, by=people.manager)

    assert device.get(f"{DEVICE}jobs/").json()["snapshots"] == ["nvr:1"]


def test_another_boxs_clip_is_not_this_boxs(device, cameras, yunusobod, evening):
    _other_box, token = pair_box(yunusobod, name="Yunusobod qutisi")
    clip = request(cameras)

    other = device_client(token)
    assert other.get(f"{DEVICE}jobs/").json()["clips"] == []
    response = other.post(f"{DEVICE}clips/{clip.pk}/", {"failed": "nvr_error"}, format="json")
    assert (response.status_code, response.json()["code"]) == (404, "not_found")


def send_video(device, clip, video: bytes, *, poster=True):
    data = {
        "video": upload(video, "clip.mp4", "video/mp4"),
        "meta": json.dumps({"duration_s": 15.0, "source": "recorder", "w": 1280, "h": 720}),
    }
    if poster:
        data["poster"] = upload(jpeg(1280, 720), "poster.jpg")
    return device.post(f"{DEVICE}clips/{clip.pk}/", data)


def test_the_video_arrives_and_plays_through_a_signed_link(
    device, client, cameras, people, owner_api, evening
):
    clip = request(cameras)
    device.get(f"{DEVICE}jobs/")
    video = mp4(200_000)

    assert send_video(device, clip, video).status_code == 204

    clip.refresh_from_db()
    assert (clip.state, clip.duration_s, clip.source, clip.width) == (
        "ready",
        15.0,
        "recorder",
        1280,
    )
    assert clip.video.name.startswith(f"vision/clips/{clip.company_id}/")
    assert clip.video.name.endswith(".mp4")
    assert clip.poster.name.endswith(".jpg")
    body = owner_api(people.manager).get(owner_url(clip.company, f"clips/{clip.pk}/")).json()
    assert body["state"] == "ready" and body["duration_s"] == 15.0
    client.force_login(people.manager.user)
    played = client.get(body["video_url"], HTTP_RANGE="bytes=0-99")
    assert played.status_code == 206
    assert b"".join(played.streaming_content) == video[:100]
    poster = client.get(body["poster_url"])
    assert poster.status_code == 200 and poster["Content-Type"] == "image/jpeg"
    # A link made for someone without vision.video opens nothing.
    from apps.core.files import signed_url

    theirs = signed_url(
        clip.video,
        user=people.reader.user,
        company_id=clip.company_id,
        check=f"vision.clip:{clip.pk}",
    )
    assert client.get(theirs).status_code == 404


def test_a_40_mb_clip_goes_through_and_a_bigger_one_doesnt(device, cameras, evening):
    big = request(cameras)
    bigger = request(cameras, at=local(DAY, 18, 35))

    assert send_video(device, big, mp4(40 * 1024 * 1024), poster=False).status_code == 204
    refused = send_video(device, bigger, mp4(40 * 1024 * 1024 + 1), poster=False)

    assert (refused.status_code, refused.json()["code"]) == (413, "too_large")
    big.refresh_from_db()
    assert big.state == "ready" and big.video.size == 40 * 1024 * 1024


def test_only_an_mp4_is_a_video(device, cameras, evening):
    clip = request(cameras)

    response = send_video(device, clip, b"<html>" + b"0" * 5000)

    assert (response.status_code, response.json()["code"]) == (400, "bad_video")


def test_a_box_that_cant_cut_it_says_why(device, cameras, owner_api, people, evening):
    clip = request(cameras)

    response = device.post(
        f"{DEVICE}clips/{clip.pk}/",
        {"failed": "not_recorded", "detail": "The recorder keeps 3 days."},
        format="json",
    )

    assert response.status_code == 204
    body = owner_api(people.manager).get(owner_url(clip.company, f"clips/{clip.pk}/")).json()
    assert (body["state"], body["failure"]) == ("failed", "not_recorded")
    assert body["failure_text"] == "This moment wasn't recorded."
    bad = device.post(f"{DEVICE}clips/{clip.pk}/", {"failed": "agent_timeout"}, format="json")
    assert bad.status_code == 400


def test_a_ready_clip_stays_ready(device, cameras, evening):
    clip = request(cameras)
    send_video(device, clip, mp4())
    clip.refresh_from_db()
    name = clip.video.name

    assert send_video(device, clip, mp4(9000)).status_code == 204
    device.post(f"{DEVICE}clips/{clip.pk}/", {"failed": "nvr_error"}, format="json")

    clip.refresh_from_db()
    assert (clip.state, clip.video.name) == ("ready", name)


def test_a_late_video_still_counts_after_the_timeout(device, cameras, evening):
    clip = request(cameras)
    Clip.objects.filter(pk=clip.pk).update(state="failed", failure="agent_timeout")

    assert send_video(device, clip, mp4()).status_code == 204

    clip.refresh_from_db()
    assert (clip.state, clip.failure) == ("ready", "")
