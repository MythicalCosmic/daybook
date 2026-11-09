"""Shapes of package Q1's API (courses, lessons, videos, who watched what).

The employee shapes are the contract with the mini app (docs/PLAN-LEARNING.md §13 Q1): the
serializers document them for the schema, and the `*_card` / `*_json` functions build them.
Times are ISO in UTC.
"""

from __future__ import annotations

import math
from datetime import datetime

from rest_framework import serializers

from apps.learning import certificates, conf, lessons, media, queries
from apps.learning.models import Assignment, Course, CourseStep, Lesson, LessonProgress
from apps.members.models import Membership

WORDS_PER_MINUTE = 180
CHARS_PER_WORD = 6


# Employee: cards ------------------------------------------------------------------------


class LearningCourseCardSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    emoji = serializers.CharField()
    color = serializers.CharField()
    description = serializers.CharField()
    mandatory = serializers.BooleanField()
    steps = serializers.IntegerField(help_text="How many steps.")
    minutes = serializers.IntegerField(help_text="About how long the course takes.")

    class Meta:
        ref_name = "LearningCourseCard"


class LearningAssignmentCardSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    state = serializers.ChoiceField(choices=Assignment.State.choices)
    percent = serializers.IntegerField()
    steps_done = serializers.IntegerField()
    steps_total = serializers.IntegerField()
    due_at = serializers.DateTimeField(allow_null=True)
    late = serializers.BooleanField()
    completed_at = serializers.DateTimeField(allow_null=True)
    certificate_url = serializers.CharField(
        allow_null=True, help_text="A signed link to the certificate PDF."
    )
    course = LearningCourseCardSerializer()

    class Meta:
        ref_name = "LearningAssignmentCard"


class LearningHomeSerializer(serializers.Serializer):
    todo = LearningAssignmentCardSerializer(many=True)
    done = LearningAssignmentCardSerializer(many=True, help_text="The newest 20.")
    catalog = LearningCourseCardSerializer(many=True)
    certificates = serializers.IntegerField()

    class Meta:
        ref_name = "LearningHome"


class LearningStepSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=CourseStep.Kind.choices)
    title = serializers.CharField()
    emoji = serializers.CharField()
    required = serializers.BooleanField()
    done = serializers.BooleanField()
    locked = serializers.BooleanField()
    done_at = serializers.DateTimeField(allow_null=True)
    lesson_id = serializers.IntegerField(allow_null=True)
    page_id = serializers.IntegerField(allow_null=True)
    quiz_id = serializers.IntegerField(allow_null=True)
    minutes = serializers.IntegerField(allow_null=True)
    best_percent = serializers.IntegerField(
        allow_null=True,
        help_text="A quiz: the best finished attempt. A lesson: how much of it was watched.",
    )

    class Meta:
        ref_name = "LearningStep"


class LearningCourseDetailSerializer(LearningCourseCardSerializer):
    sequential = serializers.BooleanField()
    certificate = serializers.BooleanField()
    assignment = LearningAssignmentCardSerializer(allow_null=True)
    can_start = serializers.BooleanField()
    steps = LearningStepSerializer(many=True)

    class Meta:
        ref_name = "LearningCourseDetail"


# Employee: lessons ----------------------------------------------------------------------


class LearningVideoLinksSerializer(serializers.Serializer):
    url = serializers.CharField(help_text="Signed, valid 6 hours.")
    poster_url = serializers.CharField(allow_null=True, help_text="Signed, valid 6 hours.")
    duration_seconds = serializers.IntegerField()
    width = serializers.IntegerField()
    height = serializers.IntegerField()

    class Meta:
        ref_name = "LearningVideoLinks"


class LearningTopicRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    color = serializers.CharField()

    class Meta:
        ref_name = "LearningTopicRef"


class LearningMyProgressSerializer(serializers.Serializer):
    percent = serializers.IntegerField()
    position = serializers.IntegerField()
    completed_at = serializers.DateTimeField(allow_null=True)
    ranges = serializers.ListField(
        child=serializers.ListField(child=serializers.IntegerField(), min_length=2, max_length=2)
    )

    class Meta:
        ref_name = "LearningMyProgress"


class LearningNextStepSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=CourseStep.Kind.choices)
    id = serializers.IntegerField(help_text="The lesson's, page's or quiz's id.")
    title = serializers.CharField()

    class Meta:
        ref_name = "LearningNextStep"


class LearningLessonPlaySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    emoji = serializers.CharField()
    summary = serializers.CharField()
    notes_html = serializers.CharField()
    source = serializers.ChoiceField(choices=Lesson.Source.choices)
    video = LearningVideoLinksSerializer(allow_null=True)
    youtube_id = serializers.CharField()
    duration_seconds = serializers.IntegerField()
    processing = serializers.BooleanField()
    topics = LearningTopicRefSerializer(many=True)
    completion_percent = serializers.IntegerField()
    progress = LearningMyProgressSerializer(allow_null=True)
    next = LearningNextStepSerializer(allow_null=True)

    class Meta:
        ref_name = "LearningLessonPlay"


