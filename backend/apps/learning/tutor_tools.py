"""The tutor chat's write tools (package h, v11): they only ever make drafts, which the person
approves, edits or discards in the chat.

    tools = tutor_tools.tools_for(ctx)        # AITool objects for "Ask the tutor" (apps.ai.chat)
    result = tutor_tools.run(name, ctx, tool_input, turn=turn, tool_use_id="toolu_…")
    cards = tutor_tools.cards(conversation, user)       # what the chat shows, live

- `tutor_draft_questions`: 1 to 15 questions of the bank's seven kinds, written by a drafting call
  (apps.learning.drafting: from a page's or a lesson's text, its numbers only; or from what
  Claude knows of one of the company's topics), state draft, source ai (the rules without
  Claude, from a text).
- `tutor_draft_quiz`: a draft quiz: a fixed list of draft or in-use questions, the pass mark,
  a time limit, the positions it is meant for.

The tools are never registered with `apps.ai.tools.registry`: that registry is read-only and
every Ask AI conversation and custom agent may use it. Each input is checked against the bank's
rules (the services' own checks), and a refused one comes back as `{"error": ...}` (the chat's
loop sends it with `is_error`). Each call leaves a `TutorDraft` (the chat's card: "being
written" while the drafting call works, then the drafts' ids) and an audit record. Approving
and discarding are the person's own calls (`approve`, `discard`: the owner endpoints
`learning/tutor/drafts/{id}/…`), never the AI's.
"""

from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass
from typing import Literal

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone, translation
from django.utils.functional import Promise
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext
from pydantic import BaseModel, Field, ValidationError

from apps.ai.tools.registry import AITool, ToolContext
from apps.ai.tools.scrub import scrub_data
from apps.audit import services as audit
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.knowledge import queries as knowledge_queries
from apps.learning import conf, drafting, grading, quiz_queries, quizzes, skills
from apps.learning.audit_actions import QuizAction
from apps.learning.models import Question, QuestionDraftJob, Quiz, Status, TutorDraft
from apps.learning.services import ensure_manager
from apps.members.models import Membership, Position
from apps.members.permissions import Perm

logger = logging.getLogger(__name__)

QUESTIONS = "tutor_draft_questions"
QUIZ = "tutor_draft_quiz"
DOMAIN = "learning"
MAX_QUESTIONS = drafting.COUNT[1]
QUIZ_MAX = quizzes.COUNT[1]
NOTE = (
    "Saved as drafts, not in use: the asker sees each one as a card under your answer and "
    "approves, edits or discards it there."
)

KindName = Literal["single", "multi", "true_false", "order", "match", "text", "number"]


class DraftQuestionsInput(BaseModel):
    count: int = Field(5, ge=1, le=MAX_QUESTIONS, description="How many questions, 1–15.")
    kinds: list[KindName] = Field(
        default_factory=list,
        max_length=7,
        description=(
            "The kinds to write: single (one right option), multi (several right options), "
            "true_false, order (steps to put in order), match (pairs), text (type a short "
            "answer), number (a number and its unit). Empty: a mix."
        ),
    )
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    topic_id: int | None = Field(
        None,
        description=(
            "The company's topic the questions are about and filed under (topic ids come from "
            "learning_skills or learning_questions)."
        ),
    )
    page_id: int | None = Field(
        None, description="Write from this knowledge base page (ids from knowledge_search)."
    )
    lesson_id: int | None = Field(
        None, description="Write from this lesson's notes and transcript (ids from the tools)."
    )
    subject: str = Field(
        "",
        max_length=drafting.TOPIC_MAX,
        description="Without a page or a lesson, and when no topic says it: the subject, briefly.",
    )
    language: Literal["uz", "ru", "en"] | None = Field(
        None, description="The questions' language; leave it out for the company's own."
    )
    brief: str = Field(
        "",
        max_length=drafting.BRIEF_MAX,
        description="The asker's wishes in a sentence: who the questions are for, what to stress.",
    )


