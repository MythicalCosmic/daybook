"""An agent's own page (v5): the run log the runner keeps (`AgentRun`), GET ai/agents/<key>/
(its runs, its Claude calls, its token use, what comes next and its scene) and each agent's
`upcoming` hook.

The reference moment is Tuesday 3 November 2026, 10:00 in Tashkent (UTC+5); the pharmacy
works Monday to Friday.
"""

import dataclasses
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import translation

from apps.ai import agents, availability, drafting, events, services
from apps.ai.agents import (
    deadline_watcher,
    hr_assistant,
    morning_plan,
    photo_checker,
    registry,
    runner,
    voice_tasks,
)
from apps.ai.models import AgentEvent, AgentRun, AgentState, AIUsage
from apps.hr import services as hr
from apps.hr.tests.factories import EmployeeDocumentFactory
from apps.members.models import AccessRole
from apps.members.permissions import Perm
from apps.payroll.tests.factories import CompensationFactory
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory
from apps.timeoff.models import Holiday

pytestmark = pytest.mark.django_db

TZ = ZoneInfo("Asia/Tashkent")
NOW = datetime(2026, 11, 3, 10, 0, tzinfo=TZ)
DETAIL_FIELDS = {
    "key",
    "name",
    "description",
    "icon",
    "enabled",
    "needs_claude",
    "available",
    "unavailable_reason",
    "schedule",
    "running",
    "last_run_at",
    "next_run_at",
    "stats",
    "config",
    "fields",
    "runs",
    "calls",
    "usage",
    "upcoming",
    "scene",
}
RUN_FIELDS = {
    "id",
    "started_at",
    "finished_at",
    "duration_ms",
    "status",
    "forced",
    "done",
    "error",
    "calls",
    "input_tokens",
    "output_tokens",
    "cost_usd",
}
CALL_FIELDS = {
    "at",
    "model",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "latency_ms",
    "stop_reason",
    "cost_usd",
}


def at(day: int, hour: int, minute: int = 0, month: int = 11) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=TZ)


@pytest.fixture
def pharmacy(company, member, ai_on, freeze):
    """AI on, at NOW: the owner Dilnoza, the manager Bekzod who gives work, Alisher who does
    it, and Zarina who only opens the dashboard; the watcher and the morning plan on."""
    freeze(NOW)
    company.timezone = "Asia/Tashkent"
    company.workdays = [0, 1, 2, 3, 4]
    company.save()
    ai_on(company)
    AccessRole.objects.create(company=company, name="Viewer", permissions=[Perm.DASHBOARD_ACCESS])
    people = SimpleNamespace(
        company=company,
        owner=member.registered(company, "Owner", first_name="Dilnoza", last_name="Karimova"),
        giver=member.registered(company, "Manager", first_name="Bekzod", last_name="Mirzayev"),
        worker=member.registered(company, first_name="Alisher", last_name="Valiyev"),
        viewer=member.registered(company, "Viewer", first_name="Zarina", last_name="Usmonova"),
    )
    for person in (people.owner, people.giver, people.worker, people.viewer):
        person.user.telegram_id = 9_100_000 + person.pk
        person.user.save(update_fields=["telegram_id"])
    for key in (deadline_watcher.KEY, morning_plan.KEY):
        state = agents.state_of(company, key)
        state.enabled = True
        state.save()
    return people


def page(owner_api, person, key: str, company=None):
    company_id = company.pk if company is not None else person.company_id
    return owner_api(person).get(f"/api/v1/owner/companies/{company_id}/ai/agents/{key}/")


def usage(company, feature: str, when: datetime, **numbers) -> AIUsage:
    """One recorded Claude call at `when`."""
    numbers = {
        "input_tokens": 1000,
        "output_tokens": 200,
        "cache_read_tokens": 0,
        "cost_micro_usd": 1500,
        "latency_ms": 900,
        "stop_reason": "end_turn",
    } | numbers
    row = AIUsage.objects.create(
        company=company, feature=feature, model="claude-haiku-5-5", **numbers
    )
    AIUsage.objects.filter(pk=row.pk).update(created_at=when)
    return row


def a_run(company, key: str, started: datetime, **fields) -> AgentRun:
    fields = {"status": AgentRun.Status.OK, "finished_at": started + timedelta(seconds=2)} | fields
    return AgentRun.objects.create(company=company, key=key, started_at=started, **fields)


