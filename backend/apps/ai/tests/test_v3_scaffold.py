"""The v0.3 pieces other work codes against (briefs/v3-contract.md): the model catalog's and the
briefing's signatures, and an agent entry that only words events (Flows) staying out of the
agent list and out of "turn AI on"."""

import inspect

import pytest

from apps.ai import briefing, catalog, queries, services
from apps.ai.agents import registry
from apps.ai.agents.registry import Agent, EventTemplate
from apps.ai.models import AgentState


def test_every_feature_has_a_model(settings):
    settings.AI_MODEL_FAST = "claude-haiku-5-5"
    settings.AI_MODEL_CHAT = "claude-sonnet-5-5"
    assert catalog.model_for(None, "flows") == "claude-haiku-5-5"
    assert catalog.model_for(None, "briefing") == "claude-sonnet-5-5"
    for feature in catalog.FEATURES:
        assert catalog.model_for(None, feature).startswith("claude-")
    with pytest.raises(ValueError):
        catalog.model_for(None, "telepathy")


def test_the_catalog_and_the_briefing_keep_their_signatures():
    model_for = inspect.signature(catalog.model_for).parameters
    assert list(model_for) == ["company", "feature"]
    build = inspect.signature(briefing.build).parameters
    assert list(build) == ["company", "membership", "period", "language"]
    assert build["period"].kind is inspect.Parameter.KEYWORD_ONLY
    assert build["language"].kind is inspect.Parameter.KEYWORD_ONLY
    with pytest.raises(ValueError):
        briefing.build(None, None, period="year")


def test_a_briefing_reads_as_plain_text():
    assert briefing.as_text(briefing.Briefing(period="today", headline="")) == ""
    result = briefing.Briefing(
        period="today",
        headline="Bugun 12 ta vazifa bajarildi",
        sections=[{"title": "Kechikkanlar", "bullets": ["3 ta vazifa kechikdi"]}],
    )
    assert briefing.as_text(result) == (
        "Bugun 12 ta vazifa bajarildi\n\nKechikkanlar\n- 3 ta vazifa kechikdi"
    )


@pytest.mark.django_db
def test_an_unlisted_agent_is_neither_listed_nor_switched_on(company, member, monkeypatch):
    words_only = Agent(
        key="words_only",
        name="Words only",
        description="",
        icon="workflow",
        needs_claude=False,
        default_enabled=True,
        fields=(),
        schedule=lambda config: "",
        events={"ran": EventTemplate("Ran")},
        listed=False,
    )
    monkeypatch.setitem(registry._agents, words_only.key, words_only)

    services.enable_ai(company, by=member(company, "Owner"))

    assert "words_only" not in [row["key"] for row in queries.agent_rows(company)]
    assert not AgentState.objects.filter(company=company, key="words_only", enabled=True).exists()
    assert {row["key"] for row in queries.agent_rows(company)} >= {"voice_tasks"}
