"""The words of a review: the template without AI, and Claude's draft kept only where it cites
a signal of the facts and says only their numbers (the fake client)."""

from decimal import Decimal

import pytest
from django.conf import settings

from apps.ai.models import AIUsage
from apps.briefings import facts, numbers, periods, reviews, scope, signals, writing
from apps.briefings.models import Briefing

from .conftest import MONDAY, NOW

pytestmark = pytest.mark.django_db


@pytest.fixture
def review_facts(ledger, people):
    owner = people.owner
    return facts.build(
        owner.company, periods.latest("weekly", MONDAY), scope.of(owner), today=MONDAY
    )


def test_the_template_writes_a_whole_review_without_ai(review_facts):
    content = writing.template(review_facts, "en")

    found = signals.by_key(review_facts)
    assert content["headline"].startswith("Week of 9–15")
    assert "20\u00a0mln\u00a0UZS" in content["headline"] and "11.1%" in content["headline"]
    sections = {section["key"]: section for section in content["sections"]}
    assert set(sections) == {"went_well", "went_wrong"}
    wrong = sections["went_wrong"]
    assert wrong["title"] == "What went wrong"
    assert len(wrong["bullets"]) == len(wrong["facts"]) >= 2
    assert all(found[key]["tone"] == signals.BAD for key in wrong["facts"])
    assert any("Transport" in bullet for bullet in wrong["bullets"])
    assert any("Yunusobod" in bullet for bullet in wrong["bullets"])
    assert 1 <= len(content["actions"]) <= 3
    for action in content["actions"]:
        assert action["fact"] in found
        assert action["url"] == found[action["fact"]]["url"]
        assert action["label"] and action["text"]


def test_the_template_says_only_numbers_of_the_facts(review_facts):
    known = numbers.known_numbers(review_facts)
    for language in ("en", "uz", "ru"):
        content = writing.template(review_facts, language)
        texts = [content["headline"], *(a["text"] for a in content["actions"])]
        texts += [bullet for section in content["sections"] for bullet in section["bullets"]]
        for text in texts:
            assert numbers.numbers_ok(text, known), (language, text, numbers.unknown(text, known))


def test_the_bot_text_is_plain(review_facts):
    content = writing.template(review_facts, "en")
    text = writing.bot_text(content, "en", "weekly")

    assert text.startswith(content["headline"])
    assert "What went wrong" in text and "What to do this week" in text
    assert "1. " in text
    assert not any(mark in text for mark in ("→", "✓", "<", ">", "**"))
    assert writing.title(review_facts, "en") == "Weekly business review: 9–15 November"


def draft(review_facts, **changes):
    found = signals.by_key(review_facts)
    margin = next(key for key in found if key.endswith(":margin"))
    jump = next(key for key in found if key.startswith("expense:"))
    body = {
        "headline": "Sales grew 11.1% to 20 mln UZS, but Yunusobod's margin fell.",
        "went_well": [{"text": "Revenue reached 20 mln UZS.", "fact": "revenue"}],
        "went_wrong": [
            {"text": "Yunusobod's gross margin fell to 30% from 40%.", "fact": margin},
            {"text": f"Transport cost {invented(review_facts)} mln UZS.", "fact": jump},
            {"text": "Revenue fell.", "fact": "revenue"},  # a good signal under "wrong"
        ],
        "suggestions": [
            {"text": "Compare Yunusobod's purchase prices with Chilonzor's.", "fact": margin},
            {"text": "Ask the drivers about 2.5 mln UZS of transport.", "fact": jump},
            {"text": "Open a third pharmacy.", "fact": "branch:999:margin"},  # no such signal
        ],
    }
    return body | changes


def test_claudes_draft_keeps_only_what_holds(review_facts):
    content, kept = writing.checked(draft(review_facts), review_facts, "en")

    assert kept
    assert content["headline"].startswith("Sales grew 11.1%")
    sections = {section["key"]: section for section in content["sections"]}
    assert sections["went_well"]["bullets"] == ["Revenue reached 20 mln UZS."]
    assert sections["went_wrong"]["bullets"] == ["Yunusobod's gross margin fell to 30% from 40%."]
    texts = [action["text"] for action in content["actions"]]
    assert texts[:2] == [
        "Compare Yunusobod's purchase prices with Chilonzor's.",
        "Ask the drivers about 2.5 mln UZS of transport.",
    ]
    assert "Open a third pharmacy." not in texts
    assert len(content["actions"]) == 2  # one per bad signal: there are two this week


