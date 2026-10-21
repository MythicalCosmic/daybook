"""Routine work apart from one-off tasks (the owner, 2026-10-21: "routines are just tasks given
automatically… I can't see the finished routines on the tasks page"). The Tasks page lists one-off
work (`routines=without`); the Routines page has a day of routine work with each person's run and
who was skipped, its history, and its own confirmation queue; the two badges count apart.

The clock is frozen on Wednesday 23 October 2030, 12:00 in the company's timezone."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.audit.models import AuditLog
from apps.members.models import Membership
from apps.members.tests.factories import PositionFactory
from apps.tasks.generation import generate_daily_tasks
from apps.tasks.models import Proof, Task
from apps.tasks.tests.factories import TaskFactory, TaskTemplateFactory, jpeg, make_shop
from apps.timeoff.models import TimeOff

pytestmark = pytest.mark.django_db

WED = date(2030, 10, 23)
MON, TUE, THU = WED - timedelta(days=2), WED - timedelta(days=1), WED + timedelta(days=1)


@pytest.fixture
def clock(monkeypatch):
    def set_now(moment: datetime) -> datetime:
        monkeypatch.setattr("django.utils.timezone.now", lambda: moment)
        return moment

    return set_now


@pytest.fixture
def pharmacy(company, member, clock):
    """A pharmacy's two branches with cashiers, its routines and Wednesday's work so far."""
    tz = ZoneInfo(company.timezone)

    def at(day, hour, minute=0):
        return datetime.combine(day, time(hour, minute), tzinfo=tz)

    clock(at(WED, 0, 5) - timedelta(days=40))
    shop = make_shop(company, member)
    cashier = PositionFactory(company=company, name="Kassir")

    def cashier_at(branch, name, **fields):
        return member.registered(
            company, position=cashier, home_branch=branch, first_name=name, **fields
        )

    people = {
        "ali": cashier_at(shop.here, "Ali"),
        "vali": cashier_at(shop.here, "Vali"),
        "gani": cashier_at(shop.there, "Gani"),
        "away": cashier_at(shop.here, "Aziza"),
        "susp": cashier_at(shop.here, "Sardor", status=Membership.Status.SUSPENDED),
        "new": cashier_at(shop.here, "Nodira", onboarded_at=at(WED, 10, 0)),
    }
    TimeOff.objects.create(
        company=company,
        membership=people["away"],
        first_day=WED,
        last_day=WED,
        status=TimeOff.Status.APPROVED,
    )
    kassa = TaskTemplateFactory(
        company=company,
        title="Kassani ochish",
        due_time=time(9, 0),
        positions=[cashier],
        proof=Proof.PHOTO,
        needs_confirmation=True,
        created_by=shop.owner,
    )
    fridge = TaskTemplateFactory(
        company=company,
        title="Muzlatgich haroratini yozish",
        due_time=time(18, 0),
        assignees=[people["ali"]],
        created_by=shop.owner,
    )
    TaskTemplateFactory(
        company=company,
        title="Shanba: omborni sanash",
        weekdays=[5],
        due_time=time(9, 0),
        assignees=[people["ali"]],
        created_by=shop.owner,
    )
    clock(at(WED, 0, 5))
    generate_daily_tasks(company, WED)
    clock(at(WED, 11, 0))
    late = TaskTemplateFactory(
        company=company,
        title="Muddati yaqin dorilar",
        due_time=time(9, 0),
        assignees=[people["ali"]],
        created_by=shop.owner,
    )
    run = {t.assignee_id: t for t in Task.objects.filter(template=kassa, for_date=WED)}
    done = run[people["ali"].pk]
    done.status, done.completed_at = Task.Status.DONE, at(WED, 8, 50)
    done.proof_photo.save("kassa.jpg", jpeg(), save=False)
    done.save()
    waiting = run[people["vali"].pk]
    waiting.status, waiting.completed_at = Task.Status.REVIEW, at(WED, 9, 20)
    waiting.save()
    clock(at(WED, 12, 0))
    return {
        "shop": shop,
        "at": at,
        "people": people,
        "kassa": kassa,
        "fridge": fridge,
        "late": late,
        "cashier": cashier,
    }


def path(company, rest):
    return f"/api/v1/owner/companies/{company.pk}/{rest}"


def test_a_day_of_routine_work_shows_every_run_and_who_was_skipped(pharmacy, owner_api):
    shop, at = pharmacy["shop"], pharmacy["at"]
    body = owner_api(shop.owner).get(path(shop.company, "routines/day/")).json()
    assert body["day"] == WED.isoformat() and body["idle"] == 1  # Saturday's routine
    by_title = {row["routine"]["title"]: row for row in body["routines"]}
    assert list(by_title) == [
        "Kassani ochish",
        "Muddati yaqin dorilar",
        "Muzlatgich haroratini yozish",
    ]

    kassa = by_title["Kassani ochish"]
    assert [(run["member"]["name"].split()[0], run["state"]) for run in kassa["runs"]] == [
        ("Gani", "late"),
        ("Vali", "review"),
        ("Ali", "done"),
    ]
    done = kassa["runs"][2]
    assert done["on_time"] is True and done["proof_photo"] and done["proof_thumb"]
    assert datetime.fromisoformat(done["completed_at"]) == at(WED, 8, 50)
    assert kassa["runs"][1]["can_confirm"] is True and kassa["runs"][1]["on_time"] is False
    assert kassa["progress"] == {"finished": 2, "total": 3, "percent": 67}
    assert [(skip["member"]["name"].split()[0], skip["reason"]) for skip in kassa["skipped"]] == [
        ("Aziza", "time_off"),
        ("Nodira", "joined_later"),
        ("Sardor", "suspended"),
    ]
    assert kassa["counts"]["skipped"] == 3

    late = by_title["Muddati yaqin dorilar"]
    assert late["reason"] == "made_late" and late["runs"] == []
    assert datetime.fromisoformat(late["next_run"]) == at(THU, 9)
    assert late["give"]["people"] == 1
    fridge = by_title["Muzlatgich haroratini yozish"]
    assert [run["state"] for run in fridge["runs"]] == ["open"]
    assert body["totals"]["finished"] == 2 and body["totals"]["total"] == 4

    # Filtered to the other branch: Gani's run alone; nothing of Ali's or the skipped there.
    there = (
        owner_api(shop.owner)
        .get(path(shop.company, "routines/day/"), {"branch": shop.there.pk})
        .json()
    )
    kassa_there = next(r for r in there["routines"] if r["routine"]["title"] == "Kassani ochish")
    assert [run["member"]["name"].split()[0] for run in kassa_there["runs"]] == ["Gani"]
    assert kassa_there["skipped"] == []


def test_a_branch_lead_sees_their_branchs_routine_work(pharmacy, owner_api):
    shop = pharmacy["shop"]
    body = owner_api(shop.lead).get(path(shop.company, "routines/day/")).json()
    kassa = next(r for r in body["routines"] if r["routine"]["title"] == "Kassani ochish")
    # Gani works at the other branch: his run isn't the lead's to see.
    assert {run["member"]["name"].split()[0] for run in kassa["runs"]} == {"Ali", "Vali"}
    assert kassa["progress"] == {"finished": 2, "total": 2, "percent": 100}
    # The late routine belongs to every branch: the lead may not plan it, so it offers nothing.
    late = next(r for r in body["routines"] if r["routine"]["title"] == "Muddati yaqin dorilar")
    assert late["reason"] == "made_late" and late["give"] is None


def test_routine_work_needs_seeing_all_tasks_and_confirming_needs_tasks_confirm(
    pharmacy, owner_api, member
):
    shop = pharmacy["shop"]
    worker = owner_api(shop.worker)
    for rest in ("routines/day/", "routines/history/", "routines/to-confirm/"):
        assert worker.get(path(shop.company, rest)).status_code == 403


def test_history_rates_each_routine_per_day_over_the_work_due(pharmacy, owner_api):
    shop, people, at = pharmacy["shop"], pharmacy["people"], pharmacy["at"]
    kassa = pharmacy["kassa"]

    def run(person, day, **fields):
        return TaskFactory(
            assignee=person,
            created_by=shop.owner,
            kind=Task.Kind.DAILY,
            template=kassa,
            for_date=day,
            due_at=at(day, 9),
            branch=person.home_branch,
            **fields,
        )

    run(people["ali"], MON, status=Task.Status.DONE, completed_at=at(MON, 8, 30))
    run(people["vali"], MON)  # missed
    run(people["ali"], TUE, status=Task.Status.DONE, completed_at=at(TUE, 10, 0))  # late
    body = (
        owner_api(shop.owner)
        .get(
            path(shop.company, "routines/history/"),
            {"from": MON.isoformat(), "to": WED.isoformat()},
        )
        .json()
    )
    assert body["days"] == [MON.isoformat(), TUE.isoformat(), WED.isoformat()]
    rows = {row["routine"]["title"]: row for row in body["routines"]}
    monday, tuesday, wednesday = rows["Kassani ochish"]["cells"]
    assert monday["made"] == 2 and monday["missed"] == 1
    assert monday["percent"] == 50 and tuesday["late"] == 1 and tuesday["percent"] == 100
    assert wednesday["finished"] == 2 and wednesday["percent"] == 67  # Gani is late
    fridge = rows["Muzlatgich haroratini yozish"]["cells"]
    assert fridge[0] is None and fridge[2]["open"] == 1 and fridge[2]["percent"] is None
    ali = next(row for row in body["people"] if row["member"]["id"] == people["ali"].pk)
    assert (ali["made"], ali["finished"], ali["open"], ali["percent"]) == (4, 3, 1, 100)
    assert ali["on_time_percent"] == 67


def test_routine_work_waits_for_confirmation_in_its_own_queue(pharmacy, owner_api):
    shop, people, at = pharmacy["shop"], pharmacy["people"], pharmacy["at"]
    kassa, fridge = pharmacy["kassa"], pharmacy["fridge"]

    def waiting(routine, person, day, due):
        return TaskFactory(
            assignee=person,
            created_by=shop.owner,
            kind=Task.Kind.DAILY,
            template=routine,
            for_date=day,
            due_at=at(day, due),
            branch=person.home_branch,
            status=Task.Status.REVIEW,
            needs_confirmation=True,
            completed_at=at(day, due) - timedelta(minutes=5),
        )

    tuesday_kassa = waiting(kassa, people["gani"], TUE, 9)
    waiting(fridge, people["ali"], TUE, 18)
    one_off = TaskFactory(
        assignee=people["ali"],
        created_by=shop.owner,
        status=Task.Status.REVIEW,
        needs_confirmation=True,
        completed_at=at(WED, 10),
    )
    client = owner_api(shop.owner)
    queue = client.get(path(shop.company, "routines/to-confirm/")).json()
    assert queue["count"] == 3
    assert [(g["routine"]["title"], g["day"]) for g in queue["groups"]] == [
        ("Kassani ochish", TUE.isoformat()),
        ("Muzlatgich haroratini yozish", TUE.isoformat()),
        ("Kassani ochish", WED.isoformat()),
    ]
    # The badges count apart; one-off work is checked on the Tasks side only.
    counters = client.get(path(shop.company, "pulse/")).json()["counters"]
    assert counters["tasks.review"] == 1 and counters["tasks.routine_review"] == 3
    reviews = client.get(path(shop.company, "tasks/reviews/"), {"routines": "without"}).json()
    assert [task["id"] for task in reviews["results"]] == [one_off.pk]

    # "Confirm all" of a group goes through the bulk endpoint: audited, one by one.
    ids = [item["id"] for item in queue["groups"][0]["items"]]
    confirmed = client.post(
        path(shop.company, "tasks/bulk/"), {"ids": ids, "action": "confirm"}, format="json"
    )
    assert confirmed.json()["done"] == 1
    tuesday_kassa.refresh_from_db()
    assert tuesday_kassa.status == Task.Status.DONE
    assert AuditLog.objects.filter(action="task.confirmed", target_id=tuesday_kassa.pk).exists()

    # Nobody confirms their own run, whatever their rights: it isn't even in their queue.
    own = waiting(fridge, shop.owner, TUE, 18)
    queue = client.get(path(shop.company, "routines/to-confirm/")).json()
    assert own.pk not in {item["id"] for group in queue["groups"] for item in group["items"]}
    refused = client.post(
        path(shop.company, "tasks/bulk/"), {"ids": [own.pk], "action": "confirm"}, format="json"
    ).json()
    assert refused["done"] == 0 and refused["results"][0]["ok"] is False


def test_the_tasks_page_lists_one_off_work_and_counts_it_apart(pharmacy, owner_api):
    shop, people, at = pharmacy["shop"], pharmacy["people"], pharmacy["at"]
    one_off = TaskFactory(
        assignee=people["ali"], created_by=shop.owner, due_at=at(WED, 17), branch=shop.here
    )
    client = owner_api(shop.owner)
    tasks = path(shop.company, "tasks/")
    everything = {task["id"] for task in client.get(tasks).json()["results"]}
    one_offs = {task["id"] for task in client.get(tasks, {"routines": "without"}).json()["results"]}
    routine_work = client.get(tasks, {"routines": "only"}).json()["results"]
    assert one_offs == {one_off.pk}
    assert everything == one_offs | {task["id"] for task in routine_work}
    assert {task["kind"] for task in routine_work} == {"daily"}
    assert client.get(tasks, {"routines": "some"}).status_code == 400

    summary = client.get(path(shop.company, "tasks/summary/"), {"routines": "without"}).json()
    assert summary["total_today"] == 1 and summary["late_now"] == 0
    assert client.get(path(shop.company, "tasks/summary/")).json()["total_today"] == 5
    board = client.get(path(shop.company, "tasks/board/"), {"routines": "without"}).json()
    assert sum(column["count"] for column in board["columns"]) == 1


def test_a_day_of_routine_work_doesnt_query_per_run(pharmacy, owner_api, member):
    shop = pharmacy["shop"]
    client = owner_api(shop.owner)
    url = path(shop.company, "routines/day/")
    client.get(url)  # warm caches

    def count() -> int:
        with CaptureQueriesContext(connection) as context:
            assert client.get(url).status_code == 200
        return len(context.captured_queries)

    few = count()
    for index in range(5):
        person = member.registered(
            shop.company,
            position=pharmacy["cashier"],
            home_branch=shop.here,
            first_name=f"Kassir {index}",
        )
        TaskFactory(
            assignee=person,
            created_by=shop.owner,
            kind=Task.Kind.DAILY,
            template=pharmacy["kassa"],
            for_date=WED,
            due_at=pharmacy["at"](WED, 9),
            branch=shop.here,
        )
    assert count() == few