def replaced(monkeypatch, key: str, **changes):
    """The registered agent `key` with `changes` (its run, its schedule) for this test."""
    agent = dataclasses.replace(registry.get(key), **changes)
    monkeypatch.setitem(registry._agents, key, agent)
    return agent


def given_task(people, due_in: timedelta, **fields) -> Task:
    """Work Bekzod gave Alisher, due `due_in` from NOW (negative: late)."""
    fields = {
        "company": people.company,
        "kind": Task.Kind.ASSIGNED,
        "created_by": people.giver,
        "assignee": people.worker,
        "due_at": NOW + due_in,
        "title": "Muzlatgich haroratini tekshirish",
    } | fields
    return TaskFactory(**fields)


def runs_of(company, key: str) -> list[AgentRun]:
    return list(AgentRun.objects.filter(company=company, key=key).order_by("-started_at", "-pk"))


def when(item: dict) -> datetime | None:
    return datetime.fromisoformat(item["at"]) if item["at"] else None


# The page ---------------------------------------------------------------------------------------


def test_the_page_has_the_list_fields_and_its_own(owner_api, pharmacy):
    company = pharmacy.company
    a_run(company, deadline_watcher.KEY, NOW - timedelta(minutes=30), done=2)
    usage(company, deadline_watcher.KEY, NOW - timedelta(minutes=30))

    body = page(owner_api, pharmacy.owner, deadline_watcher.KEY).json()

    assert set(body) == DETAIL_FIELDS
    listed = owner_api(pharmacy.owner).get(f"/api/v1/owner/companies/{company.pk}/ai/agents/")
    row = next(item for item in listed.json() if item["key"] == deadline_watcher.KEY)
    assert {name: body[name] for name in row} == row
    assert set(body["runs"][0]) == RUN_FIELDS
    assert body["runs"][0]["done"] == 2 and body["runs"][0]["duration_ms"] == 2000
    assert set(body["calls"][0]) == CALL_FIELDS
    assert set(body["usage"]) == {"month", "days", "company"}
    assert set(body["usage"]["month"]) == {
        "calls",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cost_usd",
    }
    assert set(body["usage"]["days"][0]) == {
        "date",
        "calls",
        "input_tokens",
        "output_tokens",
        "cost_usd",
    }
    assert body["usage"]["company"] == {"month_cost_usd": "0.001500", "monthly_budget_usd": "20.00"}
    assert {item["kind"] for item in body["upcoming"]} == {"run", "item"}
    assert body["scene"] == "idle"


def test_any_dashboard_user_reads_it_but_money_and_errors_need_ai_configure(owner_api, pharmacy):
    company = pharmacy.company
    a_run(
        company,
        deadline_watcher.KEY,
        NOW - timedelta(minutes=30),
        status=AgentRun.Status.ERROR,
        error="RuntimeError: boom",
        cost_micro_usd=2500,
    )
    usage(company, deadline_watcher.KEY, NOW - timedelta(minutes=30), cost_micro_usd=2500)

    owner = page(owner_api, pharmacy.owner, deadline_watcher.KEY).json()
    viewer = page(owner_api, pharmacy.viewer, deadline_watcher.KEY)

    assert owner["runs"][0]["error"] == "RuntimeError: boom"
    assert owner["runs"][0]["cost_usd"] == "0.002500"
    assert owner["calls"][0]["cost_usd"] == "0.002500"
    assert owner["usage"]["month"]["cost_usd"] == "0.002500"
    assert viewer.status_code == 200
    body = viewer.json()
    assert body["runs"][0]["status"] == "error"
    assert body["runs"][0]["error"] is None and body["runs"][0]["cost_usd"] is None
    assert body["calls"][0]["cost_usd"] is None
    assert body["calls"][0]["input_tokens"] == 1000  # tokens are not money
    assert body["usage"]["month"]["cost_usd"] is None
    assert {day["cost_usd"] for day in body["usage"]["days"]} == {None}
    assert body["usage"]["company"] is None


def test_an_unknown_agent_one_not_listed_and_another_company_are_not_found(
    owner_api, pharmacy, other_company, member
):
    """The HR assistant works only where the company has HR or payroll; someone of another
    company finds nothing at this company's address."""
    stranger = member.registered(other_company, "Owner")

    assert page(owner_api, pharmacy.owner, "nope").status_code == 404
    assert page(owner_api, pharmacy.owner, "hr_assistant").status_code == 404
    assert page(owner_api, stranger, deadline_watcher.KEY, pharmacy.company).status_code == 404
    patched = owner_api(pharmacy.owner).patch(
        f"/api/v1/owner/companies/{pharmacy.company.pk}/ai/agents/hr_assistant/",
        {"enabled": True},
        format="json",
    )
    assert patched.status_code == 404  # not listed here: never a 500


