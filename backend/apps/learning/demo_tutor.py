"""Demo data of the tutor's chat (package h, v11): the owner's "Ask the tutor" conversation in
which the tutor drafted three questions on the cold chain and a test of them, waiting on their
cards to be approved. Written as the chat writes it (the history Claude reads, the real quiz
tool, the cards), two days back, so every build tells the same story and the conversation can
go on with Claude or without."""

import json
from datetime import timedelta

from apps.ai import chat
from apps.ai.models import AIConversation, AIMessage, AITurn
from apps.ai.tools.registry import ToolContext
from apps.audit import services as audit
from apps.core import demo_time
from apps.knowledge.models import Page
from apps.learning import quizzes, tutor_tools
from apps.learning.audit_actions import QuizAction
from apps.learning.models import Question, TutorDraft

PAGE = "learning/tutor"
ASKED = "Sovuq zanjir bo‘yicha yangi xodimlar uchun 3 ta savol va ulardan test tuzib ber"
QUIZ_TITLE = "Sovuq zanjir: yangi xodimlar uchun"
ANSWER = (
    "**Sovuq zanjir** sahifasidan 3 ta savol qoralamasini yozdim va ulardan test qoralamasini "
    "tuzdim: o‘tish bali 70 %, vaqti 10 daqiqa. Hali hech narsa foydalanishda emas: quyidagi "
    "kartalarda har birini tasdiqlang, tahrirlang yoki o‘chiring."
)
# (kind, text, data, explanation, difficulty): as the tutor writes them from the page.
DRAFTS = (
    (
        "single",
        "Insulin muzlatgichda qanday haroratda saqlanadi?",
        {
            "options": [
                {"text": "+2 °C dan +8 °C gacha", "correct": True},
                {"text": "0 °C dan +2 °C gacha", "correct": False},
                {"text": "+15 °C dan +25 °C gacha", "correct": False},
            ]
        },
        "Issiqqa sezgir dorilar muzlatgichda +2 °C dan +8 °C gacha saqlanadi.",
        "easy",
    ),
    (
        "order",
        "Muzlatgich harorati chegaradan chiqdi. Nima qilasiz? To‘g‘ri tartibda joylang.",
        {
            "items": [
                {"text": "Darhol mudirga xabar beraman"},
                {"text": "Dorilarni zaxira muzlatgichga o‘tkazaman"},
                {"text": "Nima bo‘lganini jurnalga yozaman"},
            ]
        },
        "Avval mudirga xabar beriladi, keyin dorilar zaxira muzlatgichga o‘tkaziladi va hammasi "
        "jurnalga yoziladi.",
        "medium",
    ),
    (
        "true_false",
        "Harorati chegaradan chiqqan dorini mudir ruxsatisiz sotish mumkin.",
        {"answer": False},
        "Bunday dori mudir ruxsatisiz sotilmaydi.",
        "medium",
    ),
)


def seed(company, people, now) -> None:
    """The owner's conversation, where the cold chain page and the draft tools are there."""
    owner = people["owner"]
    page = (
        Page.objects.filter(company=company, title__icontains="sovuq zanjir").order_by("pk").first()
    )
    if page is None or not tutor_tools.tools_for(ToolContext.for_member(owner)):
        return
    at = now - timedelta(days=2, hours=3)
    with demo_time.moment(at):
        conversation = AIConversation.objects.create(
            company=company,
            membership=owner,
            agent=chat.TUTOR,
            title=ASKED[:60] + "…",
            last_activity_at=at,
            turn_count=1,
        )
        turn = AITurn.objects.create(
            company=company,
            conversation=conversation,
            membership=owner,
            page=PAGE,
            status=AITurn.Status.RUNNING,
            started_at=at,
        )
        history = _History(conversation, turn)
        history.add("user", [_text(chat.turn_context(owner, PAGE)), _text(ASKED)], ASKED)
        asked = {"page_id": page.pk, "count": 3, "kinds": ["single", "order", "true_false"]}
        history.add("assistant", [_use(tutor_tools.QUESTIONS, asked, "toolu_demo_1")])
        written = _questions(company, owner, turn, page)
        history.add("user", [_result("toolu_demo_1", written)])
        ids = [row["id"] for row in written["data"]["questions"]]
        quiz = {
            "title": QUIZ_TITLE,
            "question_ids": ids,
            "pass_percent": 70,
            "time_limit_minutes": 10,
        }
        history.add("assistant", [_use(tutor_tools.QUIZ, quiz, "toolu_demo_2")])
        made = tutor_tools.run(
            tutor_tools.QUIZ,
            ToolContext.for_member(owner, now=at),
            quiz,
            turn=turn,
            tool_use_id="toolu_demo_2",
        )
        history.add("user", [_result("toolu_demo_2", made)])
        answer = history.add("assistant", [_text(ANSWER)], ANSWER)
        steps = [
            {"label": str(tool.step), "status": "done", "ms": ms}
            for tool, ms in zip(tutor_tools.TOOLS, (8400, 300), strict=True)
        ]
        AITurn.objects.filter(pk=turn.pk).update(
            status=AITurn.Status.DONE,
            finished_at=at + timedelta(seconds=14),
            text=ANSWER,
            message=answer,
            model="demo",
            steps=steps,
        )


def _questions(company, owner, turn, page) -> dict:
    """The three drafts and their card, as tutor_draft_questions leaves them."""
    topic = page.topics.order_by("position", "pk").first()
    made = [
        quizzes.create_question(
            company,
            by=None,
            author=owner,
            kind=kind,
            text=text,
            data=data,
            explanation=explanation,
            difficulty=difficulty,
            topic_id=topic.pk if topic else None,
            page_id=page.pk,
            state=Question.State.DRAFT,
            source=Question.Source.AI,
        )
        for kind, text, data, explanation, difficulty in DRAFTS
    ]
    card = TutorDraft.objects.create(
        company=company,
        conversation_id=turn.conversation_id,
        turn=turn,
        tool_use_id="toolu_demo_1",
        kind=TutorDraft.Kind.QUESTIONS,
        state=TutorDraft.State.DONE,
        count=len(made),
        title=page.title,
        question_ids=[question.pk for question in made],
        created_by=owner,
    )
    audit.record(
        QuizAction.TUTOR_QUESTIONS_DRAFTED,
        company_id=company.pk,
        actor=owner.user,
        target=card,
        count=len(made),
        source="page",
        conversation=turn.conversation_id,
        turn=turn.pk,
    )
    return {
        "data": {
            "draft_id": card.pk,
            "state": "draft",
            "questions": [
                {"id": question.pk, "kind": question.kind, "text": question.text}
                for question in made
            ],
            "note": tutor_tools.NOTE,
        }
    }


class _History:
    """The conversation's messages in order, as the chat stores them."""

    def __init__(self, conversation, turn):
        self.conversation, self.turn, self.seq = conversation, turn, 0

    def add(self, role: str, content: list, display: str = "") -> AIMessage:
        self.seq += 1
        return AIMessage.objects.create(
            conversation=self.conversation,
            turn=self.turn,
            seq=self.seq,
            role=role,
            content=content,
            display_text=display,
        )


def _text(text: str) -> dict:
    return {"type": "text", "text": text}


def _use(name: str, tool_input: dict, tool_id: str) -> dict:
    return {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}


def _result(tool_id: str, result: dict) -> dict:
    content = json.dumps(result, ensure_ascii=False, default=str)
    return {"type": "tool_result", "tool_use_id": tool_id, "content": content}
