"""Maslahatchi, the advisor agent (apps.ai.agents.advisor): registered like the others with its
page, and "Ask the advisor", an Ask AI conversation on the fast model at low effort with the
read-only money and people tools plus its own two."""

import json

import pytest
from django.conf import settings

from apps.ai import agents, chat
from apps.ai.agents import advisor
from apps.ai.models import AIMessage, AITurn, AIUsage

from .conftest import NOW

pytestmark = pytest.mark.django_db


def test_maslahatchi_is_an_agent_with_its_own_page(ledger, people, pharmacy, owner_api, ai_on):
    ai_on()
    agent = agents.get("advisor")

    assert agents.all_agents()[0] is agent
    assert (agent.needs_claude, agent.default_enabled, agent.icon) == (False, True, "trending-up")
    assert agent.usage_features == ("advisor", "advisor_chat")
    assert [str(prompt.label) for prompt in agent.prompts] == [
        "The business review",
        "Ask the advisor",
    ]
    page = owner_api(people.owner).get(f"/api/v1/owner/companies/{pharmacy.pk}/ai/agents/advisor/")
    assert page.status_code == 200
    body = page.json()
    assert body["name"] == "Advisor" and body["enabled"] is True
    labels = [item["label"] for item in body["upcoming"]]
    assert "Weekly business review" in labels and "Monthly business review" in labels
    assert body["prompts"][0]["text"] == advisor.REVIEW_SYSTEM


def test_it_works_where_there_is_something_to_review(company):
    assert not advisor.AGENT.works_in(company)
    company.features = ["attendance"]
    assert advisor.AGENT.works_in(company)


def tool_use(name, tool_input, tool_id):
    return {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}


def test_ask_the_advisor_with_claude(
    ledger, people, pharmacy, ai_on, fake_claude, django_capture_on_commit_callbacks
):
    ai_on()
    owner = people.owner
    conversation = chat.start_conversation(owner, agent=chat.ADVISOR)
    fake_claude.script(
        fake_claude.message(
            [
                tool_use(
                    "briefings_advisor_scenario",
                    {"monthly_change": -30_000_000, "label": "second pharmacy"},
                    "toolu_1",
                ),
                tool_use("finance_summary", {}, "toolu_2"),
            ],
            stop_reason="tool_use",
            model="claude-haiku-5-5",
        ),
        fake_claude.text("**Yes, but only just.**", model="claude-haiku-5-5"),
    )
    with django_capture_on_commit_callbacks():
        turn = chat.start_turn(conversation, by=owner, text="Ikkinchi filialga pulim yetadimi?")

    chat.run_turn(turn.pk)

    turn.refresh_from_db()
    assert turn.status == AITurn.Status.DONE and turn.text == "**Yes, but only just.**"
    first, second = fake_claude.requests
    assert first["model"] == settings.AI_MODEL_FAST
    assert first["output_config"]["effort"] == "low"
    assert "temperature" not in first and "tool_choice" not in first
    names = [tool["name"] for tool in first["tools"]]
    assert names == sorted(names)
    assert {"briefings_advisor_facts", "briefings_advisor_scenario", "finance_summary"} <= set(
        names
    )
    assert not any(name.startswith(("tasks_", "learning_", "knowledge_")) for name in names)
    assert advisor.CHAT_SYSTEM in first["system"][0]["text"]
    results = second["messages"][-1]
    assert results["role"] == "user"
    assert [block["tool_use_id"] for block in results["content"]] == ["toolu_1", "toolu_2"]
    scenario = json.loads(results["content"][0]["content"])
    assert scenario["data"]["change"]["monthly"] == "-30000000.00"
    assert set(AIUsage.objects.values_list("feature", flat=True)) == {"advisor_chat"}
    assert AIMessage.objects.filter(conversation=conversation).count() == 4


def test_a_bad_tool_input_comes_back_as_an_error(
    ledger, people, pharmacy, ai_on, fake_claude, django_capture_on_commit_callbacks
):
    ai_on()
    owner = people.owner
    conversation = chat.start_conversation(owner, agent=chat.ADVISOR)
    fake_claude.script(
        fake_claude.message(
            [tool_use("briefings_advisor_scenario", {"monthly_change": "a lot"}, "toolu_9")],
            stop_reason="tool_use",
            model="claude-haiku-5-5",
        ),
        fake_claude.text("I need an amount.", model="claude-haiku-5-5"),
    )
    with django_capture_on_commit_callbacks():
        turn = chat.start_turn(conversation, by=owner, text="What if?")

    chat.run_turn(turn.pk)

    [result] = fake_claude.requests[1]["messages"][-1]["content"]
    assert result["is_error"] is True
    assert json.loads(result["content"])["error"] == "invalid_input"


def test_without_claude_the_advisor_answers_from_its_tools(
    ledger, people, pharmacy, ai_on, settings, django_capture_on_commit_callbacks
):
    settings.AI_FAKE = True
    ai_on()
    from apps.briefings import reviews

    reviews.tick(NOW)
    owner = people.owner
    conversation = chat.start_conversation(owner, agent=chat.ADVISOR)
    with django_capture_on_commit_callbacks():
        turn = chat.start_turn(conversation, by=owner, text="Ikkinchi filial ochsam nima bo‘ladi?")

    chat.run_turn(turn.pk)

    turn.refresh_from_db()
    assert turn.status == AITurn.Status.DONE
    assert "One more pharmacy that costs about" in turn.text
    assert [step["status"] for step in turn.steps] == ["done", "done"]


def test_the_advisor_chat_needs_maslahatchi(ledger, people, pharmacy, ai_on, settings):
    settings.AI_FAKE = True
    ai_on(advisor=False)

    with pytest.raises(chat.TurnRefused):
        chat.start_conversation(people.owner, agent=chat.ADVISOR)
    assert chat.start_conversation(people.owner).agent == ""