def test_changing_an_agent_still_needs_ai_configure(owner_api, pharmacy):
    url = f"/api/v1/owner/companies/{pharmacy.company.pk}/ai/agents/{deadline_watcher.KEY}/"

    refused = owner_api(pharmacy.viewer).patch(url, {"enabled": False}, format="json")
    assert refused.status_code == 403
    changed = owner_api(pharmacy.owner).patch(url, {"enabled": False}, format="json")
    assert changed.status_code == 200 and changed.json()["enabled"] is False
    assert set(changed.json()) == DETAIL_FIELDS - {"runs", "calls", "usage", "upcoming", "scene"}


def test_the_scene_works_waits_or_sleeps(owner_api, pharmacy):
    company = pharmacy.company
    watcher = AgentState.objects.filter(company=company, key=deadline_watcher.KEY)

    assert page(owner_api, pharmacy.owner, deadline_watcher.KEY).json()["scene"] == "idle"
    watcher.update(running_since=NOW - timedelta(minutes=1))
    assert page(owner_api, pharmacy.owner, deadline_watcher.KEY).json()["scene"] == "working"
    watcher.update(running_since=None, enabled=False)
    off = page(owner_api, pharmacy.owner, deadline_watcher.KEY).json()
    assert off["scene"] == "asleep" and off["upcoming"] == []
    # On, but without Claude the photo checker can't work.
    AgentState.objects.filter(pk=agents.state_of(company, photo_checker.KEY).pk).update(
        enabled=True
    )
    assert page(owner_api, pharmacy.owner, photo_checker.KEY).json()["scene"] == "asleep"


# The run log ------------------------------------------------------------------------------------


def test_each_run_is_recorded_with_what_it_did(pharmacy):
    company = pharmacy.company
    given_task(pharmacy, -timedelta(hours=3))

    runner.tick(NOW)

    [run] = runs_of(company, deadline_watcher.KEY)
    assert (run.status, run.done, run.forced, run.error) == ("ok", 1, False, "")
    assert run.started_at == run.finished_at == NOW  # the clock stands still in this test
    assert (run.calls, run.input_tokens, run.output_tokens, run.cost_micro_usd) == (0, 0, 0, 0)
    runner.tick(NOW + timedelta(minutes=10))  # not due yet: nothing claimed, nothing recorded
    assert len(runs_of(company, deadline_watcher.KEY)) == 1


def test_run_now_is_recorded_as_forced(owner_api, pharmacy, django_capture_on_commit_callbacks):
    url = f"/api/v1/owner/companies/{pharmacy.company.pk}/ai/agents/{deadline_watcher.KEY}/run/"

    with django_capture_on_commit_callbacks(execute=True):
        response = owner_api(pharmacy.owner).post(url)

    assert response.status_code == 202
    [run] = runs_of(pharmacy.company, deadline_watcher.KEY)
    assert run.forced and run.status == "ok" and run.finished_at is not None
    body = page(owner_api, pharmacy.owner, deadline_watcher.KEY).json()
    assert body["runs"][0]["forced"] is True and body["scene"] == "idle"


def test_a_failing_run_is_an_error_with_its_text(pharmacy, monkeypatch):
    def broken(company, state, now):
        raise RuntimeError("boom")

    replaced(monkeypatch, deadline_watcher.KEY, run=broken)
    state = agents.state_of(pharmacy.company, deadline_watcher.KEY)

    assert runner.run_state(state.pk, NOW, forced=True) == 0

    [run] = runs_of(pharmacy.company, deadline_watcher.KEY)
    state.refresh_from_db()
    assert (run.status, run.error, run.forced, run.done) == ("error", "RuntimeError: boom", True, 0)
    assert run.finished_at == NOW and state.last_error == run.error


