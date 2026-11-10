"""The tutor chat's draft tools (package h, v11): drafts only, the bank's rules, who may draft,
the cards, the person's approve and discard, and the chat's loop end to end."""

import json

import pytest
from django.conf import settings
from django.utils import timezone, translation

from apps.ai import chat
from apps.ai.models import AIConversation, AITurn
from apps.ai.tools import registry
from apps.ai.tools.registry import ToolContext
from apps.audit.models import AuditLog
from apps.companies.tests.factories import CompanyFactory
from apps.knowledge import sanitize
from apps.knowledge.demo import COLD_CHAIN
from apps.knowledge.tests.factories import PageFactory, SpaceFactory
from apps.learning import tutor_tools
from apps.learning.models import Question, QuestionDraftJob, Quiz, Status, TutorDraft
from apps.learning.tests.q2.fixtures import (
    ai_on,
    branch_viewer,
    person,
    position,
    question,
    switch_on,
    topic,
)
from apps.members.permissions import Perm

pytestmark = pytest.mark.django_db

QUESTIONS = tutor_tools.QUESTIONS
QUIZ = tutor_tools.QUIZ

# Three questions with only the cold chain page's numbers in them.
THREE = [
    {
        "kind": "single",
        "text": "Insulin muzlatgichda qanday haroratda saqlanadi?",
        "explanation": "Issiqqa sezgir dorilar +2 °C dan +8 °C gacha saqlanadi.",
        "options": [
            {"text": "+2 °C dan +8 °C gacha", "correct": True},
            {"text": "+15 °C dan +25 °C gacha", "correct": False},
        ],
    },
    {
        "kind": "true_false",
        "text": "Haroratni kuniga ikki marta yozish kerak.",
        "statement_is_true": True,
    },
    {
        "kind": "order",
        "text": "Harorat chegaradan chiqsa nima qilinadi?",
        "steps": ["Mudirga xabar bering", "Zaxira muzlatgichga o‘tkazing", "Jurnalga yozing"],
    },
]

# One question of each of the seven kinds (from what Claude knows: no number check).
SEVEN = [
    THREE[0],
    {
        "kind": "multi",
        "text": "Qaysilari muzlatgichda saqlanadi?",
        "options": [
            {"text": "Insulin", "correct": True},
            {"text": "Vaksina", "correct": True},
            {"text": "Paratsetamol tabletkasi", "correct": False},
        ],
    },
    THREE[1],
    THREE[2],
    {
        "kind": "match",
        "text": "Atamani ma’nosi bilan juftlang",
        "pairs": [
            {"left": "XPN", "right": "Xalqaro nom"},
            {"left": "Defektura", "right": "Topilmagan dorilar"},
        ],
    },
    {"kind": "text", "text": "Insulin qayerda saqlanadi?", "answers": ["muzlatgichda"]},
    {
        "kind": "number",
        "text": "Muzlatgichning eng past harorati necha daraja?",
        "value": 2,
        "tolerance": 0,
        "unit": "°C",
    },
]


def may_ask(member):
    member.role.permissions = [*member.role.permissions, Perm.AI_USE]
    member.role.save(update_fields=["permissions"])


@pytest.fixture
def page(pharmacy):
    cold = topic(pharmacy)
    found = PageFactory(
        space=SpaceFactory(company=pharmacy), title="Sovuq zanjir", body=sanitize.clean(COLD_CHAIN)
    )
    found.topics.add(cold)
    return found


def talk(member) -> AITurn:
    """A turn of a new "Ask the tutor" conversation of `member`'s."""
    conversation = AIConversation.objects.create(
        company=member.company, membership=member, agent="tutor", last_activity_at=timezone.now()
    )
    return AITurn.objects.create(
        company=member.company, conversation=conversation, membership=member
    )


