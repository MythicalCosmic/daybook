"""The registry and runner of the AI assistant's read-only tools (docs/PLAN-OWNER.md §8.3).

A module writes its tools in `apps/<app>/ai_tools.py`, wrapping its own `queries.py`:

    class SalesSummaryInput(BaseModel):
        start: date
        end: date

    @ai_tool("sales_summary", domain="sales", perm=Perm.SALES_VIEW, label=_("Sales summary"),
             input=SalesSummaryInput, feature="sales", switch="share_finance")
    def sales_summary(ctx: ToolContext, args: SalesSummaryInput) -> ToolResult:
        totals = queries.summary(ctx.company, args.start, args.end, branch_ids=ctx.branch_ids)
        return ToolResult(data=totals, currency=ctx.company.base_currency)

Rules: the name starts with the app's label (`sales_…`); every query uses `ctx.company` and
`ctx.branch_ids`, never ids from the model's input alone; an id from another company or
outside the scope raises `ToolNotFound`; every row carries an "id".

`tools_for(ctx)` lists the tools the asker may use (permission, module, data switch), sorted
by name so the prompt prefix stays byte-stable. `run_tool(name, ctx, raw_input)` validates
the input, re-checks the permission, runs the tool, caps rows at 50 (with `total`,
`truncated`, `as_of`, `currency`), turns Decimals into strings and scrubs every string
(apps.ai.tools.scrub). It always returns a JSON-ready dict; problems come back as
`{"error": "unknown_tool" | "not_allowed" | "invalid_input" | "not_found"}`.
"""

import importlib
import importlib.util
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from django.apps import apps as django_apps
from django.utils import timezone
from django.utils.functional import Promise
from pydantic import BaseModel, ValidationError

from apps.ai.tools.scrub import scrub_data
from apps.companies.models import Feature
from apps.members.permissions import Perm

MAX_ROWS = 50
# The data switches an owner sets in Settings → AI (AISettings): what the assistant may read.
SWITCHES = frozenset({"share_task_text", "share_finance", "share_salaries"})


@dataclass(frozen=True)
class ToolContext:
    """Who is asking and what they may see. Built from the URL's membership, never from
    anything the model says."""

    company: object
    membership: object
    branch_ids: list[int] | None
    now: datetime
    language: str
    switches: frozenset[str]

    @classmethod
    def for_member(
        cls, member, *, switches=SWITCHES, now: datetime | None = None, language=None
    ) -> ToolContext:
        from apps.members.scope import branch_ids

        return cls(
            company=member.company,
            membership=member,
            branch_ids=branch_ids(member),
            now=now or timezone.now(),
            language=language or member.user.language,
            switches=frozenset(switches),
        )


@dataclass
class ToolResult:
    """What a tool returns: `rows` (each with an "id") for lists, `data` for one record or a
    summary, or both. `total` is the number of rows before any cap (len(rows) by default)."""

    rows: list[dict] | None = None
    data: dict | None = None
    total: int | None = None
    currency: str | None = None
    as_of: datetime | None = None


class ToolNotFound(Exception):
    """Raised by a tool for an id that isn't in the asker's company or branch scope."""


class DuplicateTool(ValueError):
    pass


class ToolDefinitionError(ValueError):
    """A tool broke the rules (e.g. a row without an id). A bug, never shown to the model."""


@dataclass(frozen=True)
class AITool:
    name: str
    domain: str
    perm: Perm
    label: str | Promise
    input: type[BaseModel]
    fn: Callable[[ToolContext, BaseModel], ToolResult] = field(repr=False)
    feature: str | None = None
    switch: str | None = None

    def allowed(self, ctx: ToolContext) -> bool:
        return (
            ctx.membership.has_perm(self.perm)
            and (self.feature is None or ctx.company.has_feature(self.feature))
            and (self.switch is None or self.switch in ctx.switches)
        )

    def definition(self) -> dict:
        """The tool as the Messages API takes it (the runtime adds strictness and caching)."""
        return {
            "name": self.name,
            "description": str(self.label),
            "input_schema": self.input.model_json_schema(),
        }


