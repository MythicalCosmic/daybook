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
from apps.learning.models import (
    Assignment,
    Course,
    CourseStep,
    Lesson,
    LessonProgress,
    Status,
    Video,
)
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


# Owner: inputs --------------------------------------------------------------------------


class LearningCourseWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    emoji = serializers.CharField(max_length=16, required=False, allow_blank=True)
    color = serializers.CharField(max_length=16, required=False, allow_blank=True)
    description = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    mandatory = serializers.BooleanField(required=False)
    audience_all = serializers.BooleanField(required=False)
    position_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    branch_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    due_days = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    renew_months = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    sequential = serializers.BooleanField(required=False)
    certificate = serializers.BooleanField(required=False)

    class Meta:
        ref_name = "LearningCourseWrite"


class LearningStepWriteSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=CourseStep.Kind.choices)
    target_id = serializers.IntegerField(min_value=1)
    required = serializers.BooleanField(required=False, default=True)

    class Meta:
        ref_name = "LearningStepWrite"


class LearningStepUpdateSerializer(serializers.Serializer):
    required = serializers.BooleanField()

    class Meta:
        ref_name = "LearningStepUpdate"


class LearningIdsSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(), max_length=500)

    class Meta:
        ref_name = "LearningIds"


class LearningAssignSerializer(serializers.Serializer):
    member_ids = serializers.ListField(
        child=serializers.IntegerField(), min_length=1, max_length=500
    )
    due_on = serializers.DateField(
        required=False, allow_null=True, help_text="The company's date; the end of that day."
    )

    class Meta:
        ref_name = "LearningAssign"


class LearningRemindSerializer(serializers.Serializer):
    member_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_null=True, max_length=500
    )

    class Meta:
        ref_name = "LearningRemind"


class LearningExemptSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=200)

    class Meta:
        ref_name = "LearningExempt"


class LearningDueSerializer(serializers.Serializer):
    due_on = serializers.DateField(
        allow_null=True, help_text="The company's date (the end of that day); null: no deadline."
    )

    class Meta:
        ref_name = "LearningDue"


class LearningLessonWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    emoji = serializers.CharField(max_length=16, required=False, allow_blank=True)
    summary = serializers.CharField(max_length=300, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    source = serializers.ChoiceField(choices=Lesson.Source.choices, required=False)
    video_id = serializers.IntegerField(required=False, allow_null=True)
    youtube = serializers.CharField(
        max_length=300, required=False, allow_blank=True, help_text="A link or the video id."
    )
    topic_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    audience_all = serializers.BooleanField(required=False)
    position_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    transcript = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)

    class Meta:
        ref_name = "LearningLessonWrite"


class LearningVideoStartSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=300, allow_blank=True, required=False, default="")
    size = serializers.IntegerField(min_value=1, help_text="Bytes.")

    class Meta:
        ref_name = "LearningVideoStart"


class LearningSettingsSerializer(serializers.Serializer):
    completion_percent = serializers.IntegerField(min_value=50, max_value=100)
    max_speed_percent = serializers.IntegerField(min_value=100, max_value=400)
    remind_before_days = serializers.IntegerField(min_value=0, max_value=30)
    escalate_after_days = serializers.IntegerField(min_value=0, max_value=60)
    certificates = serializers.BooleanField()
    certificate_prefix = serializers.RegexField(r"^[A-Za-z0-9]{1,8}$", max_length=8)
    next_certificate_number = serializers.IntegerField(read_only=True)
    catalog_for_staff = serializers.BooleanField()
    storage_limit_mb = serializers.IntegerField(min_value=100, max_value=1_000_000)
    storage_used_bytes = serializers.IntegerField(read_only=True)

    class Meta:
        ref_name = "LearningSettings"


# Owner: shapes --------------------------------------------------------------------------


class LearningPersonRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    photo_url = serializers.CharField(allow_null=True)
    position = serializers.CharField(allow_null=True)
    branch = serializers.CharField(allow_null=True)

    class Meta:
        ref_name = "LearningPersonRef"


class LearningRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()

    class Meta:
        ref_name = "LearningRef"


class LearningStatsSerializer(serializers.Serializer):
    people = serializers.IntegerField()
    completed = serializers.IntegerField()
    in_progress = serializers.IntegerField()
    overdue = serializers.IntegerField()
    percent = serializers.IntegerField()

    class Meta:
        ref_name = "LearningStats"


class LearningOwnerCourseRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    emoji = serializers.CharField()
    color = serializers.CharField()
    status = serializers.ChoiceField(choices=Status.choices)
    mandatory = serializers.BooleanField()
    steps = serializers.IntegerField()
    minutes = serializers.IntegerField()
    due_days = serializers.IntegerField(allow_null=True)
    renew_months = serializers.IntegerField(allow_null=True)
    updated_at = serializers.DateTimeField()
    stats = LearningStatsSerializer()

    class Meta:
        ref_name = "LearningOwnerCourseRow"


class LearningStepTargetSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    emoji = serializers.CharField()
    status = serializers.CharField(help_text="draft, published or archived.")
    minutes = serializers.IntegerField(allow_null=True)

    class Meta:
        ref_name = "LearningStepTarget"


class LearningOwnerStepSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=CourseStep.Kind.choices)
    position = serializers.IntegerField()
    required = serializers.BooleanField()
    target = LearningStepTargetSerializer()

    class Meta:
        ref_name = "LearningOwnerStep"


class LearningOwnerCourseSerializer(LearningOwnerCourseRowSerializer):
    description = serializers.CharField()
    audience_all = serializers.BooleanField()
    positions = LearningRefSerializer(many=True)
    branches = LearningRefSerializer(many=True)
    sequential = serializers.BooleanField()
    certificate = serializers.BooleanField()
    published_at = serializers.DateTimeField(allow_null=True)
    archived_at = serializers.DateTimeField(allow_null=True)
    step_list = LearningOwnerStepSerializer(many=True)

    class Meta:
        ref_name = "LearningOwnerCourse"


class LearningAssignmentRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    state = serializers.ChoiceField(choices=Assignment.State.choices)
    source = serializers.ChoiceField(choices=Assignment.Source.choices)
    cycle = serializers.IntegerField()
    percent = serializers.IntegerField()
    steps_done = serializers.IntegerField()
    steps_total = serializers.IntegerField()
    assigned_at = serializers.DateTimeField()
    due_at = serializers.DateTimeField(allow_null=True)
    late = serializers.BooleanField()
    days_late = serializers.IntegerField()
    started_at = serializers.DateTimeField(allow_null=True)
    last_activity_at = serializers.DateTimeField(allow_null=True)
    completed_at = serializers.DateTimeField(allow_null=True)
    certificate_no = serializers.CharField()
    expires_at = serializers.DateTimeField(allow_null=True)
    exempt_reason = serializers.CharField()

    class Meta:
        ref_name = "LearningAssignmentRow"


class LearningCoursePersonSerializer(serializers.Serializer):
    assignment = LearningAssignmentRowSerializer()
    member = LearningPersonRefSerializer()

    class Meta:
        ref_name = "LearningCoursePerson"


class LearningCoursePeopleSerializer(serializers.Serializer):
    counts = serializers.DictField(child=serializers.IntegerField())
    results = LearningCoursePersonSerializer(many=True)

    class Meta:
        ref_name = "LearningCoursePeople"


class LearningCandidateSerializer(LearningPersonRefSerializer):
    assigned = serializers.BooleanField(help_text="Has this course open or still valid.")

    class Meta:
        ref_name = "LearningCandidate"


class LearningCountSerializer(serializers.Serializer):
    count = serializers.IntegerField()

    class Meta:
        ref_name = "LearningCount"


class LearningTopicRefOwnerSerializer(LearningTopicRefSerializer):
    class Meta:
        ref_name = "LearningOwnerTopicRef"


class LearningVideoSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    state = serializers.ChoiceField(choices=Video.State.choices)
    error = serializers.CharField()
    original_name = serializers.CharField()
    original_bytes = serializers.IntegerField()
    received_bytes = serializers.IntegerField()
    chunk_bytes = serializers.IntegerField()
    size_bytes = serializers.IntegerField()
    duration_seconds = serializers.IntegerField()
    width = serializers.IntegerField()
    height = serializers.IntegerField()
    url = serializers.CharField(allow_null=True, help_text="Signed, valid 6 hours.")
    poster_url = serializers.CharField(allow_null=True, help_text="Signed, valid 6 hours.")
    upload_expires_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()
    lessons = LearningRefSerializer(many=True)

    class Meta:
        ref_name = "LearningVideo"


class LearningChunkResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    state = serializers.ChoiceField(choices=Video.State.choices)
    received_bytes = serializers.IntegerField()
    original_bytes = serializers.IntegerField()

    class Meta:
        ref_name = "LearningChunkResult"


