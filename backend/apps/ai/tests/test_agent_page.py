"""An agent's own page (v5): the run log the runner keeps (`AgentRun`), GET ai/agents/<key>/
(its runs, its Claude calls, its token use, what comes next and its scene) and each agent's
`upcoming` hook.

The reference moment is Tuesday 3 November 2026, 10:00 in Tashkent (UTC+5); the pharmacy
works Monday to Friday.
"""

import dataclasses
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from apps.ai import agents
from apps.ai.agents import deadline_watcher, morning_plan, registry
from apps.ai.models import AgentRun, AIUsage
from apps.members.models import AccessRole
from apps.members.permissions import Perm

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
