"""Read-only AI tools of package Q2 (quizzes, the daily question, checks, skills, the tutor),
imported by `ai_tools.py`.

Each wraps a query and registers with `apps.ai.tools.registry.ai_tool` (domain "learning",
feature "learning", perm `learning.view`; names start with `learning_`). They keep to the
asker's branches (`ctx.branch_ids`) and give names, counts and percentages, never a phone
number or pay. `learning_questions` (the bank, for the tutor's draft quizzes) needs
`learning.manage`, like the bank's own pages, and never gives a right answer.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

from django.utils import translation
from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, Field

from apps.ai.tools.registry import ToolContext, ToolResult, ai_tool
from apps.learning import quiz_queries, skills, suggestions
from apps.learning.models import CheckRound, Question, Quiz, RegularCheck, Status
from apps.members.permissions import Perm

DOMAIN = "learning"
FEATURE = "learning"


class LearningSkillsInput(BaseModel):
    topic: str | None = Field(None, description="Part of a topic's name to keep to.")
    limit: int = Field(20, ge=1, le=50, description="How many people to list, weakest first.")


@ai_tool(
    "learning_skills",
    domain=DOMAIN,
    perm=Perm.LEARNING_VIEW,
    label=_(
        "The skill matrix: each topic's average mastery (0–100 from the questions answered "
        "lately), how many people are weak or strong in it, and each person's weak and strong "
        "topics, the weakest people first"
    ),
    input=LearningSkillsInput,
    feature=FEATURE,
)
def learning_skills(ctx: ToolContext, args: LearningSkillsInput) -> ToolResult:
    found = skills.matrix(ctx.company, branch_ids=ctx.branch_ids)
    columns = found["topics"]
    if args.topic:
        wanted = args.topic.casefold()
        columns = [column for column in columns if wanted in column["topic"].name.casefold()]
    names = {column["topic"].pk: column["topic"].name for column in columns}
    rows = []
    for row in found["people"]:
        cells = {topic_id: cell for topic_id, cell in row["cells"].items() if topic_id in names}
        rated = {topic_id: cell for topic_id, cell in cells.items() if cell["score"] is not None}
        if not rated:
            continue
        rows.append(
            {
                "id": row["member"].pk,
                "name": str(row["member"]),
                "position": row["member"].position.name if row["member"].position_id else None,
                "average": round(sum(c["score"] for c in rated.values()) / len(rated)),
                "weak": [names[t] for t, c in rated.items() if c["score"] < skills.WEAK],
                "strong": [names[t] for t, c in rated.items() if c["score"] >= skills.STRONG],
            }
        )
    rows.sort(key=lambda row: (row["average"], row["name"]))
    return ToolResult(
        rows=rows[: args.limit],
        total=len(rows),
        data={
            "topics": [
                {
                    "id": column["topic"].pk,
                    "name": column["topic"].name,
                    "average": column["average"],
                    "rated": column["rated"],
                    "weak": column["weak"],
                    "strong": column["strong"],
                }
                for column in columns
            ],
            "weak_below": skills.WEAK,
            "strong_from": skills.STRONG,
        },
        as_of=ctx.now,
    )


class LearningQuizResultsInput(BaseModel):
    days: int = Field(30, ge=1, le=365, description="Attempts finished in the last N days.")


@ai_tool(
    "learning_quiz_results",
    domain=DOMAIN,
    perm=Perm.LEARNING_VIEW,
    label=_(
        "Quiz results: for each published quiz the attempts, people, pass rate and average "
        "score in the last N days, and its hardest questions"
    ),
    input=LearningQuizResultsInput,
    feature=FEATURE,
)
def learning_quiz_results(ctx: ToolContext, args: LearningQuizResultsInput) -> ToolResult:
    since = ctx.now - timedelta(days=args.days)
    quizzes = list(
        Quiz.objects.filter(company=ctx.company)
        .exclude(status=Status.DRAFT)
        .order_by("title", "pk")[:50]
    )
    rows = []
    for quiz in quizzes:
        found = quiz_queries.results(quiz, branch_ids=ctx.branch_ids, start=since)
        summary = found["summary"]
        if not summary["attempts"]:
            continue
        rows.append(
            {
                "id": quiz.pk,
                "title": quiz.title,
                "archived": quiz.status == Status.ARCHIVED,
                "pass_percent": quiz.pass_percent,
                **summary,
                "hardest": [
                    {"text": row["text"][:160], "right_percent": row["percent"]}
                    for row in found["hardest"][:3]
                ],
            }
        )
    return ToolResult(rows=rows, data={"days": args.days}, as_of=ctx.now)


class LearningSuggestionsInput(BaseModel):
    kind: str | None = Field(
        None,
        description="Only one kind: assign, lesson_needed, overdue, mentor or praise.",
    )


@ai_tool(
    "learning_suggestions",
    domain=DOMAIN,
    perm=Perm.LEARNING_VIEW,
    label=_(
        "The tutor's open suggestions: who to assign which course, topics a lesson is missing "
        "for, who is late with mandatory training, who could coach others, who to thank"
    ),
    input=LearningSuggestionsInput,
    feature=FEATURE,
)
def learning_suggestions(ctx: ToolContext, args: LearningSuggestionsInput) -> ToolResult:
    found = suggestions.visible(ctx.membership)
    if args.kind:
        found = found.filter(kind=args.kind)
    with translation.override(ctx.language):
        rows = [
            {
                "id": row.pk,
                "kind": row.kind,
                "person": str(row.membership) if row.membership_id else None,
                "topic": row.topic.name if row.topic_id else None,
                "course": row.course.title if row.course_id else None,
                "text": suggestions.text(row),
            }
            for row in found[:50]
        ]
    return ToolResult(rows=rows, total=found.count(), as_of=ctx.now)


class LearningQuestionsInput(BaseModel):
    topic_id: int | None = Field(None, description="Only the questions of this topic.")
    state: Literal["draft", "active"] | None = Field(
        None, description="draft or active (in use); leave it out for both."
    )
    kind: Literal["single", "multi", "true_false", "order", "match", "text", "number"] | None = None
    words: str | None = Field(None, max_length=100, description="Words of the question's text.")
    limit: int = Field(20, ge=1, le=50)


@ai_tool(
    "learning_questions",
    domain=DOMAIN,
    perm=Perm.LEARNING_MANAGE,
    label=_(
        "The question bank: questions in use and drafts with their kind, topic, difficulty and "
        "how often they were answered right (never the right answers), newest first"
    ),
    input=LearningQuestionsInput,
    feature=FEATURE,
)
def learning_questions(ctx: ToolContext, args: LearningQuestionsInput) -> ToolResult:
    rows = quiz_queries.questions(
        ctx.company, topic=args.topic_id, kind=args.kind, state=args.state, q=args.words
    ).exclude(state=Question.State.ARCHIVED)
    total = rows.count()
    found = []
    for row in rows.select_related("topic")[: args.limit]:
        found.append(
            {
                "id": row.pk,
                "kind": row.kind,
                "text": row.text[:200],
                "topic": row.topic.name if row.topic_id else None,
                "topic_id": row.topic_id,
                "difficulty": row.difficulty,
                "state": row.state,
                "answered": row.answered,
                "right_percent": round(row.correct / row.answered * 100) if row.answered else None,
            }
        )
    return ToolResult(rows=found, total=total, as_of=ctx.now)


class LearningChecksInput(BaseModel):
    pass


@ai_tool(
    "learning_checks",
    domain=DOMAIN,
    perm=Perm.LEARNING_VIEW,
    label=_(
        "Regular checks: each active check's schedule and its latest round (people, answered, "
        "passed, who hasn't answered), and how the last rounds went"
    ),
    input=LearningChecksInput,
    feature=FEATURE,
)
def learning_checks(ctx: ToolContext, args: LearningChecksInput) -> ToolResult:
    rows = []
    for check in (
        RegularCheck.objects.filter(company=ctx.company)
        .exclude(state=RegularCheck.State.ARCHIVED)
        .select_related("quiz")
    ):
        rounds = list(CheckRound.objects.filter(regular_check=check).order_by("-starts_at")[:4])
        last = rounds[0] if rounds else None
        detail = quiz_queries.round_detail(last, branch_ids=ctx.branch_ids) if last else None
        rows.append(
            {
                "id": check.pk,
                "title": check.title,
                "quiz": check.quiz.title,
                "state": check.state,
                "every": check.every,
                "next": check.next_run_at.isoformat() if check.next_run_at else None,
                "latest": {
                    "starts": last.starts_at.isoformat(),
                    "due": last.due_at.isoformat(),
                    "closed": last.closed_at is not None,
                    "people": detail["people"],
                    "answered": detail["done"],
                    "passed": detail["passed"],
                    "not_answered": [
                        entry["member"]["name"] for entry in detail["entries"] if not entry["done"]
                    ][:20],
                }
                if last
                else None,
                "earlier": [
                    quiz_queries.round_row(row, branch_ids=ctx.branch_ids) | {"id": row.pk}
                    for row in rounds[1:]
                ],
            }
        )
    return ToolResult(rows=rows, as_of=ctx.now)
