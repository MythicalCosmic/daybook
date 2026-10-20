"""The AI tool registry and runner: what any module's tool goes through (§8.3)."""

import json
from datetime import date, datetime
from decimal import Decimal

import pytest
from pydantic import BaseModel

from apps.ai.tools import registry
from apps.ai.tools.registry import ToolContext, ToolNotFound, ToolResult, ai_tool, run_tool
from apps.ai.tools.scrub import HIDDEN, scrub, scrub_data
from apps.ai.tools.testing import call_tool
from apps.companies.tests.factories import BranchFactory
from apps.members.permissions import Perm
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def empty_registry(monkeypatch):
    monkeypatch.setattr(registry, "_tools", {})
    monkeypatch.setattr(registry, "_discovered", True)


class NoInput(BaseModel):
    pass


class TaskInput(BaseModel):
    task_id: int


def register_examples():
    @ai_tool("ai_people", domain="people", perm=Perm.MEMBERS_VIEW, label="People", input=NoInput)
    def people(ctx, args):
        return ToolResult(
            rows=[
                {
                    "id": member.pk,
                    "name": member.full_name,
                    "phone": member.user.phone,
                    "telegram_id": member.user.telegram_id,
                    "note": "Call me at +998 90 123 45 67 or @aziz_k, t.me/aziz",
                }
                for member in ctx.membership.company.memberships.order_by("pk")
            ]
        )

    @ai_tool(
        "ai_money",
        domain="finance",
        perm=Perm.REPORTS_VIEW,
        label="Money",
        input=NoInput,
        feature="finance",
        switch="share_finance",
    )
    def money(ctx, args):
        return ToolResult(
            data={"net": Decimal("5200000000.00"), "day": date(2026, 10, 20)}, currency="UZS"
        )

    @ai_tool("ai_task", domain="tasks", perm=Perm.TASKS_VIEW_ALL, label="Task", input=TaskInput)
    def task(ctx, args):
        found = Task.objects.for_company(ctx.company).filter(pk=args.task_id).first()
        if found is None or (ctx.branch_ids is not None and found.branch_id not in ctx.branch_ids):
            raise ToolNotFound
        return ToolResult(data={"id": found.pk, "title": found.title})

    @ai_tool("ai_many", domain="tasks", perm=Perm.MEMBERS_VIEW, label="Many", input=NoInput)
    def many(ctx, args):
        return ToolResult(rows=[{"id": n, "n": n} for n in range(120)])


@pytest.fixture
def manager(company, member):
    return member.registered(company, "Manager")


@pytest.fixture
def owner(company, member):
    return member.registered(company, "Owner")


def test_results_are_capped_scrubbed_and_json_ready(company, manager, member):
    register_examples()
    member.registered(company, user__phone="+998901234567")

    result = call_tool("ai_people", manager, _now=datetime(2026, 10, 20, 9, 0))

    json.dumps(result)  # nothing the API can't send
    assert result["total"] == len(result["rows"])
    assert result["truncated"] is False
    assert result["as_of"] == "2026-10-20T09:00:00"
    assert result["currency"] is None
    row = result["rows"][0]
    assert "phone" not in row and "telegram_id" not in row
    assert row["note"] == f"Call me at {HIDDEN} or {HIDDEN}, {HIDDEN}"
    assert "998" not in json.dumps(result)


def test_rows_are_capped_at_fifty(company, manager):
    register_examples()

    result = call_tool("ai_many", manager)

    assert len(result["rows"]) == registry.MAX_ROWS
    assert result["total"] == 120
    assert result["truncated"] is True


def test_money_stays_exact_and_is_not_mistaken_for_an_id(company, owner):
    register_examples()
    company.features = ["finance"]
    company.save()

    result = call_tool("ai_money", owner)

    assert result["data"] == {"net": "5200000000.00", "day": "2026-10-20"}
    assert result["currency"] == "UZS"


def test_tools_are_offered_only_with_permission_module_and_switch(company, manager, owner):
    register_examples()
    worker_ctx = ToolContext.for_member(manager)

    assert [tool.name for tool in registry.tools_for(worker_ctx)] == [
        "ai_many",
        "ai_people",
        "ai_task",
    ]  # no finance module yet
    company.features = ["finance"]
    company.save()
    owner.company.refresh_from_db()
    assert "ai_money" in [t.name for t in registry.tools_for(ToolContext.for_member(owner))]
    without_switch = ToolContext.for_member(owner, switches=frozenset())
    assert "ai_money" not in [t.name for t in registry.tools_for(without_switch)]
    assert call_tool("ai_money", owner, _switches=frozenset()) == {"error": "not_allowed"}


def test_permission_is_checked_again_when_running(company, member):
    register_examples()
    worker = member.registered(company)

    assert call_tool("ai_people", worker) == {"error": "not_allowed"}


def test_ids_from_another_company_or_branch_are_not_found(company, other_company, member):
    register_examples()
    here = company.branches.get()
    there = BranchFactory(company=company)
    lead_role = company.accessroles.create(name="Lead", permissions=[Perm.TASKS_VIEW_ALL])
    lead = member.registered(company, "Lead")
    lead.branches.set([here])
    assert lead.role == lead_role
    owner = member.registered(company, "Owner")
    mine = TaskFactory(assignee=owner, created_by=owner, branch=here)
    elsewhere = TaskFactory(assignee=owner, created_by=owner, branch=there)
    foreign = TaskFactory(assignee=member.registered(other_company))

    assert call_tool("ai_task", lead, task_id=mine.pk)["data"]["id"] == mine.pk
    assert call_tool("ai_task", lead, task_id=elsewhere.pk) == {"error": "not_found"}
    assert call_tool("ai_task", lead, task_id=foreign.pk) == {"error": "not_found"}


