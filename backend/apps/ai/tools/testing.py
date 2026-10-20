"""Running AI tools in tests exactly as the assistant will (permission, module, data switch,
branch scope, row cap and scrubbing included).

    result = call_tool("sales_summary", manager, start="2026-10-01", end="2026-10-20")
    assert result["data"]["net"] == "48120000.00"
    assert call_tool("sales_summary", cashier, start=..., end=...) == {"error": "not_allowed"}

Every data switch is on unless `_switches` says otherwise; `_now` and `_language` set the
context's clock and language.
"""

from datetime import datetime

from apps.ai.tools.registry import SWITCHES, ToolContext, run_tool


def call_tool(
    name: str,
    member,
    *,
    _switches=SWITCHES,
    _now: datetime | None = None,
    _language: str | None = None,
    **args,
) -> dict:
    ctx = ToolContext.for_member(member, switches=_switches, now=_now, language=_language)
    return run_tool(name, ctx, args)