def draft(member, name, tool_input, *, turn=None, tool_id="toolu_1"):
    turn = turn or talk(member)
    return tutor_tools.run(
        name, ToolContext.for_member(member), tool_input, turn=turn, tool_use_id=tool_id
    )


def url(company, path):
    return f"/api/v1/owner/companies/{company.pk}/learning/{path}"


# The tools make drafts, never anything in use ------------------------------------------------


def test_questions_from_a_page_are_drafts_linked_to_the_turn(pharmacy, manager, page, fake_claude):
    ai_on(pharmacy)
    fake_claude.script(fake_claude.json({"questions": THREE}))
    turn = talk(manager)

    found = draft(
        manager,
        QUESTIONS,
        {
            "page_id": page.pk,
            "count": 3,
            "kinds": ["single", "true_false", "order"],
            "brief": "Yangi farmatsevtlar uchun, sodda qilib",
        },
        turn=turn,
    )

    assert "error" not in found, found
    ids = [row["id"] for row in found["data"]["questions"]]
    assert len(ids) == 3 and found["data"]["state"] == "draft"
    rows = Question.objects.filter(pk__in=ids)
    assert set(rows.values_list("state", "source", "page", "topic")) == {
        ("draft", "ai", page.pk, page.topics.get().pk)
    }
    assert not Question.objects.exclude(state="draft").exists()
    card = TutorDraft.objects.get()
    assert (card.kind, card.state, card.question_ids, card.turn, card.tool_use_id) == (
        "questions",
        "done",
        ids,
        turn,
        "toolu_1",
    )
    assert (card.conversation, card.title, card.count) == (turn.conversation, "Sovuq zanjir", 3)
    assert card.job.state == QuestionDraftJob.State.DONE
    [request] = fake_claude.requests
    assert request["model"] == settings.AI_MODEL_FAST == "claude-haiku-5-5"
    assert request["output_config"]["effort"] == "medium"
    assert request["max_tokens"] >= 8000
    assert "temperature" not in request and "fallbacks" not in request
    asked = request["messages"][0]["content"][0]["text"]
    assert "Yangi farmatsevtlar uchun" in asked and "+2 °C dan +8 °C gacha" in asked
    entry = AuditLog.objects.get(action="learning.tutor_questions_drafted")
    assert entry.actor == manager.user
    assert entry.details["turn"] == turn.pk and entry.details["source"] == "page"


def test_all_seven_kinds_from_what_the_tutor_knows(pharmacy, manager, fake_claude):
    ai_on(pharmacy)
    cold = topic(pharmacy)
    fake_claude.script(fake_claude.json({"questions": SEVEN}))

    found = draft(manager, QUESTIONS, {"topic_id": cold.pk, "count": 7, "difficulty": "easy"})

    assert "error" not in found, found
    kinds = {row["kind"] for row in found["data"]["questions"]}
    assert kinds == set(Question.Kind.values)
    assert set(Question.objects.values_list("state", "topic", "difficulty", "page")) == {
        ("draft", cold.pk, "easy", None)
    }
    [request] = fake_claude.requests
    assert "pharmacy knowledge" in request["system"]
    assert "<topic>Sovuq zanjir</topic>" in request["messages"][0]["content"][0]["text"]


def test_a_number_not_in_the_page_leaves_a_question_out(pharmacy, manager, page, fake_claude):
    ai_on(pharmacy)
    wrong = {
        **THREE[0],
        "options": [{"text": "+4 °C", "correct": True}, {"text": "0", "correct": False}],
    }
    fake_claude.script(fake_claude.json({"questions": [wrong, THREE[1]]}))

    found = draft(manager, QUESTIONS, {"page_id": page.pk, "count": 2})

    assert len(found["data"]["questions"]) == 1 and found["data"]["left_out"] == 1


