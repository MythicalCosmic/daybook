"""The Claude client and the Claude path of task drafts, with the scripted fake (§8.2, §8.9)."""

import json
import re

import pytest
from pydantic import BaseModel

from apps.ai import availability, client, drafting
from apps.ai.models import AIDraft, AIUsage

pytestmark = pytest.mark.django_db


class Answer(BaseModel):
    word: str


def ask(company, **kwargs):
    kwargs.setdefault("model", "claude-opus-5-5")
    return client.structured(
        "test", company=company, schema=Answer, system="Say a word.", user="Hi", **kwargs
    )


def test_a_structured_call_follows_the_request_rules(company, fake_claude):
    fake_claude.script(fake_claude.json({"word": "salom"}, input_tokens=1000, output_tokens=200))

    result, call = ask(company)

    assert result.word == "salom"
    [request] = fake_claude.requests
    assert request["output_config"]["effort"] == "low"
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert request["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert request["fallbacks"] == "default"
    assert request["betas"] == ["server-side-fallback-2026-07-01"]
    for banned in ("temperature", "top_p", "top_k", "thinking", "tool_choice"):
        assert banned not in request
    assert request["max_tokens"] <= 16_000
    usage = AIUsage.objects.get()
    assert (usage.model, usage.input_tokens, usage.output_tokens) == ("claude-opus-5-5", 1000, 200)
    assert usage.cost_micro_usd == 1000 * 4 + 200 * 20
    assert usage.request_id.startswith("req_fake_")
    assert call.cost_micro_usd == usage.cost_micro_usd


def test_haiku_never_sends_fallbacks(company, fake_claude):
    fake_claude.script(fake_claude.json({"word": "x"}, model="claude-haiku-5-5"))

    ask(company, model="claude-haiku-5-5")

    [request] = fake_claude.requests
    assert "fallbacks" not in request and "betas" not in request


def test_a_fallback_is_priced_by_each_model_that_ran(company, fake_claude):
    iterations = [
        {
            "type": "message",
            "model": "claude-opus-5-5",
            "input_tokens": 1000,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
        {
            "type": "fallback_message",
            "model": "claude-opus-4-8",
            "input_tokens": 1000,
            "output_tokens": 100,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    ]
    fake_claude.script(
        fake_claude.json({"word": "x"}, model="claude-opus-4-8", iterations=iterations)
    )

    ask(company)

    usage = AIUsage.objects.get()
    assert usage.model == "claude-opus-4-8"
    assert usage.cost_micro_usd == 1000 * 4 + (1000 * 5 + 100 * 25)


def test_a_refusal_is_recorded_and_raised(company, fake_claude):
    fake_claude.script(fake_claude.refusal("bio"))

    with pytest.raises(client.Refused):
        ask(company)

    assert AIUsage.objects.get().stop_reason == "refusal"


def test_a_cut_answer_is_not_read(company, fake_claude):
    fake_claude.script(fake_claude.truncated())

    with pytest.raises(client.Truncated):
        ask(company)


def test_an_answer_off_the_schema_is_invalid(company, fake_claude):
    fake_claude.script(fake_claude.text('{"other": 1}'))

    with pytest.raises(client.InvalidOutput):
        ask(company)


def test_failures_open_the_breaker(company, ai_on, fake_claude):
    ai_on(company)
    fake_claude.script(*[fake_claude.status_error(529) for _ in range(4)])
    fake_claude.script(fake_claude.connection_error())

    for _ in range(5):
        with pytest.raises(client.Unavailable):
            ask(company)

    assert availability.breaker_open()
    assert availability.status(company).state == "unavailable"
    availability.reset_breaker()


def test_without_a_key_nothing_is_called(company):
    with pytest.raises(client.Unavailable):
        ask(company)


def test_the_month_spend_stops_claude(company, ai_on, fake_claude):
    from apps.ai import conf

    ai_on(company)
    row = conf.get_settings(company)
    row.monthly_budget_usd = "0.01"
    row.save()
    fake_claude.script(fake_claude.json({"word": "x"}, input_tokens=5000, output_tokens=0))

    ask(company)

    status = availability.status(company)
    assert status.state == "budget_reached"
    assert status.resets_on.day == 1


# The Claude path of task drafts -----------------------------------------------------------------

PHONE = re.compile(r"\+?998[\s\-]?\d{2}|\b9\d[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}\b")


@pytest.fixture
def people(company, member, ai_on):
    ai_on(company)
    manager = member.registered(
        company, "Manager", first_name="Bekzod", last_name="Mirzayev", user__username="bekzod_m"
    )
    alisher = member.registered(
        company, first_name="Alisher", last_name="Valiyev", user__telegram_id=7_771_234_567
    )
    return {"manager": manager, "alisher": alisher}


def claude_drafts(people, fake_claude, answer, text="Alisher, ertaga 10 gacha kassani sana"):
    fake_claude.script(fake_claude.json(answer))
    return drafting.understand(people["manager"], text, language="uz")


def test_claude_reads_the_instruction_against_the_candidates(people, fake_claude):
    found = claude_drafts(
        people,
        fake_claude,
        {
            "drafts": [
                {
                    "title": "Muzlatgich haroratini tekshirish",
                    "description": "",
                    "assignee_id": people["alisher"].pk,
                    "assignee_heard": "",
                    "due": "2030-01-02T10:00",
                    "priority": "normal",
                    "checklist": [],
                    "proof": "photo",
                },
                {
                    "title": "Kassani sanash",
                    "description": "",
                    "assignee_id": 999999,
                    "assignee_heard": "Nodir",
                    "due": None,
                    "priority": "urgent",
                    "checklist": ["Naqd", "Karta"],
                    "proof": "none",
                },
            ],
            "questions": ["Kassani qaysi filialda?"],
        },
    )

    assert found.engine == AIDraft.Engine.CLAUDE
    fridge, cash = found.drafts
    assert fridge["assignee_id"] == people["alisher"].pk
    assert fridge["due_at"] == "2030-01-02T10:00:00+05:00"
    assert cash["assignee_id"] is None  # an id nobody offered is dropped
    assert cash["assignee_guess"] == "Nodir"
    assert cash["problems"] == ["no_assignee_match"]
    assert cash["checklist"] == ["Naqd", "Karta"]
    assert found.questions == ["Kassani qaysi filialda?"]
    [request] = fake_claude.requests
    assert request["model"] == "claude-opus-5-5"
    assert request["output_config"]["effort"] == "low"
    prompt = request["messages"][0]["content"][0]["text"]
    assert "Asia/Tashkent" in prompt or "<today>" in prompt
    candidates = json.loads(prompt.split("<candidates>")[1].split("</candidates>")[0])
    assert {c["id"] for c in candidates} == {people["manager"].pk, people["alisher"].pk}


def test_no_phone_numbers_telegram_ids_or_usernames_reach_claude(people, fake_claude):
    claude_drafts(
        people,
        fake_claude,
        {"drafts": [], "questions": []},
        text="Alisher, +998 90 123 45 67 ga qo‘ng‘iroq qil, @bekzod_m ga yoz, t.me/x",
    )

    body = json.dumps(fake_claude.requests, ensure_ascii=False, default=str)
    assert not PHONE.search(body)
    assert "7771234567" not in body
    assert "@bekzod_m" not in body and "bekzod_m" not in body
    assert "t.me" not in body


def test_when_claude_fails_the_rules_answer(people, fake_claude):
    fake_claude.script(fake_claude.refusal("cyber"))

    found = drafting.understand(
        people["manager"], "Alisher, ertaga soat 10 da kassani sana.", language="uz"
    )

    assert found.engine == AIDraft.Engine.RULES
    assert found.drafts[0]["assignee_id"] == people["alisher"].pk


def test_with_fake_ai_claude_is_never_called(people, fake_claude, settings):
    settings.AI_FAKE = True

    found = drafting.understand(people["manager"], "Alisher, kassani sana.", language="uz")

    assert found.engine == AIDraft.Engine.FAKE
    assert fake_claude.requests == []


def test_someone_who_cannot_give_work_offers_only_themselves(people):
    candidates = drafting.candidates(people["alisher"])

    assert [c.id for c in candidates] == [people["alisher"].pk]
    assert candidates[0].is_author