class LearningViewerCountsSerializer(serializers.Serializer):
    watched = serializers.IntegerField()
    watching = serializers.IntegerField()

    class Meta:
        ref_name = "LearningViewerCounts"


class LearningOwnerLessonRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    emoji = serializers.CharField()
    status = serializers.ChoiceField(choices=Status.choices)
    source = serializers.ChoiceField(choices=Lesson.Source.choices)
    duration_seconds = serializers.IntegerField()
    video_state = serializers.CharField(allow_null=True)
    topics = LearningTopicRefOwnerSerializer(many=True)
    viewers = LearningViewerCountsSerializer()
    updated_at = serializers.DateTimeField()
    published_at = serializers.DateTimeField(allow_null=True)

    class Meta:
        ref_name = "LearningOwnerLessonRow"


class LearningOwnerLessonSerializer(LearningOwnerLessonRowSerializer):
    summary = serializers.CharField()
    notes = serializers.CharField()
    youtube_id = serializers.CharField()
    video = LearningVideoSerializer(allow_null=True)
    transcript = serializers.CharField()
    audience_all = serializers.BooleanField()
    positions = LearningRefSerializer(many=True)
    archived_at = serializers.DateTimeField(allow_null=True)
    courses = LearningRefSerializer(many=True)

    class Meta:
        ref_name = "LearningOwnerLesson"


class LearningViewerSerializer(serializers.Serializer):
    member = LearningPersonRefSerializer()
    state = serializers.ChoiceField(choices=["never", "watching", "watched"])
    percent = serializers.IntegerField()
    ranges = serializers.ListField(child=serializers.ListField(child=serializers.IntegerField()))
    watched_seconds = serializers.IntegerField()
    spent_seconds = serializers.IntegerField()
    sessions = serializers.IntegerField()
    first_at = serializers.DateTimeField(allow_null=True)
    last_at = serializers.DateTimeField(allow_null=True)
    completed_at = serializers.DateTimeField(allow_null=True)

    class Meta:
        ref_name = "LearningViewer"


class LearningViewersSerializer(serializers.Serializer):
    counts = serializers.DictField(child=serializers.IntegerField())
    duration_seconds = serializers.IntegerField()
    results = LearningViewerSerializer(many=True)

    class Meta:
        ref_name = "LearningViewers"


class LearningLateSerializer(serializers.Serializer):
    member = LearningPersonRefSerializer()
    course = serializers.DictField(help_text="{id, title}")
    due_at = serializers.DateTimeField()
    days_late = serializers.IntegerField()

    class Meta:
        ref_name = "LearningLate"


class LearningActivityDaySerializer(serializers.Serializer):
    day = serializers.DateField()
    seconds = serializers.IntegerField()
    lessons = serializers.IntegerField()
    courses = serializers.IntegerField()

    class Meta:
        ref_name = "LearningActivityDay"