def test_a_quiz_is_a_draft_of_drafts_and_questions_in_use(pharmacy, manager, page, fake_claude):
    ai_on(pharmacy)
    fake_claude.script(fake_claude.json({"questions": THREE[:2]}))
    turn = talk(manager)
    written = draft(manager, QUESTIONS, {"page_id": page.pk, "count": 2}, turn=turn)
    ids = [row["id"] for row in written["data"]["questions"]]
    in_use = question(pharmacy, "true_false", state="active")
    position(pharmacy, "Farmatsevt")

    found = draft(
        manager,
        QUIZ,
        {
            "title": "Sovuq zanjir testi",
            "question_ids": [*ids, in_use.pk],
            "pass_percent": 80,
            "time_limit_minutes": 10,
            "positions": ["farmatsevt"],
        },
        turn=turn,
        tool_id="toolu_2",
    )

    assert "error" not in found, found
    quiz = Quiz.objects.get(pk=found["data"]["quiz_id"])
    assert (quiz.status, quiz.mode, quiz.pass_percent, quiz.time_limit_seconds) == (
        Status.DRAFT,
        "fixed",
        80,
        600,
    )
    assert not quiz.audience_all and [p.name for p in quiz.positions.all()] == ["Farmatsevt"]
    assert list(quiz.items.order_by("position").values_list("question_id", flat=True)) == [
        *ids,
        in_use.pk,
    ]
    assert found["data"]["draft_questions"] == 2
    assert set(Question.objects.filter(pk__in=ids).values_list("state", flat=True)) == {"draft"}
    card = TutorDraft.objects.get(kind="quiz")
    assert (card.quiz, card.question_ids, card.tool_use_id) == (quiz, [*ids, in_use.pk], "toolu_2")
    assert AuditLog.objects.filter(action="learning.tutor_quiz_drafted").count() == 1


# The bank's rules: a refused input changes nothing ---------------------------------------------


@pytest.mark.parametrize(
    "tool_input",
    [
        {"count": 20, "topic_id": None, "subject": "Insulin"},
        {"count": 3, "kinds": ["essay"], "subject": "Insulin"},
        {"count": 3},
        {"count": 3, "page_id": 1, "lesson_id": 2},
    ],
)
def test_a_wrong_questions_input_is_refused(pharmacy, manager, fake_claude, tool_input):
    ai_on(pharmacy)
    found = draft(manager, QUESTIONS, tool_input)
    assert found["error"] == "invalid_input", found
    assert not TutorDraft.objects.exists() and not Question.objects.exists()
    assert fake_claude.requests == []


def test_another_companys_page_is_refused(pharmacy, manager, fake_claude):
    ai_on(pharmacy)
    elsewhere = PageFactory(space=SpaceFactory(company=CompanyFactory()), body="<p>Matn 5.</p>")
    found = draft(manager, QUESTIONS, {"page_id": elsewhere.pk, "count": 2})
    assert found["error"] == "invalid_input" and "this company" in found["detail"]
    assert not QuestionDraftJob.objects.exists()


def test_without_ai_only_a_text_can_be_turned_into_questions(pharmacy, manager, page):
    cold = topic(pharmacy)
    refused = draft(manager, QUESTIONS, {"topic_id": cold.pk, "count": 2})
    assert refused["error"] == "invalid_input" and "page" in refused["detail"]

    found = draft(manager, QUESTIONS, {"page_id": page.pk, "count": 2})  # the rules write them
    assert found["data"]["written_by"] == "rules" and len(found["data"]["questions"]) == 2
    assert set(Question.objects.values_list("state", "source", flat=False)) == {("draft", "rules")}