class DraftQuizInput(BaseModel):
    title: str = Field(..., min_length=1, max_length=quizzes.TITLE_MAX)
    description: str = Field("", max_length=quizzes.DESCRIPTION_MAX)
    question_ids: list[int] = Field(
        ...,
        min_length=1,
        max_length=QUIZ_MAX,
        description=(
            "The quiz's questions in their order: drafts from tutor_draft_questions or "
            "questions of the bank (learning_questions); not archived ones."
        ),
    )
    pass_percent: int = Field(70, ge=1, le=100, description="The pass mark, percent.")
    time_limit_minutes: int | None = Field(
        None, ge=1, le=240, description="A time limit in minutes; leave it out for none."
    )
    max_attempts: int | None = Field(None, ge=1, le=20, description="Leave it out for any.")
    positions: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Who it is meant for: the company's position names; empty: everyone.",
    )


@dataclass(frozen=True)
class DraftTool(AITool):
    """An AITool with the short words the chat shows while it runs (`step`)."""

    step: str | Promise = ""


def _tool(name, label, step, model, fn) -> DraftTool:
    return DraftTool(
        name=name,
        domain=DOMAIN,
        perm=Perm.LEARNING_MANAGE,
        label=label,
        input=model,
        fn=fn,
        feature="learning",
        step=step,
    )


def tools_for(ctx: ToolContext) -> list[DraftTool]:
    """The draft tools `ctx`'s member may use (learning.manage, the module on), by name."""
    if not conf.is_on(ctx.company):
        return []
    return [tool for tool in TOOLS if tool.allowed(ctx)]


def names() -> frozenset[str]:
    return frozenset(tool.name for tool in TOOLS)


def run(name: str, ctx: ToolContext, raw_input, *, turn, tool_use_id: str) -> dict:
    """Run one draft tool call as `ctx`'s member in `turn`; always a JSON-ready dict, problems
    as {"error": "unknown_tool" | "not_allowed" | "invalid_input" | "not_written", ...}."""
    if ctx.company.pk != ctx.membership.company_id or turn.company_id != ctx.company.pk:
        raise ValueError("The context, the turn and the member must be one company's.")
    tool = next((tool for tool in TOOLS if tool.name == name), None)
    if tool is None:
        return {"error": "unknown_tool"}
    if tool not in tools_for(ctx):
        return {"error": "not_allowed"}
    try:
        if isinstance(raw_input, str | bytes):
            args = tool.input.model_validate_json(raw_input)
        else:
            args = tool.input.model_validate(raw_input or {})
    except ValidationError as exc:
        problems = [
            {"field": ".".join(str(part) for part in error["loc"]), "problem": error["msg"]}
            for error in exc.errors()
        ]
        return scrub_data({"error": "invalid_input", "details": problems})
    try:
        with translation.override("en"):  # Claude reads what was wrong in English
            return scrub_data(tool.fn(ctx, args, turn=turn, tool_use_id=tool_use_id[:64]))
    except grading.InvalidQuestion as exc:
        return scrub_data({"error": "invalid_input", "details": exc.errors})
    except (DomainError, PermissionDenied) as exc:
        return scrub_data({"error": "invalid_input", "detail": str(exc)})


# Drafting questions -----------------------------------------------------------------------