def test_an_agent_without_a_next_time_is_recorded_as_an_error(owner_api, pharmacy):
    """A setting stored before it was checked (an old row, the admin) leaves the agent no next
    time: that is a run that failed, and its page still opens."""
    state = agents.state_of(pharmacy.company, morning_plan.KEY)
    state.config = {"at": "half past eight", "who": "both"}
    state.save()

    runner.tick(NOW)

    [run] = runs_of(pharmacy.company, morning_plan.KEY)
    state.refresh_from_db()
    assert run.status == "error" and "half past eight" in run.error
    assert run.error == state.last_error
    assert run.started_at == run.finished_at and not run.forced
    body = page(owner_api, pharmacy.owner, morning_plan.KEY).json()
    assert body["runs"][0]["status"] == "error"
    assert [(item["kind"], item["at"]) for item in body["upcoming"]] == [("item", None)]


def test_a_run_sums_the_claude_calls_its_agent_made(
    pharmacy, fake_claude, django_capture_on_commit_callbacks
):
    """The morning plan asks Claude for each plan's summary: the run counts those calls, not
    the calls of other features nor the ones before it started."""
    company = pharmacy.company
    given_task(pharmacy, -timedelta(hours=27))
    usage(company, "chat", NOW, input_tokens=9999)
    usage(company, morning_plan.KEY, NOW - timedelta(hours=1), input_tokens=9999)
    fake_claude.script(
        fake_claude.json({"summary": "Bitta vazifa kechikmoqda."}),
        fake_claude.json({"summary": "Bitta vazifa kechikmoqda."}),
    )
    state = agents.state_of(company, morning_plan.KEY)

    with django_capture_on_commit_callbacks(execute=True):
        assert runner.run_state(state.pk, NOW, forced=True) == 2  # the owner and Bekzod

    [run] = runs_of(company, morning_plan.KEY)
    made = AIUsage.objects.filter(company=company, feature=morning_plan.KEY, created_at=NOW)
    assert len(fake_claude.requests) == made.count() == 2
    assert (run.calls, run.input_tokens, run.output_tokens) == (2, 2400, 600)
    assert run.cost_micro_usd == sum(row.cost_micro_usd for row in made) > 0


def test_the_voice_agents_calls_are_the_drafting_ones(owner_api, pharmacy, fake_claude):
    fake_claude.script(fake_claude.json({"drafts": [], "questions": []}))
    drafting.understand(pharmacy.giver, "Alisher, kassani sana", language="uz")
    usage(pharmacy.company, "chat", NOW)

    calls = page(owner_api, pharmacy.owner, voice_tasks.KEY).json()["calls"]

    assert voice_tasks.AGENT.usage_features == ("task_drafts",)
    assert deadline_watcher.AGENT.usage_features == (deadline_watcher.KEY,)
    assert [(call["input_tokens"], call["output_tokens"]) for call in calls] == [(1200, 300)]


def test_only_the_newest_200_runs_of_an_agent_stay(owner_api, pharmacy, other_company):
    company = pharmacy.company
    key = deadline_watcher.KEY
    AgentRun.objects.bulk_create(
        AgentRun(
            company=company,
            key=key,
            started_at=NOW - timedelta(hours=index + 1),
            finished_at=NOW - timedelta(hours=index + 1),
            status=AgentRun.Status.OK,
        )
        for index in range(AgentRun.RUNS_KEPT)
    )
    oldest = AgentRun.objects.filter(company=company, key=key).order_by("started_at").first()
    a_run(company, morning_plan.KEY, NOW - timedelta(days=30))
    a_run(other_company, key, NOW - timedelta(days=30))
    state = agents.state_of(company, key)

    runner.run_state(state.pk, NOW, forced=True)

    kept = AgentRun.objects.filter(company=company, key=key)
    assert kept.count() == AgentRun.RUNS_KEPT
    assert not kept.filter(pk=oldest.pk).exists()
    assert AgentRun.objects.filter(company=company, key=morning_plan.KEY).count() == 1
    assert AgentRun.objects.filter(company=other_company).count() == 1
    runs = page(owner_api, pharmacy.owner, key).json()["runs"]
    assert len(runs) == 30 and runs[0]["forced"] is True
    assert [run["started_at"] for run in runs] == sorted(
        (run["started_at"] for run in runs), reverse=True
    )