@pytest.mark.parametrize(
    "change",
    [
        {"question_ids": []},
        {"pass_percent": 0},
        {"time_limit_minutes": 500},
        {"title": ""},
        {"positions": ["Kosmonavt"]},
        {"question_ids": ["archived"]},
        {"question_ids": ["elsewhere"]},
    ],
)
def test_a_wrong_quiz_input_is_refused(pharmacy, manager, change):
    mine = question(pharmacy, "single", state="active")
    archived = question(pharmacy, "single", state="archived")
    elsewhere = question(switch_on(CompanyFactory()), "single")
    tool_input = {"title": "Test", "question_ids": [mine.pk]} | change
    swap = {"archived": archived.pk, "elsewhere": elsewhere.pk}
    tool_input["question_ids"] = [swap.get(pk, pk) for pk in tool_input["question_ids"]]

    found = draft(manager, QUIZ, tool_input)

    assert found["error"] == "invalid_input", found
    assert not Quiz.objects.exists() and not TutorDraft.objects.exists()


def test_an_unknown_position_names_the_companys(pharmacy, manager):
    position(pharmacy, "Kassir")
    mine = question(pharmacy, "single", state="active")
    found = draft(manager, QUIZ, {"title": "T", "question_ids": [mine.pk], "positions": ["X"]})
    assert "Kassir" in found["detail"]


# Who may draft ------------------------------------------------------------------------------


def test_only_learning_managers_get_the_draft_tools(pharmacy, manager):
    viewer = branch_viewer(pharmacy, list(pharmacy.branches.all()), perms=(Perm.LEARNING_VIEW,))
    assert tutor_tools.tools_for(ToolContext.for_member(viewer)) == []
    assert draft(viewer, QUESTIONS, {"subject": "Insulin"}) == {"error": "not_allowed"}
    assert {tool.name for tool in tutor_tools.tools_for(ToolContext.for_member(manager))} == {
        QUESTIONS,
        QUIZ,
    }
    # Never in the read-only registry: Ask AI and the custom agents can't draft.
    assert registry.get_tool(QUESTIONS) is None and registry.get_tool(QUIZ) is None
    ask_ai = AIConversation.objects.create(
        company=pharmacy, membership=manager, last_activity_at=timezone.now()
    )
    names = {tool.name for tool in chat.conversation_tools(ask_ai, ToolContext.for_member(manager))}
    assert not names & {QUESTIONS, QUIZ}
    tutor_names = {
        tool.name
        for tool in chat.conversation_tools(
            talk(manager).conversation, ToolContext.for_member(manager)
        )
    }
    assert {QUESTIONS, QUIZ, "learning_questions"} <= tutor_names


def test_no_draft_tools_while_learning_is_off(pharmacy, manager):
    pharmacy.features = [feature for feature in pharmacy.features if feature != "learning"]
    pharmacy.save(update_fields=["features"])
    assert tutor_tools.tools_for(ToolContext.for_member(manager)) == []
    assert draft(manager, QUESTIONS, {"subject": "Insulin"}) == {"error": "not_allowed"}


def test_the_bank_tool_never_gives_the_right_answers(pharmacy, manager):
    cold = topic(pharmacy)
    question(pharmacy, "single", topic=cold, state="active", text="Insulin qayerda?")
    question(pharmacy, "true_false", state="draft")
    question(pharmacy, "single", state="archived")
    viewer = branch_viewer(pharmacy, list(pharmacy.branches.all()), perms=(Perm.LEARNING_VIEW,))
    assert registry.run_tool("learning_questions", ToolContext.for_member(viewer), {}) == {
        "error": "not_allowed"
    }

    found = registry.run_tool("learning_questions", ToolContext.for_member(manager), {})

    assert found["total"] == 2
    assert {row["state"] for row in found["rows"]} == {"active", "draft"}
    assert all("data" not in row and "options" not in row for row in found["rows"])
    only = registry.run_tool(
        "learning_questions", ToolContext.for_member(manager), {"topic_id": cold.pk}
    )
    assert [row["text"] for row in only["rows"]] == ["Insulin qayerda?"]


# The cards and the person's decisions --------------------------------------------------------