def _draft_questions(ctx: ToolContext, args: DraftQuestionsInput, *, turn, tool_use_id) -> dict:
    company, member = ctx.company, ctx.membership
    from_text = bool(args.page_id or args.lesson_id)
    # What only Claude reads is plain English (run() switches the services' messages to it).
    if not (from_text or args.topic_id or args.subject.strip()):
        raise DomainError("Name a page, a lesson, a topic or a subject to write about.")
    if not from_text and not drafting.claude_may_run(company):
        raise DomainError(
            "Writing from what you know needs AI, which can't run here now: name a knowledge "
            "base page or a lesson, and its text is turned into questions."
        )
    if args.page_id and knowledge_queries.get_page(member, args.page_id) is None:
        raise DomainError(_("Pick a page or a lesson of this company."))
    with transaction.atomic():
        job = drafting.start_for_tutor(
            company,
            by=member,
            page_id=args.page_id,
            lesson_id=args.lesson_id,
            count=args.count,
            kinds=list(args.kinds),
            difficulty=args.difficulty,
            topic_id=args.topic_id,
        )
        draft = TutorDraft.objects.create(
            company=company,
            conversation_id=turn.conversation_id,
            turn=turn,
            tool_use_id=tool_use_id,
            kind=TutorDraft.Kind.QUESTIONS,
            count=job.count,
            title=_title(job, args.subject),
            job=job,
            created_by=member,
        )
        audit.record(
            QuizAction.TUTOR_QUESTIONS_DRAFTED,
            company_id=company.pk,
            actor=member.user,
            target=draft,
            count=job.count,
            source="page" if job.page_id else "lesson" if job.lesson_id else "knowledge",
            conversation=turn.conversation_id,
            turn=turn.pk,
        )
    # Committed: the chat shows the card as being written while the drafting call works.
    try:
        written = drafting.run_for_tutor(
            job, subject=args.subject, brief=args.brief, language=args.language or ""
        )
    except Exception:
        logger.exception("Tutor draft %s: the drafting call failed", draft.pk)
        QuestionDraftJob.objects.filter(pk=job.pk, state=QuestionDraftJob.State.RUNNING).update(
            state=QuestionDraftJob.State.FAILED
        )
        written = []
    job.refresh_from_db()
    draft.question_ids = written
    draft.state = TutorDraft.State.DONE if written else TutorDraft.State.FAILED
    with translation.override(company.default_language):  # the card's words, like job.error
        draft.error = "" if written else (job.error or _("No question passed the bank's checks."))
    draft.save(update_fields=["question_ids", "state", "error", "updated_at"])
    _bump(company.pk)
    if not written:
        return {"error": "not_written", "detail": draft.error}
    rows = Question.objects.filter(pk__in=written).select_related("topic").order_by("pk")
    return {
        "data": {
            "draft_id": draft.pk,
            "state": "draft",
            "questions": [
                {
                    "id": row.pk,
                    "kind": row.kind,
                    "text": row.text,
                    "topic": row.topic.name if row.topic_id else None,
                    "difficulty": row.difficulty,
                }
                for row in rows
            ],
            "asked": job.count,
            "left_out": job.dropped,
            "written_by": job.engine,
            "note": NOTE,
        }
    }


def _title(job: QuestionDraftJob, subject: str) -> str:
    """What the card says the questions are about (the page, the lesson, the topic)."""
    if job.page_id:
        return job.page.title[:200]
    if job.lesson_id:
        return job.lesson.title[:200]
    if job.topic_id:
        return job.topic.name[:200]
    return " ".join(subject.split())[:200]


# Drafting a quiz --------------------------------------------------------------------------


def _draft_quiz(ctx: ToolContext, args: DraftQuizInput, *, turn, tool_use_id) -> dict:
    company, member = ctx.company, ctx.membership
    wanted = list(dict.fromkeys(args.question_ids))
    positions = _positions(company, args.positions)
    with transaction.atomic():
        quiz = quizzes.create_quiz(
            company,
            by=member,
            title=args.title,
            description=args.description,
            mode=Quiz.Mode.FIXED,
            question_count=len(wanted),
            pass_percent=args.pass_percent,
            time_limit_seconds=args.time_limit_minutes * 60 if args.time_limit_minutes else None,
            max_attempts=args.max_attempts,
            audience_all=not positions,
            position_ids=[position.pk for position in positions],
            question_ids=wanted,
        )
        draft = TutorDraft.objects.create(
            company=company,
            conversation_id=turn.conversation_id,
            turn=turn,
            tool_use_id=tool_use_id,
            kind=TutorDraft.Kind.QUIZ,
            state=TutorDraft.State.DONE,
            count=len(wanted),
            title=quiz.title,
            question_ids=wanted,
            quiz=quiz,
            created_by=member,
        )
        audit.record(
            QuizAction.TUTOR_QUIZ_DRAFTED,
            company_id=company.pk,
            actor=member.user,
            target=draft,
            quiz=quiz.pk,
            questions=len(wanted),
            conversation=turn.conversation_id,
            turn=turn.pk,
        )
    drafts = Question.objects.filter(pk__in=wanted, state=Question.State.DRAFT).count()
    return {
        "data": {
            "draft_id": draft.pk,
            "quiz_id": quiz.pk,
            "status": quiz.status,
            "title": quiz.title,
            "questions": len(wanted),
            "draft_questions": drafts,
            "pass_percent": quiz.pass_percent,
            "time_limit_minutes": args.time_limit_minutes,
            "for": [position.name for position in positions] or "everyone",
            "note": NOTE,
        }
    }