def test_a_run_still_running_after_an_hour_reads_as_an_error(owner_api, pharmacy):
    company = pharmacy.company
    key = deadline_watcher.KEY
    running = {"status": AgentRun.Status.RUNNING, "finished_at": None}
    a_run(company, key, NOW - timedelta(hours=2), **running)
    a_run(company, key, NOW - timedelta(minutes=5), **running)

    owner = page(owner_api, pharmacy.owner, key).json()["runs"]
    viewer = page(owner_api, pharmacy.viewer, key).json()["runs"]

    assert [
        (run["status"], run["error"], run["finished_at"], run["duration_ms"]) for run in owner
    ] == [
        ("running", None, None, None),
        ("error", "Did not finish", None, None),
    ]
    assert (viewer[1]["status"], viewer[1]["error"]) == ("error", None)


# Token use --------------------------------------------------------------------------------------


def test_token_use_by_day_in_the_companys_calendar(owner_api, pharmacy, other_company):
    company = pharmacy.company
    key = deadline_watcher.KEY
    # The budget's cached month total (stale here: rows written past the client) is not what
    # the page reads; the agent's share comes from the same rows as the company's month.
    assert availability.month_spend_micro(company) == 0
    usage(company, key, at(2, 23, 30), input_tokens=100, output_tokens=10, cost_micro_usd=1000)
    # 00:30 in Tashkent is still Monday in UTC: it counts on Tuesday.
    usage(
        company,
        key,
        at(3, 0, 30),
        input_tokens=200,
        output_tokens=20,
        cache_read_tokens=50,
        cost_micro_usd=2000,
    )
    usage(
        company, key, at(31, 12, month=10), input_tokens=400, output_tokens=40, cost_micro_usd=4000
    )
    usage(company, key, at(4, 12, month=10))  # 30 days ago: before the chart
    usage(company, "chat", at(3, 9))  # not this agent's
    usage(other_company, key, at(3, 9))

    body = page(owner_api, pharmacy.owner, key).json()["usage"]

    days = body["days"]
    assert len(days) == 30
    assert (days[0]["date"], days[-1]["date"]) == ("2026-10-05", "2026-11-03")
    assert {
        day["date"]: (day["calls"], day["input_tokens"], day["output_tokens"], day["cost_usd"])
        for day in days
        if day["calls"]
    } == {
        "2026-10-31": (1, 400, 40, "0.004000"),
        "2026-11-02": (1, 100, 10, "0.001000"),
        "2026-11-03": (1, 200, 20, "0.002000"),
    }
    assert {day["cost_usd"] for day in days if not day["calls"]} == {"0.000000"}
    assert body["month"] == {
        "calls": 2,
        "input_tokens": 300,
        "output_tokens": 30,
        "cache_read_tokens": 50,
        "cost_usd": "0.003000",
    }
    # The whole company's month (every feature) beside it, for the agent's share.
    assert body["company"] == {"month_cost_usd": "0.004500", "monthly_budget_usd": "20.00"}


def test_the_calls_list_is_the_newest_30_of_the_agent(owner_api, pharmacy):
    company = pharmacy.company
    for minutes in range(35):
        usage(company, deadline_watcher.KEY, NOW - timedelta(minutes=minutes), latency_ms=minutes)
    usage(company, "chat", NOW + timedelta(minutes=1))

    calls = page(owner_api, pharmacy.owner, deadline_watcher.KEY).json()["calls"]

    assert [call["latency_ms"] for call in calls] == list(range(30))
    assert calls[0] == {
        "at": calls[0]["at"],
        "model": "claude-haiku-5-5",
        "input_tokens": 1000,
        "output_tokens": 200,
        "cache_read_tokens": 0,
        "latency_ms": 0,
        "stop_reason": "end_turn",
        "cost_usd": "0.001500",
    }
    assert datetime.fromisoformat(calls[0]["at"]) == NOW


# What comes next --------------------------------------------------------------------------------


def test_the_agents_that_wait_for_something_say_so(owner_api, pharmacy, fake_claude):
    AgentState.objects.filter(pk=agents.state_of(pharmacy.company, photo_checker.KEY).pk).update(
        enabled=True
    )

    voice = page(owner_api, pharmacy.owner, voice_tasks.KEY).json()["upcoming"]
    photo = page(owner_api, pharmacy.owner, photo_checker.KEY).json()["upcoming"]

    assert voice == [{"at": None, "kind": "item", "label": "Works when a voice note arrives"}]
    assert photo == [{"at": None, "kind": "item", "label": "Checks each proof photo as it arrives"}]