@pytest.fixture
def drafted(pharmacy, manager, page, fake_claude):
    """A turn of the manager's that drafted three questions and a quiz of them."""
    ai_on(pharmacy)
    may_ask(manager)
    fake_claude.script(fake_claude.json({"questions": THREE}))
    turn = talk(manager)
    written = draft(manager, QUESTIONS, {"page_id": page.pk, "count": 3}, turn=turn)
    ids = [row["id"] for row in written["data"]["questions"]]
    draft(
        manager,
        QUIZ,
        {"title": "Sovuq zanjir testi", "question_ids": ids},
        turn=turn,
        tool_id="toolu_2",
    )
    return turn, ids


def cards_of(client, company, turn):
    found = client.get(url(company, f"tutor/conversations/{turn.conversation_id}/drafts/"))
    assert found.status_code == 200, found.content
    return found.json()


def test_the_cards_show_each_question_as_it_will_look(owner_api, pharmacy, manager, drafted):
    turn, ids = drafted
    client = owner_api(manager)

    questions, quiz = cards_of(client, pharmacy, turn)

    assert (questions["kind"], questions["state"], questions["turn_id"]) == (
        "questions",
        "done",
        turn.pk,
    )
    assert [item["id"] for item in questions["questions"]] == ids
    single = questions["questions"][0]
    assert single["question"]["state"] == "draft" and single["deleted"] is False
    shown = single["preview"]["question"]
    right = single["preview"]["right_answer"]["option"]
    assert {option["id"] for option in shown["options"]} >= {right}
    assert "+2 °C dan +8 °C gacha" in [o["text"] for o in shown["options"] if o["id"] == right]
    assert single["preview"]["explanation"].startswith("Issiqqa sezgir")
    assert quiz["kind"] == "quiz" and quiz["quiz"]["status"] == "draft"
    assert quiz["quiz"]["audience_all"] is True and quiz["quiz"]["pass_percent"] == 70


def test_approving_one_question_and_then_the_rest(owner_api, pharmacy, manager, drafted):
    turn, ids = drafted
    client = owner_api(manager)
    questions = cards_of(client, pharmacy, turn)[0]

    one = client.post(
        url(pharmacy, f"tutor/drafts/{questions['id']}/approve/"),
        {"question_ids": [ids[0]]},
        format="json",
    )

    assert one.status_code == 200, one.content
    states = [item["question"]["state"] for item in one.json()["questions"]]
    assert states == ["active", "draft", "draft"]
    rest = client.post(url(pharmacy, f"tutor/drafts/{questions['id']}/approve/"), {}, format="json")
    assert [item["question"]["state"] for item in rest.json()["questions"]] == ["active"] * 3
    assert AuditLog.objects.filter(action="learning.question_activated").count() == 3


def test_discarding_deletes_drafts_and_the_card_says_so(owner_api, pharmacy, manager, drafted):
    turn, ids = drafted
    client = owner_api(manager)
    questions = cards_of(client, pharmacy, turn)[0]

    gone = client.post(
        url(pharmacy, f"tutor/drafts/{questions['id']}/discard/"),
        {"question_ids": [ids[1]]},
        format="json",
    )

    assert gone.status_code == 200, gone.content
    assert [item["deleted"] for item in gone.json()["questions"]] == [False, True, False]
    assert not Question.objects.filter(pk=ids[1]).exists()
    # A question put into use elsewhere can't be discarded from the card any more.
    client.patch(url(pharmacy, f"questions/{ids[0]}/"), {"state": "active"}, format="json")
    refused = client.post(
        url(pharmacy, f"tutor/drafts/{questions['id']}/discard/"),
        {"question_ids": [ids[0]]},
        format="json",
    )
    assert refused.status_code == 400
    # Discarding all leaves the one in use alone.
    client.post(url(pharmacy, f"tutor/drafts/{questions['id']}/discard/"), {}, format="json")
    assert list(Question.objects.values_list("pk", "state")) == [(ids[0], "active")]