def test_invalid_input_comes_back_as_an_error(company, manager):
    register_examples()
    ctx = ToolContext.for_member(manager)

    result = run_tool("ai_task", ctx, {"task_id": "not a number"})
    from_json = run_tool("ai_task", ctx, '{"task_id": "x"}')

    assert result["error"] == "invalid_input"
    assert result["details"][0]["field"] == "task_id"
    assert from_json["error"] == "invalid_input"
    assert run_tool("ai_nothing", ctx, {}) == {"error": "unknown_tool"}


def test_tools_must_return_rows_with_ids(company, manager):
    @ai_tool("ai_bad", domain="x", perm=Perm.MEMBERS_VIEW, label="Bad", input=NoInput)
    def bad(ctx, args):
        return ToolResult(rows=[{"name": "no id"}])

    @ai_tool("ai_worse", domain="x", perm=Perm.MEMBERS_VIEW, label="Worse", input=NoInput)
    def worse(ctx, args):
        return {"rows": []}

    with pytest.raises(registry.ToolDefinitionError):
        call_tool("ai_bad", manager)
    with pytest.raises(registry.ToolDefinitionError):
        call_tool("ai_worse", manager)


def test_registration_rules():
    def tool(ctx, args):
        return ToolResult()

    ai_tool("ai_one", domain="x", perm=Perm.MEMBERS_VIEW, label="One", input=NoInput)(tool)
    with pytest.raises(registry.DuplicateTool):
        ai_tool("ai_one", domain="x", perm=Perm.MEMBERS_VIEW, label="One", input=NoInput)(tool)
    with pytest.raises(ValueError, match="named 'ai_"):
        ai_tool("sales_one", domain="x", perm=Perm.MEMBERS_VIEW, label="x", input=NoInput)(tool)
    with pytest.raises(TypeError):
        ai_tool("ai_two", domain="x", perm=Perm.MEMBERS_VIEW, label="x", input=dict)(tool)
    with pytest.raises(ValueError, match="module"):
        ai_tool(
            "ai_three", domain="x", perm=Perm.MEMBERS_VIEW, label="x", input=NoInput, feature="z"
        )(tool)
    with pytest.raises(ValueError, match="switch"):
        ai_tool(
            "ai_four", domain="x", perm=Perm.MEMBERS_VIEW, label="x", input=NoInput, switch="z"
        )(tool)
    with pytest.raises(ValueError):
        ai_tool("ai_five", domain="x", perm="no.such", label="x", input=NoInput)(tool)


def test_definitions_for_the_api_are_sorted_and_stable(company, manager):
    register_examples()

    names = [
        tool.definition()["name"] for tool in registry.tools_for(ToolContext.for_member(manager))
    ]

    assert names == sorted(names)
    assert registry.get_tool("ai_task").definition()["input_schema"]["required"] == ["task_id"]


def test_the_context_belongs_to_one_company(company, other_company, manager):
    register_examples()
    ctx = ToolContext.for_member(manager)
    wrong = ToolContext(other_company, manager, None, ctx.now, "en", frozenset())

    with pytest.raises(ValueError):
        run_tool("ai_people", wrong, {})


def test_every_installed_tool_follows_the_rules(monkeypatch):
    from django.apps import apps

    monkeypatch.setattr(registry, "_discovered", False)

    tools = registry.all_tools()  # imports every app's ai_tools module

    labels = {config.label for config in apps.get_app_configs()}
    assert all(tool.name.split("_")[0] in labels for tool in tools)
    assert [tool.name for tool in tools] == sorted(tool.name for tool in tools)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("+998 90 123 45 67", HIDDEN),
        ("998901234567", HIDDEN),
        ("90 123 45 67", HIDDEN),
        ("(90) 123-45-67", HIDDEN),
        ("call 901234567 now", f"call {HIDDEN} now"),
        ("card 8600 1234 5678 9012", f"card {HIDDEN}"),
        ("card 8600123456789012", f"card {HIDDEN}"),
        ("tg id 6589960007", f"tg id {HIDDEN}"),
        ("ask @dilnoza_k please", f"ask {HIDDEN} please"),
        ("mail ali@example.com", "mail ali@example.com"),
        ("https://t.me/joinchat/abc and t.me/aziz", f"{HIDDEN} and {HIDDEN}"),
        ("tg://user?id=123", HIDDEN),
        (
            "Sold 12 500 000 so'm on 2026-10-20 at 10:20",
            "Sold 12 500 000 so'm on 2026-10-20 at 10:20",
        ),
        ("Fridge check #345", "Fridge check #345"),
        # Amounts a tool already wrote as money strings stay whole.
        ("350000000.00", "350000000.00"),
        ("-5200000000.50", "-5200000000.50"),
        ("total 350000000.00", f"total {HIDDEN}.00"),
        ("901234567", HIDDEN),
    ],
)
def test_scrubbing(text, expected):
    assert scrub(text) == expected


def test_scrub_data_walks_everything():
    data = {
        "rows": [{"id": 1, "Phone": "+998901234567", "text": "@someone"}],
        "total": Decimal("10.50"),
        "flag": True,
        "when": datetime(2026, 10, 20, 9, 30),
        "tags": ("a", "998901234567"),
    }

    assert scrub_data(data) == {
        "rows": [{"id": 1, "text": HIDDEN}],
        "total": "10.50",
        "flag": True,
        "when": "2026-10-20T09:30:00",
        "tags": ["a", HIDDEN],
    }