_tools: dict[str, AITool] = {}
_discovered = False
_discover_lock = threading.Lock()


def ai_tool(
    name: str,
    *,
    domain: str,
    perm: Perm,
    label: str | Promise,
    input: type[BaseModel],
    feature: str | None = None,
    switch: str | None = None,
):
    """Register the decorated `(ctx, args) -> ToolResult` function as an AI tool."""

    def register(fn):
        app_label = _app_label(fn.__module__)
        if app_label is not None and not name.startswith(f"{app_label}_"):
            raise ValueError(f"Tools of apps.{app_label} are named '{app_label}_…', not {name!r}.")
        if not (isinstance(input, type) and issubclass(input, BaseModel)):
            raise TypeError(f"{name}: input must be a pydantic model class.")
        if feature is not None and feature not in Feature.values:
            raise ValueError(f"{name}: unknown module {feature!r}.")
        if switch is not None and switch not in SWITCHES:
            raise ValueError(f"{name}: unknown data switch {switch!r}.")
        if name in _tools:
            raise DuplicateTool(f"An AI tool named {name!r} is already registered.")
        _tools[name] = AITool(name, domain, Perm(perm), label, input, fn, feature, switch)
        return fn

    return register


def autodiscover() -> None:
    """Import every installed app's `ai_tools` module once, so their tools register."""
    global _discovered
    if _discovered:
        return
    with _discover_lock:
        if _discovered:
            return
        for config in django_apps.get_app_configs():
            module = f"{config.name}.ai_tools"
            if config.name.startswith("apps.") and importlib.util.find_spec(module):
                importlib.import_module(module)
        _discovered = True


def get_tool(name: str) -> AITool | None:
    autodiscover()
    return _tools.get(name)


def all_tools() -> list[AITool]:
    autodiscover()
    return sorted(_tools.values(), key=lambda tool: tool.name)


def tools_for(ctx: ToolContext) -> list[AITool]:
    """The tools `ctx`'s member may use, sorted by name."""
    return [tool for tool in all_tools() if tool.allowed(ctx)]


def run_tool(name: str, ctx: ToolContext, raw_input) -> dict:
    """Run one tool call as `ctx`'s member and return what the model may see."""
    if ctx.company.pk != ctx.membership.company_id:
        raise ValueError("The context's company must be its membership's company.")
    tool = get_tool(name)
    if tool is None:
        return {"error": "unknown_tool"}
    if not tool.allowed(ctx):
        return {"error": "not_allowed"}
    try:
        if isinstance(raw_input, str | bytes):
            args = tool.input.model_validate_json(raw_input)
        else:
            args = tool.input.model_validate(raw_input or {})
    except ValidationError as exc:
        problems = [
            {"field": ".".join(str(part) for part in error["loc"]), "problem": error["msg"]}
            for error in exc.errors()
        ]
        return scrub_data({"error": "invalid_input", "details": problems})
    try:
        result = tool.fn(ctx, args)
    except ToolNotFound:
        return {"error": "not_found"}
    if not isinstance(result, ToolResult):
        raise ToolDefinitionError(f"{name} must return a ToolResult.")
    return scrub_data(_shape(name, result, ctx))


def _shape(name: str, result: ToolResult, ctx: ToolContext) -> dict:
    out: dict = {}
    if result.rows is not None:
        rows = list(result.rows)
        for row in rows:
            if not isinstance(row, dict) or "id" not in row:
                raise ToolDefinitionError(f"Every row of {name} needs an 'id'.")
        total = result.total if result.total is not None else len(rows)
        out["rows"] = rows[:MAX_ROWS]
        out["total"] = total
        out["truncated"] = total > len(out["rows"])
    if result.data is not None:
        out["data"] = result.data
    out["as_of"] = result.as_of or ctx.now
    out["currency"] = result.currency
    return out


def _app_label(module: str) -> str | None:
    """The app label of a module: apps.sales.ai_tools -> sales (None outside apps.*)."""
    parts = module.split(".")
    return parts[1] if len(parts) > 1 and parts[0] == "apps" else None