def test_the_cards_stay_live(owner_api, pharmacy, manager, drafted):
    turn, ids = drafted
    client = owner_api(manager)
    client.patch(url(pharmacy, f"questions/{ids[0]}/"), {"state": "active"}, format="json")
    client.delete(url(pharmacy, f"questions/{ids[2]}/"))
    quiz = Quiz.objects.get()
    client.post(url(pharmacy, f"quizzes/{quiz.pk}/publish/"))

    questions, quiz_card = cards_of(client, pharmacy, turn)

    assert [
        item["question"]["state"] if item["question"] else None for item in questions["questions"]
    ] == [
        "active",
        "draft",
        None,
    ]
    assert questions["questions"][2]["deleted"] is True
    assert quiz_card["quiz"]["status"] == "published"


def test_approving_the_quiz_puts_its_drafts_into_use_and_publishes_it(
    owner_api, pharmacy, manager, drafted
):
    turn, ids = drafted
    client = owner_api(manager)
    quiz_card = cards_of(client, pharmacy, turn)[1]

    done = client.post(url(pharmacy, f"tutor/drafts/{quiz_card['id']}/approve/"), {}, format="json")

    assert done.status_code == 200, done.content
    assert done.json()["quiz"]["status"] == "published"
    assert set(Question.objects.filter(pk__in=ids).values_list("state", flat=True)) == {"active"}
    assert AuditLog.objects.filter(action="learning.quiz_published").count() == 1


def test_a_quiz_without_questions_is_not_published(owner_api, pharmacy, manager, drafted):
    turn, _ids = drafted
    client = owner_api(manager)
    questions, quiz_card = cards_of(client, pharmacy, turn)
    client.post(url(pharmacy, f"tutor/drafts/{questions['id']}/discard/"), {}, format="json")

    refused = client.post(
        url(pharmacy, f"tutor/drafts/{quiz_card['id']}/approve/"), {}, format="json"
    )

    assert refused.status_code == 400
    assert Quiz.objects.get().status == Status.DRAFT


def test_discarding_the_quiz_keeps_its_questions(owner_api, pharmacy, manager, drafted):
    turn, ids = drafted
    client = owner_api(manager)
    quiz_card = cards_of(client, pharmacy, turn)[1]

    gone = client.post(url(pharmacy, f"tutor/drafts/{quiz_card['id']}/discard/"), {}, format="json")

    assert gone.status_code == 200 and gone.json()["quiz"] is None
    assert not Quiz.objects.exists()
    assert Question.objects.filter(pk__in=ids).count() == 3


def test_only_the_conversations_owner_decides(owner_api, pharmacy, manager, drafted):
    turn, _ids = drafted
    card = TutorDraft.objects.get(kind="questions")
    other = person(pharmacy, "Manager", first_name="Nodira", last_name="Aliyeva")
    may_ask(other)
    client = owner_api(other)
    assert (
        client.get(url(pharmacy, f"tutor/conversations/{turn.conversation_id}/drafts/")).status_code
        == 404
    )
    assert (
        client.post(
            url(pharmacy, f"tutor/drafts/{card.pk}/approve/"), {}, format="json"
        ).status_code
        == 404
    )
    assert set(Question.objects.values_list("state", flat=True)) == {"draft"}


def test_the_draft_endpoints_need_learning_manage(owner_api, pharmacy, manager, drafted):
    _turn, _ids = drafted
    card = TutorDraft.objects.get(kind="questions")
    manager.role.permissions = [p for p in manager.role.permissions if p != Perm.LEARNING_MANAGE]
    manager.role.save(update_fields=["permissions"])
    client = owner_api(manager)
    assert (
        client.post(
            url(pharmacy, f"tutor/drafts/{card.pk}/approve/"), {}, format="json"
        ).status_code
        == 403
    )