def _positions(company, names: list[str]) -> list[Position]:
    """The company's positions by name (any case); an unknown name is refused with the names
    there are."""
    if not names:
        return []
    known = {row.name.casefold(): row for row in Position.objects.filter(company=company)}
    found, unknown = [], []
    for name in names:
        row = known.get(" ".join(name.split()).casefold())
        if row is None:
            unknown.append(name)
        elif row not in found:
            found.append(row)
    if unknown:
        there = ", ".join(sorted(row.name for row in known.values())[:30]) or "none"
        raise DomainError(
            f"Unknown positions: {', '.join(unknown)}. The company's positions: {there}."
        )
    return found


TOOLS = (
    _tool(
        QUESTIONS,
        # What Claude reads (English); the chat shows `step`.
        "Draft questions for the company's question bank (1 to 15 a call, any of the seven "
        "kinds), from a knowledge base page or a lesson the asker names, or from what you know "
        "of one of the company's topics. They are saved as drafts the asker reviews and "
        "approves in the chat: nothing is put into use by you.",
        gettext_lazy("Writing draft questions"),
        DraftQuestionsInput,
        _draft_questions,
    ),
    _tool(
        QUIZ,
        "Draft a quiz from draft questions you wrote or questions of the bank: its title, pass "
        "mark, time limit and the positions it is meant for. It is saved as a draft the asker "
        "approves and publishes in the chat: you never publish it.",
        gettext_lazy("Putting a draft quiz together"),
        DraftQuizInput,
        _draft_quiz,
    ),
)


# The cards --------------------------------------------------------------------------------


def _bump(company_id: int) -> None:
    transaction.on_commit(lambda: pulse.bump(company_id, quizzes.PULSE_KEY))


def preview(question: Question, user) -> dict:
    """The question as the learner will see it (a steady order: the card doesn't reshuffle at
    each refresh), with the right answer to mark."""
    order = grading.shown_order(question.kind, question.data, rng=random.Random(question.pk))
    return {
        "question": grading.play(
            question, order, image_url=quizzes.image_url(question.image, user)
        ),
        "right_answer": grading.right_answer(question.kind, question.data, order),
        "explanation": question.explanation,
    }


def cards(conversation, user) -> list[dict]:
    """The conversation's drafts as the chat shows them: each with its questions as they are
    now (a deleted one says so) and its quiz."""
    return _cards(TutorDraft.objects.filter(conversation=conversation), user)


def card(draft: TutorDraft, user) -> dict:
    return _cards(TutorDraft.objects.filter(pk=draft.pk), user)[0]


def _cards(rows, user) -> list[dict]:
    drafts = list(
        rows.select_related("turn", "quiz")
        .prefetch_related("quiz__positions")
        .order_by("created_at", "pk")
    )
    ids = {pk for draft in drafts for pk in draft.question_ids}
    company_ids = {draft.company_id for draft in drafts}
    found = list(
        Question.objects.filter(company_id__in=company_ids, pk__in=ids)
        .select_related("topic", "lesson", "page", "image")
        .order_by("pk")
    )
    questions = {row["id"]: row for row in quiz_queries.question_rows(found, user)}
    previews = {question.pk: preview(question, user) for question in found}
    return [_card(draft, questions, previews) for draft in drafts]


