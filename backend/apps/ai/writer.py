"""Turning computed facts into short texts: briefings and insight explanations (§8.5).

Briefings and insights (package N) compute every number in SQL and hand them over as `facts`;
the writer only words them. It returns None whenever AI is unavailable, the budget is spent,
the model refuses, or a number in the text doesn't match the facts, and the caller then uses
its gettext template. Until package K builds it, it always returns None.

The result shapes are fixed here, so N codes against them now.
"""

from typing import Literal

from pydantic import BaseModel, Field

BriefingKind = Literal["morning", "evening", "weekly", "monthly"]


class BriefingSection(BaseModel):
    title: str = Field(max_length=80)
    bullets: list[str] = Field(max_length=8)


class BriefingAction(BaseModel):
    label: str = Field(max_length=40)
    url: str = Field(max_length=300, description="A dashboard path, e.g. /c/12/sales")


class BriefingContent(BaseModel):
    """`Briefing.content`: a headline, a few sections of bullets and up to three actions."""

    headline: str = Field(max_length=160)
    sections: list[BriefingSection] = Field(max_length=6)
    actions: list[BriefingAction] = Field(default_factory=list, max_length=3)


class InsightText(BaseModel):
    """The words of an insight: what happened, why it matters, and what to do."""

    title: str = Field(max_length=120)
    explanation: str = Field(max_length=600)
    suggested_action: str = Field(max_length=200)


def write_briefing(facts: dict, *, kind: BriefingKind, language: str) -> BriefingContent | None:
    """Word a briefing of `kind` in `language` from `facts` (the only source of numbers)."""
    return None


def explain_insight(facts: dict, *, language: str) -> InsightText | None:
    """Explain one insight in `language` from its `facts`."""
    return None