def test_another_companys_card_is_not_found(owner_api, pharmacy, manager, drafted):
    card = TutorDraft.objects.get(kind="questions")
    elsewhere = switch_on(CompanyFactory())
    boss = person(elsewhere, "Manager")
    may_ask(boss)
    client = owner_api(boss)
    assert (
        client.post(
            url(elsewhere, f"tutor/drafts/{card.pk}/approve/"), {}, format="json"
        ).status_code
        == 404
    )


def test_the_cards_answer_404_while_learning_is_off(owner_api, pharmacy, manager, drafted):
    turn, _ids = drafted
    pharmacy.features = [feature for feature in pharmacy.features if feature != "learning"]
    pharmacy.save(update_fields=["features"])
    client = owner_api(manager)
    assert (
        client.get(url(pharmacy, f"tutor/conversations/{turn.conversation_id}/drafts/")).status_code
        == 404
    )


# The chat's loop end to end ------------------------------------------------------------------


def tool_use(name, tool_input, tool_id):
    return {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}


def answering(fake, monkeypatch):
    """Let the script hold functions of the request too (an answer that needs an id the
    conversation made)."""
    plain = fake._answer

    def answer(request):
        if (
            fake._script
            and callable(fake._script[0])
            and not isinstance(fake._script[0], BaseException)
        ):
            fake.requests.append(request)
            return fake._script.pop(0)(request)
        return plain(request)

    monkeypatch.setattr(fake, "_answer", answer)


def last_results(request) -> list[dict]:
    message = request["messages"][-1]
    assert message["role"] == "user"
    return message["content"]


def test_a_turn_drafts_three_questions_and_a_quiz(
    owner_api, pharmacy, manager, page, fake_claude, monkeypatch
):
    ai_on(pharmacy)
    may_ask(manager)
    answering(fake_claude, monkeypatch)

    def quiz_of(request):
        [result] = last_results(request)
        ids = [row["id"] for row in json.loads(result["content"])["data"]["questions"]]
        return fake_claude.message(
            [tool_use(QUIZ, {"title": "Sovuq zanjir testi", "question_ids": ids}, "toolu_2")],
            stop_reason="tool_use",
            model="claude-haiku-5-5",
        )

    fake_claude.script(
        fake_claude.message(
            [
                {"type": "thinking", "thinking": "", "signature": "sig"},
                tool_use(QUESTIONS, {"page_id": page.pk, "count": 3}, "toolu_1"),
            ],
            stop_reason="tool_use",
            model="claude-haiku-5-5",
        ),
        fake_claude.json({"questions": THREE}, model="claude-haiku-5-5"),
        quiz_of,
        fake_claude.text(
            "3 ta savol va test qoralamasini tayyorladim: kartalarni ko‘ring.",
            model="claude-haiku-5-5",
        ),
    )
    made = owner_api(manager).post(url(pharmacy, "tutor/conversations/"))
    conversation = AIConversation.objects.get(pk=made.json()["id"])
    turn = chat.start_turn(
        conversation, by=manager, text="Sovuq zanjir bo‘yicha 3 ta savol va test tuz"
    )

    chat.run_turn(turn.pk)

    turn.refresh_from_db()
    assert turn.status == "done", turn.error_code
    assert [step["status"] for step in turn.steps] == ["done", "done"]
    with translation.override(manager.user.language):  # the chat's short words, not the long
        assert turn.steps[0]["label"] == str(tutor_tools.TOOLS[0].step)
    first, drafting_call, second, third = fake_claude.requests
    assert first["model"] == settings.AI_MODEL_FAST and first["output_config"]["effort"] == "medium"
    names = [tool["name"] for tool in first["tools"]]
    assert names == sorted(names) and {QUESTIONS, QUIZ} <= set(names)
    assert "temperature" not in first and "tool_choice" not in first
    assert second["tools"] == first["tools"] and second["system"] == first["system"]
    assert [r["tool_use_id"] for r in last_results(second)] == ["toolu_1"]
    assert [r["tool_use_id"] for r in last_results(third)] == ["toolu_2"]
    assert "is_error" not in last_results(third)[0]
    assert drafting_call["output_config"]["format"]["type"] == "json_schema"
    assert Question.objects.filter(state="draft").count() == 3
    assert not Question.objects.exclude(state="draft").exists()
    quiz = Quiz.objects.get()
    assert quiz.status == Status.DRAFT and quiz.items.count() == 3
    cards = cards_of(owner_api(manager), pharmacy, turn)
    assert [(card["kind"], card["message_id"]) for card in cards] == [
        ("questions", turn.message_id),
        ("quiz", turn.message_id),
    ]