def test_the_deadline_watcher_counts_the_work_due_within_a_day(owner_api, pharmacy):
    given_task(pharmacy, timedelta(hours=2))
    given_task(pharmacy, timedelta(hours=23, minutes=59))
    given_task(pharmacy, timedelta(hours=30))  # later
    given_task(pharmacy, -timedelta(hours=1))  # late already
    given_task(pharmacy, timedelta(hours=2), blocked_at=NOW)
    given_task(pharmacy, timedelta(hours=2), kind=Task.Kind.PERSONAL)
    given_task(pharmacy, timedelta(hours=2), escalated_at=NOW)

    upcoming = page(owner_api, pharmacy.owner, deadline_watcher.KEY).json()["upcoming"]

    assert [(when(item), item["kind"], item["label"]) for item in upcoming] == [
        (at(3, 10, 30), "run", "Scheduled run"),
        (at(3, 11), "run", "Scheduled run"),
        (at(3, 11, 30), "run", "Scheduled run"),
        (None, "item", "Tasks due in the next 24 hours: 2"),
    ]


def test_the_morning_plan_says_whom_its_next_run_is_for(owner_api, pharmacy):
    """Plans go to the heads and managers: the owner and Bekzod here."""
    upcoming = page(owner_api, pharmacy.owner, morning_plan.KEY).json()["upcoming"]

    assert [(when(item), item["kind"], item["label"]) for item in upcoming] == [
        (at(4, 8, 30), "run", "Scheduled run"),
        (at(4, 8, 30), "item", "Plans for 2 people"),
        (at(5, 8, 30), "run", "Scheduled run"),
        (at(6, 8, 30), "run", "Scheduled run"),
    ]


@pytest.mark.parametrize(
    ("language", "labels"),
    [
        ("uz", ["Jadval bo‘yicha ishga tushadi", "2 kishi uchun reja"]),
        ("ru", ["Запуск по расписанию", "Планы для 2 человек"]),
    ],
)
def test_what_comes_next_reads_in_the_readers_language(owner_api, pharmacy, language, labels):
    pharmacy.viewer.user.language = language
    pharmacy.viewer.user.save(update_fields=["language"])

    upcoming = page(owner_api, pharmacy.viewer, morning_plan.KEY).json()["upcoming"]

    assert [item["label"] for item in upcoming[:2]] == labels


@pytest.fixture
def hr_team(shop, staff, ai_on, freeze):
    """HR's pharmacy (apps/hr/tests/conftest.py) at NOW, Monday to Friday, with AI on as the
    owner's consent leaves it: the HR assistant on, its first run tomorrow at 09:00."""
    freeze(NOW)
    shop.workdays = [0, 1, 2, 3, 4]
    shop.save(update_fields=["workdays"])
    ai_on(shop)
    services.enable_ai(shop, by=staff.owner)
    return staff


def hr_upcoming(company) -> list[tuple[datetime | None, str]]:
    with translation.override("en"):
        return hr_assistant.upcoming(company, agents.state_of(company, hr_assistant.KEY), NOW)


def test_the_hr_assistant_expects_the_payroll_check_and_the_bonuses(owner_api, hr_team, shop):
    """Pay day is the 5th and the check runs from 3 days before: tomorrow, the 4th. Bonuses go
    on the month's last workday, Monday the 30th. Ali's medical book and Vali's contract end
    within the warning days; Sara's book later."""
    CompensationFactory(membership=hr_team.ali)
    state = agents.state_of(shop, hr_assistant.KEY)
    state.config = {**state.config, "suggest_bonuses": True}
    state.save()
    EmployeeDocumentFactory(membership=hr_team.ali, expires_on=NOW.date() + timedelta(days=10))
    EmployeeDocumentFactory(membership=hr_team.sara, expires_on=NOW.date() + timedelta(days=90))
    made = hr.create_contract(
        hr_team.vali,
        by=hr_team.owner,
        starts_on=date(2026, 1, 5),
        kind="fixed_term",
        ends_on=NOW.date() + timedelta(days=20),
    )
    hr.activate_contract(made, by=hr_team.owner)

    assert hr_upcoming(shop) == [
        (at(4, 9), "Payroll check before pay day"),
        (at(30, 9), "Bonus suggestions"),
        (None, "Documents and contracts to watch: 2"),
    ]
    upcoming = page(owner_api, hr_team.owner, hr_assistant.KEY).json()["upcoming"]
    assert [(when(item), item["kind"]) for item in upcoming] == [
        (at(4, 9), "run"),
        (at(4, 9), "item"),
        (at(5, 9), "run"),
        (at(6, 9), "run"),
        (at(30, 9), "item"),
        (None, "item"),
    ]

    # October is checked and November's bonuses are suggested: December's turn. A holiday on
    # the last workday moves the bonuses to the workday before.
    events.log(
        shop,
        hr_assistant.KEY,
        "payroll_ready",
        dedupe_key=hr_assistant.payroll_key(date(2026, 10, 1)),
    )
    events.log(
        shop,
        hr_assistant.KEY,
        "bonuses_suggested",
        dedupe_key=hr_assistant.bonuses_key(date(2026, 11, 1)),
    )
    Holiday.objects.create(company=shop, date=date(2026, 12, 31), name="Yangi yil arafasi")

    assert hr_upcoming(shop)[:2] == [
        (at(2, 9, month=12), "Payroll check before pay day"),
        (at(30, 9, month=12), "Bonus suggestions"),
    ]


