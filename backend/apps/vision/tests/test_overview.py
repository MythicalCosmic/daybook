"""The overview's numbers (docs/KOZ.md §6.1): visitors from the entrance, receipts from sales,
conversion and its edge cases, people who left, waits and unattended minutes, staff at the
counter and checked in, the week before, the sentences, and the live page's today."""

from datetime import timedelta

import pytest
from django.core.cache import cache

from apps.attendance.models import AttendanceRecord
from apps.vision import analytics, demo_live
from apps.vision.models import Agent, Camera
from apps.vision.tests.conftest import DAY, local
from apps.vision.tests.factories import make_alert, sale, stat
from apps.vision.tests.helpers import owner_url

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def fresh_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def night(freeze):
    """After closing: the day is over."""
    return freeze(local(DAY, 23, 0))


def came_in(camera, hour: int, count: int):
    """`count` people through the door during `hour`, three a minute."""
    minute = 0
    while count > 0:
        stat(camera, local(DAY, hour, minute), entered=min(count, 3))
        count -= 3
        minute += 1


def bought(branch, hour: int, count: int, **fields):
    for index in range(count):
        sale(branch, at=local(DAY, hour, index % 60), **fields)


def counter_minutes(camera, hour: int, *, queued: int, alone: int, wait: int, peak: int):
    """`queued` minutes with a queue (`alone` of them with nobody at the counter), then quiet
    minutes with a pharmacist; the longest wait `wait`, the longest queue `peak`."""
    for minute in range(60):
        if minute < queued:
            nobody = minute < alone
            stat(
                camera,
                local(DAY, hour, minute),
                people_avg=2.0 if nobody else 3.0,
                queue_avg=2.0,
                queue_max=peak if minute == queued - 1 else 2,
                wait_max_s=wait if minute == queued - 1 else 60,
                staff_seconds=0 if nobody else 60,
            )
        else:
            stat(camera, local(DAY, hour, minute), people_avg=1.0, staff_seconds=60)


def checked_in(person, branch, hour_in: int, hour_out: int | None):
    return AttendanceRecord.objects.create(
        company=person.company,
        membership=person,
        date=DAY,
        status=AttendanceRecord.Status.OPEN if hour_out is None else AttendanceRecord.Status.CLOSED,
        check_in_at=local(DAY, hour_in, 0),
        check_out_at=local(DAY, hour_out, 0) if hour_out is not None else None,
        branch=branch,
    )


def overview(owner_api, person, company, **params):
    params.setdefault("day", DAY.isoformat())
    response = owner_api(person).get(owner_url(company, "overview/"), params)
    assert response.status_code == 200, response.content
    return response.json()


# A day -------------------------------------------------------------------------------------


def test_a_day_in_numbers_and_sentences(owner_api, people, cameras, chilonzor, night):
    came_in(cameras.door, 9, 31)
    bought(chilonzor, 9, 22)
    came_in(cameras.door, 18, 61)
    bought(chilonzor, 18, 34)
    counter_minutes(cameras.counter, 18, queued=30, alone=8, wait=260, peak=6)
    checked_in(people.ali, chilonzor, 9, None)
    checked_in(people.vali, chilonzor, 14, 21)
    make_alert(cameras.counter, started_at=local(DAY, 18, 20))

    body = overview(owner_api, people.manager, chilonzor.company, branch=chilonzor.pk)

    assert body["day"] == "2026-10-21"
    assert body["branch"] == {"id": chilonzor.pk, "name": "Chilonzor"}
    assert body["setup"] == {"agents": 1, "cameras": 3, "entrance": True, "counter": True}
    totals = body["totals"]
    assert (totals["visitors"], totals["receipts"], totals["left"]) == (92, 56, 36)
    assert totals["conversion"] == 0.609 and totals["conversion_note"] is None
    assert (totals["wait_max_s"], totals["unattended_minutes"], totals["alerts"]) == (260, 8, 1)
    assert totals["wait_avg_s"] == round((29 * 60 + 260) / 30)
    assert totals["compare"] == {
        "visitors": 0,
        "receipts": None,
        "conversion": None,
        "label": "same_weekday_last_week",
    }
    hours = {row["hour"]: row for row in body["hours"]}
    assert len(body["hours"]) == 24
    assert hours[18] == {
        "hour": 18,
        "visitors": 61,
        "receipts": 34,
        "queue_max": 6,
        "wait_max_s": 260,
        "staff_avg": round((22 * 1.0 + 30 * 1.0) / 60, 1),
        "staff_checked_in": 2,
        "unattended_minutes": 8,
    }
    assert (hours[9]["visitors"], hours[9]["receipts"], hours[9]["staff_checked_in"]) == (31, 22, 1)
    assert hours[3]["staff_avg"] is None and hours[3]["staff_checked_in"] == 0
    assert [(item["kind"], item["severity"], item["hour"]) for item in body["insights"]] == [
        ("lost_peak", "bad", 18),
        ("staff_gap", "warn", 18),
        ("unattended", "warn", 18),
    ]
    assert body["insights"][0]["text"] == (
        "18:00–19:00: 61 people came in, 34 bought. The queue reached 6 and 27 people left "
        "without buying."
    )
    assert body["insights"][1]["text"] == (
        "18:00–19:00: 2 people were checked in, yet customers waited 8 min with nobody at the "
        "counter."
    )
    assert len(body["open_alerts"]) == 1
    assert body["agents"][0]["name"] == "Asosiy qutisi"