def test_every_result_of_a_round_goes_in_one_message_with_is_error_on_a_refusal(
    pharmacy, manager, page, fake_claude
):
    ai_on(pharmacy)
    may_ask(manager)
    fake_claude.script(
        fake_claude.message(
            [
                tool_use(QUESTIONS, {"page_id": page.pk, "count": 2}, "toolu_1"),
                tool_use(QUIZ, {"title": "", "question_ids": []}, "toolu_2"),
            ],
            stop_reason="tool_use",
            model="claude-haiku-5-5",
        ),
        fake_claude.json({"questions": THREE[:2]}),
        fake_claude.text("Ikkita savol tayyor; testni keyin tuzaman."),
    )
    conversation = chat.start_conversation(manager, agent="tutor")
    turn = chat.start_turn(conversation, by=manager, text="2 ta savol va test tuz")

    chat.run_turn(turn.pk)

    *_rest, last = fake_claude.requests
    results = last_results(last)
    assert [result["tool_use_id"] for result in results] == ["toolu_1", "toolu_2"]
    assert "is_error" not in results[0] and results[1]["is_error"] is True
    assert json.loads(results[1]["content"])["error"] == "invalid_input"
    turn.refresh_from_db()
    assert [step["status"] for step in turn.steps] == ["done", "error"]
    assert not Quiz.objects.exists()


def test_a_cut_off_answer_runs_no_tool(pharmacy, manager, page, fake_claude):
    ai_on(pharmacy)
    may_ask(manager)
    fake_claude.script(
        fake_claude.message(
            [tool_use(QUESTIONS, {"page_id": page.pk, "count": 15}, "toolu_1")],
            stop_reason="max_tokens",
        )
    )
    conversation = chat.start_conversation(manager, agent="tutor")
    turn = chat.start_turn(conversation, by=manager, text="15 ta savol tuz")

    chat.run_turn(turn.pk)

    turn.refresh_from_db()
    assert (turn.status, turn.error_code) == ("failed", "max_tokens")
    assert not TutorDraft.objects.exists() and not Question.objects.exists()


def test_without_claude_the_tutor_drafts_from_a_page_when_asked(
    owner_api, pharmacy, manager, page, settings
):
    settings.AI_FAKE = True
    ai_on(pharmacy)
    may_ask(manager)
    conversation = chat.start_conversation(manager, agent="tutor")
    turn = chat.start_turn(
        conversation, by=manager, text="Sovuq zanjir bo‘yicha 3 ta savol va test tuzib ber"
    )

    chat.run_turn(turn.pk)

    turn.refresh_from_db()
    assert turn.status == "done"
    assert "Sovuq zanjir" in turn.text and "3" in turn.text
    assert [step["status"] for step in turn.steps] == ["done", "done"]
    assert Question.objects.filter(state="draft", source="rules").count() == 3
    assert Quiz.objects.get().status == Status.DRAFT
    cards = cards_of(owner_api(manager), pharmacy, turn)
    assert [card["kind"] for card in cards] == ["questions", "quiz"]
    # Any other question still gets the weakest topics.
    other = chat.start_turn(conversation, by=manager, text="Kim sust?")
    chat.run_turn(other.pk)
    other.refresh_from_db()
    assert TutorDraft.objects.count() == 2
