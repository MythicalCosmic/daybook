"""The briefing: a company's day or week in a few lines (v0.3 AI contract §3).

    result = briefing.build(company, membership, period="today", language="uz")
    text = briefing.as_text(result)      # plain text for a Telegram message ("" = nothing to say)

Numbers come from SQL (`facts`, within the reader's branches, never anyone's personal tasks);
Claude only words them (`apps.ai.writer.write_briefing`, every number checked against the facts),
and without Claude a template words the same facts. Used by the dashboard's AI overview and by
Flows (the "AI summarizes" step). The v0.3 scaffold ships the final signatures with an empty
result; the briefing work fills them in.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from django.utils import timezone

Period = Literal["today", "week"]
PERIODS: tuple[str, ...] = ("today", "week")


@dataclass(frozen=True)
class Briefing:
    period: str
    headline: str
    # [{"title": str, "bullets": [str]}]
    sections: list[dict] = field(default_factory=list)
    # [{"label": str, "url": "<dashboard path>"}]
    actions: list[dict] = field(default_factory=list)
    facts: dict = field(default_factory=dict)
    engine: str = "template"  # "claude" | "template" | "fake"
    model: str = ""
    generated_at: datetime | None = None


def build(
    company, membership, *, period: Period = "today", language: str | None = None
) -> Briefing:
    """The briefing of `period` as `membership` may see it (their branches), in `language`
    (the reader's when None). Never raises for a valid period; an empty headline means there
    is nothing to say."""
    if period not in PERIODS:
        raise ValueError(f"Unknown briefing period {period!r}.")
    return Briefing(period=period, headline="", generated_at=timezone.now())


def as_text(result: Briefing) -> str:
    """The briefing as a short plain-text message: the headline, then each section's bullets."""
    if not result.headline:
        return ""
    lines = [result.headline]
    for section in result.sections:
        lines.append("")
        lines.append(str(section.get("title", "")))
        lines.extend(f"- {bullet}" for bullet in section.get("bullets", []))
    return "\n".join(lines).strip()
