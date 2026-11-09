"""Writing questions from a page or a lesson (package Q2; docs/PLAN-LEARNING.md §6).

    job = drafting.create_job(company, by=manager, page_id=7, count=5, kinds=["single"])
    drafting.run_job(job.pk)            # the "ai" queue (tasks.draft_questions)

A manager asks for `count` (1 to 15) questions of some kinds about a page (its text) or a lesson
(notes and transcript); the job writes them as drafts (`state` draft, `source` ai or rules) for
the manager to review, edit and put into use in the bank. The engines come in the next step.
"""

from __future__ import annotations

from django.db import transaction
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.core.exceptions import DomainError
from apps.knowledge import topics as topic_services
from apps.knowledge.models import Page
from apps.learning.audit_actions import QuizAction
from apps.learning.models import Lesson, Question, QuestionDraftJob
from apps.learning.services import ensure_manager
from apps.members.models import Membership

COUNT = (1, 15)


@transaction.atomic
def create_job(
    company,
    *,
    by: Membership | None,
    page_id: int | None = None,
    lesson_id: int | None = None,
    count: int = 5,
    kinds: list[str] | None = None,
    difficulty: str = "",
    topic_id: int | None = None,
    engine: str = "auto",
) -> QuestionDraftJob:
    """Queue a drafting job; the dashboard polls it. `engine` "rules" never asks Claude."""
    from apps.learning import tasks

    ensure_manager(by)
    if bool(page_id) == bool(lesson_id):
        raise DomainError(_("Pick a page or a lesson to write questions from."))
    page = Page.objects.filter(company=company, pk=page_id).first() if page_id else None
    lesson = Lesson.objects.filter(company=company, pk=lesson_id).first() if lesson_id else None
    if (page_id and page is None) or (lesson_id and lesson is None):
        raise DomainError(_("Pick a page or a lesson of this company."))
    if not COUNT[0] <= int(count) <= COUNT[1]:
        raise DomainError(_("Ask for 1–15 questions."))
    kinds = sorted(set(kinds or []))
    if any(kind not in Question.Kind.values for kind in kinds):
        raise DomainError(_("Pick a kind of question."))
    if difficulty and difficulty not in Question.Difficulty.values:
        raise DomainError(_("Pick how hard the question is."))
    topic = topic_services.live_ids(company.pk, [topic_id])[0] if topic_id else None
    job = QuestionDraftJob.objects.create(
        company=company,
        page=page,
        lesson=lesson,
        topic_id=topic,
        count=int(count),
        kinds=kinds,
        difficulty=difficulty,
        engine=QuestionDraftJob.Engine.RULES
        if engine == "rules"
        else QuestionDraftJob.Engine.CLAUDE,
        created_by=by,
    )
    audit.record(
        QuizAction.QUESTIONS_DRAFTED,
        company_id=company.pk,
        actor=by.user if by is not None else None,
        target=job,
        source="page" if page else "lesson",
        count=job.count,
    )
    transaction.on_commit(lambda: tasks.draft_questions.delay(job.pk))
    return job


def run_job(job_id: int) -> int:
    """Run one QuestionDraftJob (the engines come in the next step)."""
    return 0