class LearningProgressReportSerializer(serializers.Serializer):
    session = serializers.CharField(max_length=40, help_text="A random id per opening.")
    position = serializers.FloatField(min_value=0)
    duration = serializers.FloatField(min_value=0, required=False, default=0)
    ranges = serializers.ListField(
        child=serializers.ListField(child=serializers.FloatField(), min_length=2, max_length=2),
        max_length=50,
        required=False,
        default=list,
        help_text="What was played since the previous report, in media seconds.",
    )
    playing = serializers.BooleanField(required=False, default=False)

    class Meta:
        ref_name = "LearningProgressReport"


class LearningProgressResultSerializer(serializers.Serializer):
    percent = serializers.IntegerField()
    position = serializers.IntegerField()
    completed = serializers.BooleanField()
    completed_now = serializers.BooleanField()
    points = serializers.IntegerField(allow_null=True)

    class Meta:
        ref_name = "LearningProgressResult"


# Building the cards ---------------------------------------------------------------------


def step_minutes(step: CourseStep) -> int | None:
    """About how long a step takes, in minutes (None while a lesson's length is unknown)."""
    if step.kind == CourseStep.Kind.LESSON:
        seconds = step.lesson.duration_seconds if step.lesson_id else 0
        return math.ceil(seconds / 60) if seconds else None
    if step.kind == CourseStep.Kind.PAGE:
        chars = getattr(step, "page_chars", None)
        if chars is None:
            chars = len(step.page.body_text or "")
        return max(1, math.ceil(chars / CHARS_PER_WORD / WORDS_PER_MINUTE))
    quiz = step.quiz
    if quiz.time_limit_seconds:
        return max(1, math.ceil(quiz.time_limit_seconds / 60))
    questions = quiz.question_count if quiz.mode == quiz.Mode.RANDOM else len(quiz.items.all())
    return max(1, questions)


def course_card(course: Course) -> dict:
    steps = list(course.steps.all())
    return {
        "id": course.pk,
        "title": course.title,
        "emoji": course.emoji,
        "color": course.color,
        "description": course.description,
        "mandatory": course.mandatory,
        "steps": len(steps),
        "minutes": sum(step_minutes(step) or 0 for step in steps),
    }


class CertificateLinks:
    """Signed certificate links for one response; a PDF not made yet is made now, a few at
    most per response (they are made when a course is finished, so this is rare)."""

    def __init__(self, user, *, budget: int = 3):
        self.user = user
        self.budget = budget

    def __call__(self, assignment: Assignment) -> str | None:
        if assignment.state != Assignment.State.COMPLETED or not assignment.certificate_no:
            return None
        if not assignment.certificate_file and self.budget > 0:
            self.budget -= 1
            try:
                certificates.ensure_pdf(assignment)
                assignment.refresh_from_db(fields=["certificate_file"])
            except Exception:  # a broken render never breaks the page
                return None
        return certificates.link(assignment, user=self.user)


def assignment_card(assignment: Assignment, *, links: CertificateLinks, now: datetime) -> dict:
    return {
        "id": assignment.pk,
        "state": assignment.state,
        "percent": assignment.percent,
        "steps_done": assignment.steps_done,
        "steps_total": assignment.steps_total,
        "due_at": assignment.due_at,
        "late": queries.is_late(assignment, now),
        "completed_at": assignment.completed_at,
        "certificate_url": links(assignment),
        "course": course_card(assignment.course),
    }


def step_json(state: queries.StepState, best: dict[tuple[str, int], int]) -> dict:
    step = state.step
    target = step.lesson or step.page or step.quiz
    if step.kind == CourseStep.Kind.QUIZ:
        best_percent = best.get(("quiz", step.quiz_id))
    elif step.kind == CourseStep.Kind.LESSON:
        best_percent = best.get(("lesson", step.lesson_id))
    else:
        best_percent = None
    return {
        "id": step.pk,
        "kind": step.kind,
        "title": target.title,
        "emoji": target.emoji,
        "required": step.required,
        "done": state.done,
        "locked": state.locked,
        "done_at": state.done_at,
        "lesson_id": step.lesson_id,
        "page_id": step.page_id,
        "quiz_id": step.quiz_id,
        "minutes": step_minutes(step),
        "best_percent": best_percent,
    }


def lesson_json(lesson: Lesson, member: Membership, *, user, next_step: dict | None = None) -> dict:
    row = LessonProgress.objects.filter(lesson=lesson, membership=member).first()
    return {
        "id": lesson.pk,
        "title": lesson.title,
        "emoji": lesson.emoji,
        "summary": lesson.summary,
        "notes_html": lesson.notes,
        "source": lesson.source,
        "video": media.links(lesson.video, user=user)
        if lesson.source == Lesson.Source.UPLOAD
        else None,
        "youtube_id": lesson.youtube_id,
        "duration_seconds": lesson.duration_seconds,
        "processing": lessons.processing(lesson),
        "topics": [
            {"id": topic.pk, "name": topic.name, "color": topic.color}
            for topic in lesson.topics.all()
        ],
        "completion_percent": conf.get_settings(lesson.company).completion_percent,
        "progress": {
            "percent": row.percent,
            "position": row.position,
            "completed_at": row.completed_at,
            "ranges": row.ranges,
        }
        if row is not None
        else None,
        "next": next_step,
    }
