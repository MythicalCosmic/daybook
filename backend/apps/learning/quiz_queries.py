"""Read functions of package Q2 (quizzes, checks, skills, suggestions) for the owner dashboard,
the tutor and the AI tools.

A function returning people's results takes the required keyword `branch_ids: list[int] |
None` (callers pass `apps.members.scope.branch_ids(member)`): people sharing one of those
branches, everyone when None.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta

from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from apps.learning import checks, grading, quizzes, skills, suggestions
from apps.learning.models import (
    AnswerLog,
    Attempt,
    CheckRound,
    DailyQuestion,
    Question,
    QuestionDraftJob,
    Quiz,
    QuizQuestion,
    RegularCheck,
    TutorSuggestion,
)
from apps.members.models import Membership
from apps.members.queries import photo_url

DONE = (Attempt.State.FINISHED, Attempt.State.EXPIRED)
# Score buckets of a quiz's distribution: 0 to 9, 10 to 19, and so on to 90 to 100.
BUCKETS = 10
RESULTS_LIMIT = 500
HARDEST = 10


def person(member: Membership | None) -> dict | None:
    if member is None:
        return None
    return {
        "id": member.pk,
        "name": str(member),
        "photo_url": photo_url(member),
        "position": member.position.name if member.position_id else None,
    }


def topic_ref(topic) -> dict | None:
    return {"id": topic.pk, "name": topic.name, "color": topic.color} if topic else None


def ref(row, attribute: str = "title") -> dict | None:
    return {"id": row.pk, "title": getattr(row, attribute)} if row else None


def people(company, *, branch_ids: list[int] | None) -> QuerySet[Membership]:
    """Everyone of the company whose results the viewer may see."""
    rows = Membership.objects.for_company(company)
    if branch_ids is None:
        return rows
    return Membership.objects.filter(pk__in=rows.filter(branches__in=branch_ids).values("pk"))


def in_scope(member: Membership, *, branch_ids: list[int] | None) -> bool:
    return branch_ids is None or member.branches.filter(pk__in=branch_ids).exists()


# Questions ---------------------------------------------------------------------------------


def questions(
    company,
    *,
    topic: int | None = None,
    kind: str | None = None,
    difficulty: str | None = None,
    state: str | None = None,
    source: str | None = None,
    q: str | None = None,
    draft_job: int | None = None,
) -> QuerySet[Question]:
    rows = Question.objects.filter(company=company).select_related(
        "topic", "image", "lesson", "page"
    )
    if topic:
        rows = rows.filter(topic_id=topic)
    if kind:
        rows = rows.filter(kind=kind)
    if difficulty:
        rows = rows.filter(difficulty=difficulty)
    if state:
        rows = rows.filter(state=state)
    if source:
        rows = rows.filter(source=source)
    if draft_job:
        rows = rows.filter(draft_job_id=draft_job)
    for word in (q or "").split()[:4]:
        rows = rows.filter(text__icontains=word)
    return rows.order_by("-created_at", "-pk")


def quiz_counts(question_ids: list[int]) -> dict[int, int]:
    rows = (
        QuizQuestion.objects.filter(question_id__in=question_ids)
        .values("question_id")
        .annotate(count=Count("pk"))
    )
    return {row["question_id"]: row["count"] for row in rows}


def image_ref(image, user) -> dict | None:
    if image is None or not image.file:
        return None
    return {
        "id": image.pk,
        "url": quizzes.image_url(image, user),
        "width": image.width,
        "height": image.height,
    }


def question_row(question: Question, user, counts: dict[int, int]) -> dict:
    answered = question.answered
    return {
        "id": question.pk,
        "kind": question.kind,
        "text": question.text,
        "data": question.data,
        "explanation": question.explanation,
        "image": image_ref(question.image, user),
        "topic": topic_ref(question.topic),
        "difficulty": question.difficulty,
        "points": question.points,
        "state": question.state,
        "source": question.source,
        "lesson": ref(question.lesson),
        "page": ref(question.page),
        "draft_job_id": question.draft_job_id,
        "answered": answered,
        "correct": question.correct,
        "correct_percent": math.floor(question.correct / answered * 100) if answered else None,
        "quizzes": counts.get(question.pk, 0),
        "created_at": question.created_at,
        "updated_at": question.updated_at,
    }


def question_rows(rows, user) -> list[dict]:
    rows = list(rows)
    counts = quiz_counts([row.pk for row in rows])
    return [question_row(row, user, counts) for row in rows]


# Quizzes -----------------------------------------------------------------------------------


def counted_attempts(company, *, branch_ids: list[int] | None) -> QuerySet[Attempt]:
    """Finished attempts that count (no manager's tries) of people the viewer sees."""
    rows = Attempt.objects.filter(company=company, trial=False, state__in=DONE)
    if branch_ids is not None:
        rows = rows.filter(membership__in=people(company, branch_ids=branch_ids))
    return rows


def quiz_stats(company, quiz_ids: list[int], *, branch_ids: list[int] | None) -> dict[int, dict]:
    """Per quiz: attempts, people who took it, people who passed it, the average score."""
    rows = counted_attempts(company, branch_ids=branch_ids).filter(quiz_id__in=quiz_ids)
    found: dict[int, dict] = {}
    by_quiz: dict[int, list[tuple[int, int, bool]]] = defaultdict(list)
    for quiz_id, member_id, percent, passed in rows.values_list(
        "quiz_id", "membership_id", "percent", "passed"
    ):
        by_quiz[quiz_id].append((member_id, percent or 0, bool(passed)))
    for quiz_id in quiz_ids:
        attempts = by_quiz.get(quiz_id, [])
        taken = {member_id for member_id, _p, _ok in attempts}
        passed = {member_id for member_id, _p, ok in attempts if ok}
        found[quiz_id] = {
            "attempts": len(attempts),
            "people": len(taken),
            "passed_people": len(passed),
            "pass_rate": math.floor(len(passed) / len(taken) * 100) if taken else None,
            "average": math.floor(sum(p for _m, p, _ok in attempts) / len(attempts) + 0.5)
            if attempts
            else None,
        }
    return found


def quiz_row(quiz: Quiz, stats: dict) -> dict:
    return {
        "id": quiz.pk,
        "title": quiz.title,
        "emoji": quiz.emoji,
        "description": quiz.description,
        "status": quiz.status,
        "mode": quiz.mode,
        "question_count": quiz.question_count,
        "questions": quizzes.available(quiz),
        "topics": [topic_ref(topic) for topic in quiz.topics.all()],
        "pass_percent": quiz.pass_percent,
        "time_limit_seconds": quiz.time_limit_seconds,
        "max_attempts": quiz.max_attempts,
        "attempts": stats["attempts"],
        "people": stats["people"],
        "pass_rate": stats["pass_rate"],
        "average": stats["average"],
        "updated_at": quiz.updated_at,
    }


def quiz_detail(quiz: Quiz, stats: dict) -> dict:
    return quiz_row(quiz, stats) | {
        "shuffle_questions": quiz.shuffle_questions,
        "shuffle_options": quiz.shuffle_options,
        "retry_after_minutes": quiz.retry_after_minutes,
        "partial_credit": quiz.partial_credit,
        "show_answers": quiz.show_answers,
        "audience_all": quiz.audience_all,
        "position_ids": sorted(quiz.positions.values_list("pk", flat=True)),
        "topic_ids": sorted(quiz.topics.values_list("pk", flat=True)),
        "question_ids": list(
            QuizQuestion.objects.filter(quiz=quiz)
            .order_by("position", "pk")
            .values_list("question_id", flat=True)
        ),
        "in_courses": quiz.steps.count(),
        "in_checks": quiz.checks.exclude(state=RegularCheck.State.ARCHIVED).count(),
    }


def preview(quiz: Quiz, member: Membership, user) -> list[dict]:
    """A draw as a learner would get it, with the right answers (for the manager)."""
    rows = []
    for question in quizzes.draw(quiz, member):
        order = grading.shown_order(question.kind, question.data, shuffle=quiz.shuffle_options)
        rows.append(
            {
                "question": grading.play(
                    question, order, image_url=quizzes.image_url(question.image, user)
                ),
                "right_answer": grading.right_answer(question.kind, question.data, order),
                "explanation": question.explanation,
            }
        )
    return rows


def results(
    quiz: Quiz,
    *,
    branch_ids: list[int] | None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict:
    """The quiz's results among the people the viewer sees: the attempts (newest first), the
    score distribution, the hardest questions (lowest share answered right)."""
    rows = (
        Attempt.objects.filter(quiz=quiz, trial=False)
        .exclude(state=Attempt.State.ABANDONED)
        .select_related("membership__user", "membership__position")
    )
    if branch_ids is not None:
        rows = rows.filter(membership__in=people(quiz.company, branch_ids=branch_ids))
    if start is not None:
        rows = rows.filter(started_at__gte=start)
    if end is not None:
        rows = rows.filter(started_at__lt=end)
    attempts = list(rows.order_by("-started_at", "-pk")[:RESULTS_LIMIT])
    finished = [attempt for attempt in attempts if attempt.state in DONE]
    distribution = [
        {"start": index * 10, "end": 100 if index == BUCKETS - 1 else index * 10 + 9, "count": 0}
        for index in range(BUCKETS)
    ]
    for attempt in finished:
        distribution[min((attempt.percent or 0) // 10, BUCKETS - 1)]["count"] += 1
    taken = {attempt.membership_id for attempt in finished}
    passed = {attempt.membership_id for attempt in finished if attempt.passed}
    logs = (
        AnswerLog.objects.filter(attempt__in=[attempt.pk for attempt in finished])
        .values("question_id", "question__text", "question__kind")
        .annotate(answered=Count("pk"), right=Count("pk", filter=Q(correct=True)))
    )
    hardest = sorted(
        (
            {
                "id": row["question_id"],
                "text": row["question__text"],
                "kind": row["question__kind"],
                "answered": row["answered"],
                "correct": row["right"],
                "percent": math.floor(row["right"] / row["answered"] * 100),
            }
            for row in logs
        ),
        key=lambda row: (row["percent"], -row["answered"]),
    )[:HARDEST]
    return {
        "summary": {
            "attempts": len(finished),
            "people": len(taken),
            "passed_people": len(passed),
            "pass_rate": math.floor(len(passed) / len(taken) * 100) if taken else None,
            "average": math.floor(sum(a.percent or 0 for a in finished) / len(finished) + 0.5)
            if finished
            else None,
        },
        "attempts": [
            {
                "id": attempt.pk,
                "member": person(attempt.membership),
                "number": attempt.number,
                "state": attempt.state,
                "started_at": attempt.started_at,
                "finished_at": attempt.finished_at,
                "percent": attempt.percent,
                "passed": attempt.passed,
                "score": float(attempt.score) if attempt.score is not None else None,
                "max_score": float(attempt.max_score) if attempt.max_score is not None else None,
                "reset": attempt.reset_at is not None,
                "check": attempt.check_entry_id is not None,
            }
            for attempt in attempts
        ],
        "distribution": distribution,
        "hardest": hardest,
    }


# Checks ------------------------------------------------------------------------------------


def round_row(round_: CheckRound, *, branch_ids: list[int] | None) -> dict:
    entries = round_.entries.select_related("attempt")
    if branch_ids is not None:
        entries = entries.filter(membership__in=people(round_.company, branch_ids=branch_ids))
    entries = list(entries)
    return {
        "id": round_.pk,
        "starts_at": round_.starts_at,
        "due_at": round_.due_at,
        "closed_at": round_.closed_at,
        "people": len(entries),
        "done": sum(1 for entry in entries if entry.attempt_id),
        "passed": sum(1 for entry in entries if entry.attempt and entry.attempt.passed),
    }


def round_detail(round_: CheckRound, *, branch_ids: list[int] | None) -> dict:
    entries = round_.entries.select_related(
        "attempt", "membership__user", "membership__position"
    ).order_by("membership__first_name", "membership__last_name", "pk")
    if branch_ids is not None:
        entries = entries.filter(membership__in=people(round_.company, branch_ids=branch_ids))
    entries = list(entries)
    found = checks.facts(round_, entries)
    return round_row(round_, branch_ids=branch_ids) | {
        "entries": [
            {
                "id": entry.pk,
                "member": person(entry.membership),
                "done": entry.attempt_id is not None,
                "passed": bool(entry.attempt.passed) if entry.attempt_id else None,
                "percent": entry.attempt.percent if entry.attempt_id else None,
                "attempt_id": entry.attempt_id,
                "reminded_at": entry.reminded_at,
            }
            for entry in entries
        ],
        "weakest": found["weakest"],
    }


def check_row(check: RegularCheck, *, branch_ids: list[int] | None) -> dict:
    last = check.rounds.order_by("-starts_at").first()
    return {
        "id": check.pk,
        "title": check.title,
        "quiz": ref(check.quiz),
        "state": check.state,
        "every": check.every,
        "weekday": check.weekday,
        "month_day": check.month_day,
        "at": check.at,
        "answer_within_hours": check.answer_within_hours,
        "audience_all": check.audience_all,
        "position_ids": sorted(check.positions.values_list("pk", flat=True)),
        "branch_ids": sorted(check.branches.values_list("pk", flat=True)),
        "next_run_at": check.next_run_at if check.state == RegularCheck.State.ACTIVE else None,
        "last_round": round_row(last, branch_ids=branch_ids) if last else None,
    }


# Skills ------------------------------------------------------------------------------------


def matrix_shape(found: dict) -> dict:
    return {
        "topics": [
            {
                "id": column["topic"].pk,
                "name": column["topic"].name,
                "color": column["topic"].color,
                "average": column["average"],
                "rated": column["rated"],
                "weak": column["weak"],
                "strong": column["strong"],
            }
            for column in found["topics"]
        ],
        "people": [
            {
                "member": person(row["member"]),
                "average": row["average"],
                "answers": row["answers"],
                "cells": {str(topic_id): cell for topic_id, cell in row["cells"].items()},
            }
            for row in found["people"]
        ],
    }


def person_skills(member: Membership, now: datetime | None = None) -> dict:
    """One person's learning in numbers: mastery by topic, recent attempts, daily answers."""
    now = now or timezone.now()
    attempts = (
        Attempt.objects.filter(membership=member, trial=False, state__in=DONE)
        .select_related("quiz")
        .order_by("-finished_at")[:20]
    )
    daily = DailyQuestion.objects.filter(membership=member, sent_at__gte=now - timedelta(days=30))
    return {
        "member": person(member),
        "topics": [
            {
                "topic": topic_ref(row["topic"]),
                "score": row["score"],
                "answers": row["answers"],
                "band": row["band"],
                "last_at": row["last_at"],
            }
            for row in skills.of_person(member)
        ],
        "attempts": [
            {
                "id": attempt.pk,
                "quiz": ref(attempt.quiz),
                "state": attempt.state,
                "percent": attempt.percent,
                "passed": attempt.passed,
                "finished_at": attempt.finished_at,
                "check": attempt.check_entry_id is not None,
            }
            for attempt in attempts
        ],
        "daily": {
            "asked": daily.count(),
            "answered": daily.filter(answered_at__isnull=False).count(),
            "right": daily.filter(correct=True).count(),
        },
    }


# Suggestions and drafts ---------------------------------------------------------------------


def suggestion_row(row: TutorSuggestion) -> dict:
    return {
        "id": row.pk,
        "kind": row.kind,
        "state": row.state,
        "member": person(row.membership) if row.membership_id else None,
        "topic": topic_ref(row.topic) if row.topic_id else None,
        "course": ref(row.course) if row.course_id else None,
        "score": row.score,
        "params": row.params or {},
        "text": suggestions.text(row),
        "created_at": row.created_at,
        "decided_at": row.decided_at,
    }


def draft_row(job: QuestionDraftJob) -> dict:
    return {
        "id": job.pk,
        "state": job.state,
        "engine": job.engine,
        "page": ref(job.page) if job.page_id else None,
        "lesson": ref(job.lesson) if job.lesson_id else None,
        "topic": topic_ref(job.topic) if job.topic_id else None,
        "count": job.count,
        "kinds": list(job.kinds or []),
        "difficulty": job.difficulty,
        "made": job.made,
        "dropped": job.dropped,
        "error": job.error,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
    }