def test_the_sentences_speak_the_readers_language(owner_api, people, cameras, chilonzor, night):
    came_in(cameras.door, 18, 61)
    bought(chilonzor, 18, 34)
    counter_minutes(cameras.counter, 18, queued=30, alone=0, wait=260, peak=6)
    people.manager.user.language = "uz"
    people.manager.user.save(update_fields=["language"])

    body = overview(owner_api, people.manager, chilonzor.company)

    assert body["insights"][0]["text"].startswith(
        "18:00–19:00: 61 kishi kirdi, 34 kishi xarid qildi."
    )


# Conversion and its edges ------------------------------------------------------------------


def test_more_receipts_than_visitors_is_an_entrance_undercount(
    owner_api, people, cameras, chilonzor, night
):
    came_in(cameras.door, 10, 5)
    bought(chilonzor, 10, 9)

    totals = overview(owner_api, people.manager, chilonzor.company)["totals"]

    assert (totals["visitors"], totals["receipts"]) == (5, 9)
    assert (totals["conversion"], totals["conversion_note"], totals["left"]) == (
        None,
        "entrance_undercount",
        0,
    )


def test_nobody_counted_means_no_conversion(owner_api, people, cameras, chilonzor, night):
    bought(chilonzor, 10, 0)
    totals = overview(owner_api, people.manager, chilonzor.company)["totals"]

    assert totals["visitors"] == 0
    assert totals["conversion"] is None and totals["conversion_note"] is None


def test_without_an_entrance_camera_there_are_no_visitors(
    owner_api, people, cameras, chilonzor, night
):
    Camera.objects.filter(pk=cameras.door.pk).update(role=Camera.Role.FLOOR)
    bought(chilonzor, 10, 4)

    body = overview(owner_api, people.manager, chilonzor.company)

    assert body["totals"]["visitors"] is None
    assert (body["totals"]["receipts"], body["totals"]["conversion"], body["totals"]["left"]) == (
        4,
        None,
        None,
    )
    assert all(row["visitors"] is None for row in body["hours"])
    assert body["setup"]["entrance"] is False


def test_without_sales_there_are_no_receipts(owner_api, people, cameras, chilonzor, night):
    company = chilonzor.company
    company.features = ["attendance", "vision"]
    company.save(update_fields=["features"])
    came_in(cameras.door, 10, 6)

    totals = overview(owner_api, people.manager, company)["totals"]

    assert (totals["visitors"], totals["receipts"], totals["conversion"]) == (6, None, None)


def test_receipts_not_in_yet_are_unknown_not_zero(owner_api, people, cameras, chilonzor, night):
    """A pharmacy that books shift totals gets its receipts later (imported): none yet is not
    known; one that books every receipt has really sold nothing."""
    from apps.sales import conf as sales_conf
    from apps.sales.models import SalesSettings

    came_in(cameras.door, 10, 6)
    assert overview(owner_api, people.manager, chilonzor.company)["totals"]["receipts"] is None

    settings = sales_conf.get_settings(chilonzor.company)
    settings.mode = SalesSettings.Mode.RECEIPTS
    settings.save()
    totals = overview(owner_api, people.manager, chilonzor.company)["totals"]
    assert (totals["receipts"], totals["conversion"], totals["left"]) == (0, 0.0, 6)


def test_voids_and_returns_are_not_receipts(owner_api, people, cameras, chilonzor, night):
    from django.utils import timezone

    from apps.sales.models import Sale

    came_in(cameras.door, 10, 6)
    bought(chilonzor, 10, 3)
    sale(chilonzor, at=local(DAY, 10, 5), kind=Sale.Kind.REFUND)
    sale(chilonzor, at=local(DAY, 10, 6), voided_at=timezone.now())

    assert overview(owner_api, people.manager, chilonzor.company)["totals"]["receipts"] == 3