def _card(draft: TutorDraft, rows: dict, previews: dict) -> dict:
    items = [
        {
            "id": pk,
            "deleted": pk not in rows,
            "question": rows.get(pk),
            "preview": previews.get(pk) if draft.kind == TutorDraft.Kind.QUESTIONS else None,
        }
        for pk in draft.question_ids
    ]
    quiz = draft.quiz
    state, error = draft.state, draft.error
    if state == TutorDraft.State.RUNNING and _lost(draft):
        state, error = TutorDraft.State.FAILED, _("The questions couldn't be written: try again.")
    return {
        "id": draft.pk,
        "kind": draft.kind,
        "state": state,
        "turn_id": draft.turn_id,
        "message_id": draft.turn.message_id,
        "count": draft.count,
        "title": draft.title,
        "error": error,
        "created_at": draft.created_at,
        "questions": items,
        "quiz": {
            "id": quiz.pk,
            "title": quiz.title,
            "status": quiz.status,
            "pass_percent": quiz.pass_percent,
            "time_limit_seconds": quiz.time_limit_seconds,
            "max_attempts": quiz.max_attempts,
            "audience_all": quiz.audience_all,
            "positions": sorted(position.name for position in quiz.positions.all()),
        }
        if quiz is not None
        else None,
    }


def _lost(draft: TutorDraft) -> bool:
    """A card still "being written" whose turn ended, or that is far older than any drafting
    call (its job died with a worker): it says it failed, so the chat stops waiting for it."""
    from apps.ai.chat import STALE_AFTER, WORKING

    return draft.turn.status not in WORKING or draft.created_at < timezone.now() - STALE_AFTER


# The person's decisions -------------------------------------------------------------------


def _picked(draft: TutorDraft, question_ids: list[int] | None) -> list[int]:
    if question_ids is None:
        return list(draft.question_ids)
    unknown = set(question_ids) - set(draft.question_ids)
    if unknown:
        raise DomainError(_("Pick questions of this card."))
    return list(dict.fromkeys(question_ids))


@transaction.atomic
def approve(draft: TutorDraft, *, by: Membership, question_ids: list[int] | None = None):
    """The person approves: the card's draft questions (all, or `question_ids`) go into use; a
    quiz card puts its draft questions into use and publishes the quiz, or nothing changes."""
    ensure_manager(by)
    draft = TutorDraft.objects.select_for_update().get(pk=draft.pk)
    company = draft.company
    if draft.kind == TutorDraft.Kind.QUIZ:
        quiz = draft.quiz
        if quiz is None:
            raise DomainError(_("This quiz was deleted."))
        if quiz.status == Status.ARCHIVED:
            raise DomainError(_("This quiz is archived: restore it on its page first."))
        listed = list(quiz.items.values_list("question_id", flat=True))
        _activate(company, listed, by)
        quizzes.publish_quiz(quiz, by=by)
    else:
        _activate(company, _picked(draft, question_ids), by)
    return draft


def _activate(company, ids: list[int], by: Membership) -> None:
    rows = Question.objects.filter(company=company, pk__in=ids, state=Question.State.DRAFT)
    for question in rows.order_by("pk"):
        quizzes.set_question_state(question, Question.State.ACTIVE, by=by)


@transaction.atomic
def discard(draft: TutorDraft, *, by: Membership, question_ids: list[int] | None = None):
    """The person discards: the card's questions still drafts (all, or `question_ids`) are
    deleted; a quiz card deletes its quiz while it is a draft (its questions keep their own
    cards)."""
    ensure_manager(by)
    draft = TutorDraft.objects.select_for_update().get(pk=draft.pk)
    company = draft.company
    if draft.kind == TutorDraft.Kind.QUIZ:
        quiz = draft.quiz
        if quiz is None:
            return draft
        if quiz.status != Status.DRAFT:
            raise DomainError(_("This quiz is published: archive it on its page instead."))
        quizzes.delete_quiz(quiz, by=by)
        draft.refresh_from_db()
        return draft
    picked = _picked(draft, question_ids)
    rows = list(Question.objects.filter(company=company, pk__in=picked).order_by("pk"))
    if question_ids is not None and any(row.state != Question.State.DRAFT for row in rows):
        raise DomainError(_("This question is in use now: archive it on the questions page."))
    for question in rows:
        if question.state == Question.State.DRAFT:
            quizzes.delete_question(question, by=by)
    return draft


# AI_FAKE ----------------------------------------------------------------------------------