def test_the_hr_assistant_expects_no_payroll_check_while_payroll_is_unused(hr_team, shop):
    assert hr_upcoming(shop) == [(None, "Documents and contracts to watch: 0")]


# The demo ---------------------------------------------------------------------------------------


def test_the_demo_fills_the_agent_pages(owner_api, pharmacy):
    """`make demo`: the scheduled agents' runs of yesterday and today (Sunday is off) and 30
    days of Claude calls on workdays, nothing after now; a run counts its own calls."""
    from apps.ai import demo

    company = pharmacy.company
    told = events.log(company, deadline_watcher.KEY, "escalated", params={"task": "Kassa"})
    AgentEvent.objects.filter(pk=told.pk).update(created_at=at(3, 9, 10))

    demo.agent_pages(company, NOW)

    watcher = runs_of(company, deadline_watcher.KEY)
    assert len(watcher) == 26 + 4  # Monday 08:00-20:30, today until 09:30
    assert [(run.started_at, run.done) for run in watcher[:2]] == [(at(3, 9, 30), 0), (at(3, 9), 1)]
    [failed] = [run for run in watcher if run.status == "error"]
    assert failed.started_at == at(2, 13) and failed.error
    plans = runs_of(company, morning_plan.KEY)
    assert [run.started_at for run in plans] == [at(3, 8, 30), at(2, 8, 30)]
    assert AIUsage.objects.filter(company=company, created_at__gte=NOW).count() == 0
    state = AgentState.objects.get(company=company, key=deadline_watcher.KEY)
    assert state.last_run_at == at(3, 9, 30)
    voice = page(owner_api, pharmacy.owner, voice_tasks.KEY).json()
    assert len(voice["calls"]) == 30 and voice["usage"]["month"]["calls"] == 2  # today: at 10:05
    called = [date.fromisoformat(day["date"]) for day in voice["usage"]["days"] if day["calls"]]
    assert len(called) == 21 and all(day.weekday() < 5 for day in called)


# Queries ----------------------------------------------------------------------------------------


def test_each_page_reads_in_a_bounded_number_of_queries(owner_api, hr_team, shop, member):
    """More runs, calls, people, tasks and documents cost no more queries."""
    client = owner_api(hr_team.owner)
    keys = [agent.key for agent in agents.all_agents()]

    def counted() -> dict[str, int]:
        found = {}
        for key in keys:
            with CaptureQueriesContext(connection) as queries:
                response = client.get(f"/api/v1/owner/companies/{shop.pk}/ai/agents/{key}/")
            assert response.status_code == 200
            found[key] = len(queries)
        return found

    CompensationFactory(membership=hr_team.ali)
    counted()  # the first read makes the agents' rows and settings
    before = counted()
    for index in range(10):
        for key in keys:
            a_run(shop, key, NOW - timedelta(hours=index + 1))
        for feature in ("task_drafts", *keys):
            usage(shop, feature, NOW - timedelta(days=index))
        person = member.registered(shop, "Manager", first_name=f"Person {index}")
        person.user.telegram_id = 9_200_000 + person.pk
        person.user.save(update_fields=["telegram_id"])
        EmployeeDocumentFactory(membership=person, expires_on=NOW.date() + timedelta(days=5))
        TaskFactory(
            company=shop,
            kind=Task.Kind.ASSIGNED,
            assignee=person,
            created_by=hr_team.owner,
            due_at=NOW + timedelta(hours=index + 1),
        )

    after = counted()

    assert after == before
    assert max(after.values()) <= 30, after