def invented(review_facts) -> int:
    """A number that is no fact, in no form."""
    known = numbers.known_numbers(review_facts)
    return next(value for value in range(57, 1000) if Decimal(value) not in known)


def test_a_suggestion_that_falls_out_is_filled_from_the_template(review_facts):
    body = draft(review_facts)
    body["suggestions"] = [
        body["suggestions"][0],
        {
            "text": f"Cut transport by {invented(review_facts)} mln UZS.",
            "fact": body["suggestions"][1]["fact"],
        },
    ]

    content, kept = writing.checked(body, review_facts, "en")

    assert kept
    template = writing.template(review_facts, "en")
    jump = body["suggestions"][1]["fact"]
    texts = {action["fact"]: action["text"] for action in content["actions"]}
    assert texts[body["suggestions"][0]["fact"]] == body["suggestions"][0]["text"]
    assert texts[jump] == next(a["text"] for a in template["actions"] if a["fact"] == jump)


def test_a_headline_with_an_invented_number_gives_way_to_the_template(review_facts):
    headline = f"Revenue jumped {invented(review_facts)}% this week."
    content, _kept = writing.checked(draft(review_facts, headline=headline), review_facts, "en")

    assert content["headline"] == writing.template(review_facts, "en")["headline"]


def test_a_draft_with_nothing_that_holds_is_not_claudes(review_facts):
    content, kept = writing.checked(
        {"headline": "Up 1000%.", "went_well": [], "went_wrong": [], "suggestions": []},
        review_facts,
        "en",
    )

    assert not kept
    assert content == writing.template(review_facts, "en")


def test_the_advisor_writes_the_review_with_claude(ledger, people, pharmacy, ai_on, fake_claude):
    state = ai_on()
    fake_claude.script(fake_claude.json(draft_for(pharmacy, people), model="claude-haiku-5-5"))

    from apps.ai.agents import advisor

    state.forced = False
    sent = advisor.run(pharmacy, state, NOW)

    review = Briefing.objects.get()
    assert sent == 1
    assert review.written_by == Briefing.WrittenBy.AI
    assert review.model == "claude-haiku-5-5"
    wrong = next(s for s in review.content["sections"] if s["key"] == "went_wrong")
    assert wrong["bullets"] == ["Yunusobod's gross margin fell to 30% from 40%."]
    [request] = fake_claude.requests
    assert request["model"] == settings.AI_MODEL_FAST
    assert request["output_config"]["effort"] == "low"
    assert request["max_tokens"] == advisor.MAX_TOKENS
    assert "temperature" not in request and "fallbacks" not in request
    assert "<facts>" in request["messages"][0]["content"][0]["text"]
    assert '"url"' not in request["messages"][0]["content"][0]["text"]
    usage = AIUsage.objects.get()
    assert usage.feature == advisor.KEY


def draft_for(pharmacy, people):
    owner = people.owner
    found = facts.build(pharmacy, periods.latest("weekly", MONDAY), scope.of(owner), today=MONDAY)
    return draft(found)


def test_a_refusal_falls_back_to_the_template(ledger, people, pharmacy, ai_on, fake_claude):
    state = ai_on()
    fake_claude.script(fake_claude.refusal(model="claude-haiku-5-5"))

    from apps.ai.agents import advisor

    state.forced = False
    advisor.run(pharmacy, state, NOW)

    review = Briefing.objects.get()
    assert review.written_by == Briefing.WrittenBy.TEMPLATE
    assert review.content == writing.template(review.facts, review.language)


def test_without_claude_the_template_writes_it(ledger, people, pharmacy, ai_on, settings):
    settings.ANTHROPIC_API_KEY = ""
    state = ai_on()

    from apps.ai.agents import advisor

    state.forced = False
    advisor.run(pharmacy, state, NOW)

    assert Briefing.objects.get().written_by == Briefing.WrittenBy.TEMPLATE
    assert reviews.claude_writes(pharmacy) is False


def test_numbers_are_read_as_people_write_them():
    found = numbers.numbers_in("48 120 000 so‘m, 48,1 mln, 4.2%, 1,250,000.50 UZS, 23-noyabr")

    assert found == [
        Decimal("48120000"),
        Decimal("48.1"),
        Decimal("4.2"),
        Decimal("1250000.50"),
        Decimal("23"),
    ]
    known = numbers.known_numbers({"value": "48120000.00", "date": "2026-11-23", "id": 77})
    assert numbers.numbers_ok("48,1 mln so‘m, 23.11", known)
    assert not numbers.numbers_ok("77 ta", known)  # an id is no fact
    assert not numbers.numbers_ok("49 mln", known)