class LearningOverviewCourseSerializer(LearningStatsSerializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    emoji = serializers.CharField()
    color = serializers.CharField()
    mandatory = serializers.BooleanField()

    class Meta:
        ref_name = "LearningOverviewCourse"


class LearningOverviewSerializer(serializers.Serializer):
    compliance = serializers.DictField(
        child=serializers.IntegerField(),
        help_text="{people, completed, overdue_people, percent}: mandatory training.",
    )
    late = LearningLateSerializer(many=True)
    watched_week_seconds = serializers.IntegerField()
    activity = LearningActivityDaySerializer(many=True)
    courses = LearningOverviewCourseSerializer(many=True)
    counts = serializers.DictField(child=serializers.IntegerField())

    class Meta:
        ref_name = "LearningOverview"


class LearningGridCourseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    emoji = serializers.CharField()
    color = serializers.CharField()

    class Meta:
        ref_name = "LearningGridCourse"


class LearningGridRowSerializer(serializers.Serializer):
    member = LearningPersonRefSerializer()
    cells = serializers.DictField(
        child=serializers.DictField(allow_null=True),
        help_text="{course id: {assignment_id, state, percent, due_at, late} | null}",
    )
    done = serializers.IntegerField()
    total = serializers.IntegerField()
    late = serializers.IntegerField()

    class Meta:
        ref_name = "LearningGridRow"


class LearningPeopleGridSerializer(serializers.Serializer):
    courses = LearningGridCourseSerializer(many=True)
    rows = LearningGridRowSerializer(many=True)

    class Meta:
        ref_name = "LearningPeopleGrid"


class LearningPersonPageSerializer(serializers.Serializer):
    member = LearningPersonRefSerializer()
    summary = serializers.DictField(child=serializers.IntegerField())
    assignments = serializers.ListField(child=serializers.DictField())
    lessons = serializers.ListField(child=serializers.DictField())
    pages = serializers.ListField(child=serializers.DictField())

    class Meta:
        ref_name = "LearningPersonPage"


class LearningFileLinkSerializer(serializers.Serializer):
    url = serializers.CharField()
    name = serializers.CharField()
    expires_in = serializers.IntegerField()

    class Meta:
        ref_name = "LearningFileLink"


class LearningPickSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    emoji = serializers.CharField()
    status = serializers.CharField()

    class Meta:
        ref_name = "LearningPick"


# Owner: building the shapes -------------------------------------------------------------


def target_json(step: CourseStep) -> dict:
    target = step.lesson or step.page or step.quiz
    if step.kind == CourseStep.Kind.PAGE:
        status = (
            Status.ARCHIVED
            if target.archived_at
            else (Status.PUBLISHED if target.published else Status.DRAFT)
        )
    else:
        status = target.status
    return {
        "id": target.pk,
        "title": target.title,
        "emoji": target.emoji,
        "status": status,
        "minutes": step_minutes(step),
    }


def owner_course_row(course: Course, stats: dict) -> dict:
    card = course_card(course)
    return {
        "id": course.pk,
        "title": course.title,
        "emoji": course.emoji,
        "color": course.color,
        "status": course.status,
        "mandatory": course.mandatory,
        "steps": card["steps"],
        "minutes": card["minutes"],
        "due_days": course.due_days,
        "renew_months": course.renew_months,
        "updated_at": course.updated_at,
        "stats": stats,
    }


def owner_course(course: Course, stats: dict) -> dict:
    return {
        **owner_course_row(course, stats),
        "description": course.description,
        "audience_all": course.audience_all,
        "positions": [{"id": row.pk, "name": row.name} for row in course.positions.all()],
        "branches": [{"id": row.pk, "name": row.name} for row in course.branches.all()],
        "sequential": course.sequential,
        "certificate": course.certificate,
        "published_at": course.published_at,
        "archived_at": course.archived_at,
        "step_list": [
            {
                "id": step.pk,
                "kind": step.kind,
                "position": step.position,
                "required": step.required,
                "target": target_json(step),
            }
            for step in course.steps.all()
        ],
    }


def video_json(video: Video, *, user) -> dict:
    links = media.links(video, user=user) or {}
    return {
        "id": video.pk,
        "state": video.state,
        "error": video.error,
        "original_name": video.original_name,
        "original_bytes": video.original_bytes,
        "received_bytes": video.received_bytes,
        "chunk_bytes": media.CHUNK_BYTES,
        "size_bytes": video.size_bytes,
        "duration_seconds": video.duration_seconds,
        "width": video.width,
        "height": video.height,
        "url": links.get("url"),
        "poster_url": links.get("poster_url"),
        "upload_expires_at": video.upload_expires_at,
        "created_at": video.created_at,
        "lessons": [{"id": row.pk, "name": row.title} for row in video.lessons.all()],
    }


def owner_lesson_row(lesson: Lesson, viewers: dict) -> dict:
    return {
        "id": lesson.pk,
        "title": lesson.title,
        "emoji": lesson.emoji,
        "status": lesson.status,
        "source": lesson.source,
        "duration_seconds": lesson.duration_seconds,
        "video_state": lesson.video.state if lesson.video_id else None,
        "topics": [
            {"id": topic.pk, "name": topic.name, "color": topic.color}
            for topic in lesson.topics.all()
        ],
        "viewers": viewers or {"watched": 0, "watching": 0},
        "updated_at": lesson.updated_at,
        "published_at": lesson.published_at,
    }


def owner_lesson(lesson: Lesson, viewers: dict, *, user) -> dict:
    courses = {step.course_id: step.course for step in lesson.steps.select_related("course")}
    return {
        **owner_lesson_row(lesson, viewers),
        "summary": lesson.summary,
        "notes": lesson.notes,
        "youtube_id": lesson.youtube_id,
        "video": video_json(lesson.video, user=user) if lesson.video_id else None,
        "transcript": lesson.transcript,
        "audience_all": lesson.audience_all,
        "positions": [{"id": row.pk, "name": row.name} for row in lesson.positions.all()],
        "archived_at": lesson.archived_at,
        "courses": [{"id": course.pk, "name": course.title} for course in courses.values()],
    }
