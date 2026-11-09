"""Writing questions from a page or a lesson (docs/PLAN-LEARNING.md §6): the rules engine on a
pharmacy text (numbers, steps, terms), the Claude path with its number check, the fallback."""

from types import SimpleNamespace

import pytest
from django.conf import settings

from apps.knowledge import sanitize
from apps.knowledge.demo import COLD_CHAIN, RECEIVING
from apps.knowledge.tests.factories import PageFactory, SpaceFactory
from apps.learning import drafting
from apps.learning.models import Question, QuestionDraftJob
from apps.learning.tests.q2.fixtures import ai_on, topic

pytestmark = pytest.mark.django_db

TERMS = """<p>XPN – ta’sir etuvchi moddaning xalqaro nomi</p>
<p>Defektura – dorixonada topilmagan dorilar so‘rovi</p>
<p>Nakladnoy – yuk xati</p>"""


def rules(body: str, *, kinds=(), count=15):
    text = sanitize.to_text(sanitize.clean(body))
    return drafting.by_rules(SimpleNamespace(kinds=list(kinds), count=count), "Sahifa", text)


def test_a_temperature_range_is_blanked_and_changed():
    drafts, dropped = rules(COLD_CHAIN)
    assert dropped == 0
    [fridge, room] = [draft for draft in drafts if draft["kind"] == "text"]
    assert fridge["text"].endswith("dorilar muzlatgichda ____ saqlanadi.")
    assert fridge["data"]["answers"] == ["2–8", "+2 °C dan +8 °C gacha"]
    assert room["data"]["answers"][0] == "15–25"
    wrong = [draft for draft in drafts if draft["kind"] == "true_false"]
    assert wrong[0]["text"].endswith("muzlatgichda +2 °C dan +16 °C gacha saqlanadi.")
    assert wrong[0]["data"] == {"answer": False}
    assert "+2 °C dan +8 °C gacha" in wrong[0]["explanation"]
    # The times of day (09:00, 20:30) are never blanked.
    assert all("09:00" not in draft["text"] for draft in drafts)


def test_a_number_with_a_unit_word_and_its_false_twin():
    drafts, _dropped = rules(RECEIVING, kinds=["number", "true_false"])
    numbers = [draft for draft in drafts if draft["kind"] == "number"]
    assert [draft["data"]["value"] for draft in numbers] == [30, 6]
    assert numbers[0]["text"].endswith("Kirim ____ daqiqadan oshmasligi kerak.")
    statements = [draft["text"] for draft in drafts if draft["kind"] == "true_false"]
    assert "Kirim 60 daqiqadan oshmasligi kerak." in statements


def test_steps_become_an_order_question():
    drafts, _dropped = rules(RECEIVING, kinds=["order"])
    [steps] = drafts
    assert steps["text"] == "Put the steps in their order: Sahifa"
    assert [item["text"] for item in steps["data"]["items"]] == [
        "Nakladnoydagi nom va miqdorni sanab chiqing",
        "Har bir qatorning seriyasi va yaroqlilik muddatini tekshiring",
        "Sovuq zanjir dorilari: harorat yorlig‘ini ko‘ring va darhol muzlatgichga qo‘ying",
        "Nakladnoyni rasmga olib, ilovaga yuklang",
    ]


def test_term_lines_become_a_match_question():
    [pairs], _dropped = rules(TERMS)
    assert pairs["kind"] == "match"
    assert [(pair["left"], pair["right"]) for pair in pairs["data"]["pairs"]] == [
        ("XPN", "ta’sir etuvchi moddaning xalqaro nomi"),
        ("Defektura", "dorixonada topilmagan dorilar so‘rovi"),
        ("Nakladnoy", "yuk xati"),
    ]


def test_the_kinds_take_turns_up_to_the_count():
    drafts, _dropped = rules(RECEIVING, count=3)
    assert [draft["kind"] for draft in drafts] == ["true_false", "order", "number"]


@pytest.fixture
def page(pharmacy):
    cold = topic(pharmacy)
    found = PageFactory(
        space=SpaceFactory(company=pharmacy), title="Sovuq zanjir", body=sanitize.clean(COLD_CHAIN)
    )
    found.topics.add(cold)
    return found


def test_a_job_writes_drafts_for_the_bank(pharmacy, manager, page):
    job = drafting.create_job(pharmacy, by=manager, page_id=page.pk, count=4, engine="rules")
    assert job.topic == page.topics.get()
    assert drafting.run_job(job.pk) == 4
    job.refresh_from_db()
    assert (job.state, job.engine, job.made, job.dropped) == ("done", "rules", 4, 0)
    rows = Question.objects.filter(draft_job=job)
    assert set(rows.values_list("state", "source", "page", "topic")) == {
        ("draft", "rules", page.pk, page.topics.get().pk)
    }
    assert {row.created_by for row in rows} == {manager}
    assert drafting.run_job(job.pk) == 0  # once


def test_with_claude_a_number_not_in_the_text_drops_the_question(
    pharmacy, manager, page, fake_claude
):
    ai_on(pharmacy)
    fake_claude.script(
        fake_claude.json(
            {
                "questions": [
                    {
                        "kind": "single",
                        "text": "Insulin qayerda saqlanadi?",
                        "explanation": "Insulin muzlatgichda saqlanadi.",
                        "options": [
                            {"text": "Muzlatgichda, +2 °C dan +8 °C gacha", "correct": True},
                            {"text": "Javonda, xona haroratida", "correct": False},
                        ],
                    },
                    {
                        "kind": "number",
                        "text": "Muzlatgich harorati necha daraja bo‘lishi kerak?",
                        "value": 4,
                        "tolerance": 0,
                        "unit": "°C",
                    },
                    {
                        "kind": "true_false",
                        "text": "Insulin javonda turadi.",
                        "statement_is_true": None,
                    },
                ]
            }
        )
    )
    job = drafting.create_job(pharmacy, by=manager, page_id=page.pk, count=3)
    assert drafting.run_job(job.pk) == 1
    job.refresh_from_db()
    assert (job.engine, job.made, job.dropped) == ("claude", 1, 2)
    [written] = Question.objects.filter(draft_job=job)
    assert (written.kind, written.source, written.state) == ("single", "ai", "draft")
    [request] = fake_claude.requests
    assert request["model"] == settings.AI_MODEL_FAST
    assert drafting.DRAFT_SYSTEM in request["system"]
    assert "+2 °C dan +8 °C gacha" in request["messages"][0]["content"][0]["text"]


def test_when_claude_fails_the_rules_write_them(pharmacy, manager, page, fake_claude):
    ai_on(pharmacy)
    fake_claude.script(fake_claude.status_error(529))
    job = drafting.create_job(pharmacy, by=manager, page_id=page.pk, count=2)
    assert drafting.run_job(job.pk) == 2
    job.refresh_from_db()
    assert job.engine == "rules"


def test_without_ai_the_rules_write_them_and_claude_is_never_asked(
    pharmacy, manager, page, fake_claude
):
    job = drafting.create_job(pharmacy, by=manager, page_id=page.pk, count=2)
    assert drafting.run_job(job.pk) == 2
    assert fake_claude.requests == []
    assert QuestionDraftJob.objects.get().engine == "rules"


def test_a_page_without_text_fails_the_job(pharmacy, manager):
    empty = PageFactory(space=SpaceFactory(company=pharmacy), body="")
    job = drafting.create_job(pharmacy, by=manager, page_id=empty.pk, count=2)
    assert drafting.run_job(job.pk) == 0
    job.refresh_from_db()
    assert (job.state, job.error) == ("failed", "There is no text to write questions from.")