# Words of a request to write questions or a test (Uzbek, Russian, English).
ASKS_QUESTIONS = ("savol", "вопрос", "question")
ASKS_TEST = ("test", "тест", "quiz", "viktorina", "викторин")
MAKE = (
    "tuz",
    "yoz",
    "yarat",
    "tayyorla",
    "состав",
    "напиш",
    "сдела",
    "созда",
    "подготов",
    "make",
    "write",
    "draft",
    "create",
    "prepare",
)
FAKE_COUNT = 3
FAKE_PASS = 70
FAKE_MINUTES = 10
# Where a page's title stops naming its subject: "Sovuq zanjir: +2...+8 °C".
TITLE_HEAD = re.compile(r"\s*[:–—(]")


def wants_drafts(asked: str) -> bool:
    words = asked.casefold()
    return any(word in words for word in ASKS_QUESTIONS + ASKS_TEST) and any(
        word in words for word in MAKE
    )


def fake_answer(ctx: ToolContext, turn, asked: str) -> tuple[str, list[dict]] | None:
    """AI_FAKE (demos without Claude): asked to write questions, the tutor drafts three from a
    knowledge base page through the real tool (the rules engine writes them), and a draft test
    of them when a test was asked. None for any other question, or when the asker may not
    draft."""
    if not wants_drafts(asked) or not tools_for(ctx):
        return None
    page = _fake_page(ctx, asked)
    if page is None:
        return _("There is no knowledge base page to write questions from yet: add one first."), []
    steps: list[dict] = []
    found = _fake_call(ctx, turn, QUESTIONS, {"page_id": page.pk, "count": FAKE_COUNT}, steps)
    if "error" in found:
        return _("I couldn't write questions from the page %(page)s.") % {"page": page.title}, steps
    ids = [row["id"] for row in found["data"]["questions"]]
    parts = [
        ngettext(
            "From the page %(page)s I drafted %(count)s question.",
            "From the page %(page)s I drafted %(count)s questions.",
            len(ids),
        )
        % {"page": page.title, "count": len(ids)}
    ]
    if any(word in asked.casefold() for word in ASKS_TEST):
        made = _fake_call(
            ctx,
            turn,
            QUIZ,
            {
                "title": _("Test: %(page)s") % {"page": page.title},
                "question_ids": ids,
                "pass_percent": FAKE_PASS,
                "time_limit_minutes": FAKE_MINUTES,
            },
            steps,
        )
        if "error" not in made:
            parts.append(
                _("They make up a draft test: pass mark %(pass)s %%, %(minutes)s minutes.")
                % {"pass": FAKE_PASS, "minutes": FAKE_MINUTES}
            )
    parts.append(_("Nothing is in use yet: approve, edit or discard each card below."))
    return " ".join(parts), steps


def _fake_call(ctx, turn, name: str, tool_input: dict, steps: list[dict]) -> dict:
    tool = next(tool for tool in TOOLS if tool.name == name)
    started = time.monotonic()
    result = run(name, ctx, tool_input, turn=turn, tool_use_id=f"fake_{turn.pk}_{len(steps) + 1}")
    steps.append(
        {
            "label": str(tool.step),
            "status": "error" if "error" in result else "done",
            "ms": int((time.monotonic() - started) * 1000),
        }
    )
    return result


def _fake_page(ctx: ToolContext, asked: str):
    """A page with text the asker may read: one the question names (its title, or the title
    before a colon: "Sovuq zanjir: +2...+8 °C"), else one on a topic it names, else one on the
    weakest topic, else the first."""
    pages = list(
        knowledge_queries.readable_pages(ctx.membership)
        .exclude(body_text="")
        .prefetch_related("topics")
        .order_by("position", "pk")[:200]
    )
    if not pages:
        return None
    words = asked.casefold()

    def head(title: str) -> str:
        return TITLE_HEAD.split(title, maxsplit=1)[0].strip().casefold()

    for page in pages:
        if page.title.casefold() in words or (
            len(head(page.title)) > 3 and head(page.title) in words
        ):
            return page
    weakest = skills.weakest_topics(ctx.company, branch_ids=ctx.branch_ids, limit=3)
    for wanted in (
        lambda topic: topic.name.casefold() in words,
        lambda topic: any(column["topic"] == topic for column in weakest),
    ):
        for page in pages:
            if any(wanted(topic) for topic in page.topics.all()):
                return page
    return pages[0]