def test_a_branch_head_sees_only_their_branchs_numbers(
    owner_api, people, cameras, chilonzor, yunusobod, night
):
    from apps.vision.tests.factories import make_box, make_camera

    door = make_camera(make_box(yunusobod), key="nvr:1", role=Camera.Role.ENTRANCE, zones=[])
    came_in(door, 10, 40)
    came_in(cameras.door, 10, 6)

    assert overview(owner_api, people.head, chilonzor.company)["totals"]["visitors"] == 6
    assert overview(owner_api, people.manager, chilonzor.company)["totals"]["visitors"] == 46
    assert (
        overview(owner_api, people.manager, chilonzor.company, branch=yunusobod.pk)["totals"][
            "visitors"
        ]
        == 40
    )


# The week before ---------------------------------------------------------------------------


def test_a_better_day_than_a_week_ago_says_so(owner_api, people, cameras, chilonzor, night):
    week_ago = DAY - timedelta(days=7)
    for minute in range(20):
        stat(cameras.door, local(week_ago, 10, minute), entered=5)  # 100 visitors
    for index in range(50):
        sale(chilonzor, at=local(week_ago, 11, index))
    came_in(cameras.door, 10, 90)
    bought(chilonzor, 11, 54)

    body = overview(owner_api, people.manager, chilonzor.company)

    assert body["totals"]["compare"] == {
        "visitors": 100,
        "receipts": 50,
        "conversion": 0.5,
        "label": "same_weekday_last_week",
    }
    assert body["totals"]["conversion"] == 0.6
    assert body["insights"] == [
        {
            "kind": "good_day",
            "severity": "good",
            "hour": None,
            "text": "Conversion 60%, the same day a week ago 50%.",
        }
    ]


def test_today_compares_with_a_week_ago_up_to_the_same_time(
    owner_api, people, cameras, chilonzor, freeze
):
    freeze(local(DAY, 12, 0))
    week_ago = DAY - timedelta(days=7)
    stat(cameras.door, local(week_ago, 10, 0), entered=7)
    stat(cameras.door, local(week_ago, 15, 0), entered=50)  # after noon: not yet compared
    came_in(cameras.door, 10, 3)

    body = overview(owner_api, people.manager, chilonzor.company, day="")

    assert body["day"] == "2026-10-21"
    assert body["totals"]["compare"]["visitors"] == 7


def test_a_long_wait_alone_is_said(owner_api, people, cameras, chilonzor, night):
    counter_minutes(cameras.counter, 14, queued=3, alone=0, wait=200, peak=3)

    body = overview(owner_api, people.manager, chilonzor.company)

    assert [(item["kind"], item["hour"]) for item in body["insights"]] == [("long_wait", 14)]
    assert body["insights"][0]["text"] == "The longest wait was 3 min 20 s, at 14:00–15:00."


def test_a_quiet_day_says_nothing(owner_api, people, cameras, chilonzor, night):
    assert overview(owner_api, people.manager, chilonzor.company)["insights"] == []


def test_staff_numbers_need_attendance(owner_api, people, cameras, chilonzor, night):
    company = chilonzor.company
    company.features = ["sales", "vision"]
    company.save(update_fields=["features"])

    hours = overview(owner_api, people.manager, company)["hours"]

    assert all(row["staff_checked_in"] is None for row in hours)


def test_a_bad_day_parameter(owner_api, people, cameras, chilonzor):
    response = owner_api(people.manager).get(
        owner_url(chilonzor.company, "overview/"), {"day": "yesterday"}
    )

    assert response.status_code == 400


# Today on the live page --------------------------------------------------------------------


def test_today_counts_the_door_and_the_receipts_so_far(people, cameras, chilonzor, freeze):
    from apps.sales import conf as sales_conf
    from apps.sales.models import SalesSettings

    freeze(local(DAY, 12, 0))
    settings = sales_conf.get_settings(chilonzor.company)
    settings.mode = SalesSettings.Mode.RECEIPTS
    settings.save()
    came_in(cameras.door, 10, 12)
    bought(chilonzor, 11, 5)

    assert analytics.today_counts(chilonzor.company, branch_ids=None) == {
        "visitors": 12,
        "receipts": 5,
    }


def test_a_demo_boxs_today_moves_with_the_clock(people, cameras, chilonzor, freeze):
    Agent.objects.filter(pk=cameras.door.agent_id).update(demo=True)

    freeze(local(DAY, 12, 0))
    noon = analytics.today_counts(chilonzor.company, branch_ids=None)
    freeze(local(DAY, 19, 0))
    evening = analytics.today_counts(chilonzor.company, branch_ids=None)

    assert 0 < noon["visitors"] < evening["visitors"]
    assert 0.55 * evening["visitors"] <= evening["receipts"] <= 0.8 * evening["visitors"]
    chilonzor.refresh_from_db()
    assert demo_live.busy(chilonzor, local(DAY, 18, 30)) > demo_live.busy(
        chilonzor, local(DAY, 11, 0)
    )
    assert demo_live.busy(chilonzor, local(DAY, 23, 0)) == 0  # closed
