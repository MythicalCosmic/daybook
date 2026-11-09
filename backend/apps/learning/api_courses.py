"""Employee (mini app) endpoints of package Q1, routed by `urls_courses.py` under
`/api/v1/companies/<id>/` (docs/PLAN-LEARNING.md §13 Q1; the mini app codes against them):

    GET   learning/                                 my training: to do, done, the catalogue
    GET   learning/courses/{id}/                    a course with my steps
    POST  learning/courses/{id}/start/              start a course meant for me
    GET   learning/lessons/{id}/?course=<id>        a lesson to watch (signed video links)
    POST  learning/lessons/{id}/progress/           the player's report (who watched what)
    GET   learning/assignments/{id}/certificate/    my certificate as a PDF

Everything answers 404 while the company's `learning` module is off. A person only ever sees
their own training.
"""

from __future__ import annotations

from django.db.models import Max, Prefetch, QuerySet
from django.db.models.functions import Length
from django.http import FileResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.storage import SANDBOX_HEADERS
from apps.learning import certificates, conf, courses, progress, queries
from apps.learning.models import (
    LIVE,
    Assignment,
    Attempt,
    Course,
    CourseStep,
    Lesson,
    LessonProgress,
    Status,
)
from apps.learning.serializers_courses import (
    CertificateLinks,
    LearningAssignmentCardSerializer,
    LearningCourseDetailSerializer,
    LearningHomeSerializer,
    LearningLessonPlaySerializer,
    LearningProgressReportSerializer,
    LearningProgressResultSerializer,
    assignment_card,
    course_card,
    lesson_json,
    step_json,
)
from apps.members.api import IsCompanyMember
from apps.members.models import Membership

DONE_LIMIT = 20


class LearningOn(BasePermission):
    """404 while the company's learning module is off (after IsCompanyMember)."""

    def has_permission(self, request, view):
        if not conf.is_on(view.membership.company):
            raise NotFound
        return True


class LearningMemberView(APIView):
    permission_classes = (IsAuthenticated, IsCompanyMember, LearningOn)
    membership: Membership


def _steps() -> QuerySet[CourseStep]:
    """Steps with what a card needs: the targets, a quiz's questions, a page's length."""
    return (
        CourseStep.objects.select_related("lesson", "page", "quiz")
        .prefetch_related("quiz__items")
        .annotate(page_chars=Length("page__body_text"))
        .order_by("position", "pk")
    )


def steps_for_cards() -> Prefetch:
    return Prefetch("steps", queryset=_steps())


def _assignments(member: Membership) -> QuerySet[Assignment]:
    return (
        Assignment.objects.filter(membership=member)
        .select_related("course")
        .prefetch_related(Prefetch("course__steps", queryset=_steps()))
    )


def _member_branches(member: Membership) -> set[int]:
    branches = set(member.branches.values_list("pk", flat=True))
    if member.home_branch_id is not None:
        branches.add(member.home_branch_id)
    return branches


def _in_audience(member: Membership, course: Course, branches: set[int]) -> bool:
    """`queries.in_course_audience` on prefetched positions and branches."""
    if not course.audience_all and member.position_id not in {
        position.pk for position in course.positions.all()
    }:
        return False
    wanted = {branch.pk for branch in course.branches.all()}
    return not wanted or bool(branches & wanted)


def catalog(member: Membership, *, now) -> list[Course]:
    """Courses the person may start now: live, meant for them, none of theirs open or still
    valid; optional ones only while the company lets staff take them on their own."""
    on_own = conf.get_settings(member.company).catalog_for_staff
    current = queries.current_assignments(member.company, [member.pk])
    branches = _member_branches(member)
    rows = (
        Course.objects.filter(company_id=member.company_id)
        .filter(LIVE)
        .prefetch_related("positions", "branches", steps_for_cards())
        .order_by("position", "pk")
    )
    found = []
    for course in rows:
        if not (course.mandatory or on_own):
            continue
        if not _in_audience(member, course, branches):
            continue
        if courses.holds(current.get((course.pk, member.pk)), now):
            continue
        found.append(course)
    return found


def _best(member: Membership, states: list[queries.StepState]) -> dict[tuple[str, int], int]:
    quiz_ids = [state.step.quiz_id for state in states if state.step.quiz_id]
    lesson_ids = [state.step.lesson_id for state in states if state.step.lesson_id]
    best: dict[tuple[str, int], int] = {}
    if quiz_ids:
        rows = (
            Attempt.objects.filter(
                membership=member,
                quiz_id__in=quiz_ids,
                state__in=(Attempt.State.FINISHED, Attempt.State.EXPIRED),
                percent__isnull=False,
            )
            .values("quiz_id")
            .annotate(best=Max("percent"))
        )
        best.update({("quiz", row["quiz_id"]): row["best"] for row in rows})
    if lesson_ids:
        rows = LessonProgress.objects.filter(membership=member, lesson_id__in=lesson_ids)
        best.update({("lesson", row.lesson_id): row.percent for row in rows})
    return best


class HomeView(LearningMemberView):
    """My training: what is open (soonest due first), the newest finished, what I may start."""

    @extend_schema(responses=LearningHomeSerializer, operation_id="learning_home")
    def get(self, request, company_id):
        member = self.membership
        now = timezone.now()
        links = CertificateLinks(request.user)
        mine = _assignments(member)
        todo = sorted(
            mine.filter(state__in=queries.OPEN).filter(
                course__status=Status.PUBLISHED, course__archived_at__isnull=True
            ),
            key=lambda row: (row.due_at is None, row.due_at or now, row.assigned_at, row.pk),
        )
        done = mine.filter(state=Assignment.State.COMPLETED).order_by("-completed_at", "-pk")
        return Response(
            {
                "todo": [assignment_card(row, links=links, now=now) for row in todo],
                "done": [assignment_card(row, links=links, now=now) for row in done[:DONE_LIMIT]],
                "catalog": [course_card(course) for course in catalog(member, now=now)],
                "certificates": Assignment.objects.filter(
                    membership=member, state=Assignment.State.COMPLETED
                )
                .exclude(certificate_no="")
                .count(),
            }
        )


class CourseView(LearningMemberView):
    """A course with my steps: done, locked (sequential courses) or open."""

    def course(self, pk) -> tuple[Course, Assignment | None]:
        member = self.membership
        course = (
            Course.objects.filter(company_id=member.company_id, pk=pk)
            .exclude(status=Status.DRAFT)
            .prefetch_related(steps_for_cards())
            .first()
        )
        if course is None:
            raise NotFound
        mine = courses.latest(course, member)
        held = mine if mine is not None and mine.state in queries.HELD else None
        visible = (
            queries.is_live(course)
            and (held is not None or queries.in_course_audience(member, course))
        ) or (held is not None and held.state == Assignment.State.COMPLETED)
        if not visible:
            raise NotFound
        return course, held

    def detail(self, course: Course, held: Assignment | None) -> dict:
        member = self.membership
        now = timezone.now()
        states = queries.step_states(course, member, held)
        best = _best(member, states)
        links = CertificateLinks(self.request.user)
        return {
            **course_card(course),
            "sequential": course.sequential,
            "certificate": course.certificate,
            "assignment": assignment_card(held, links=links, now=now) if held else None,
            "can_start": courses.can_start(course, member, now=now),
            "steps": [step_json(state, best) for state in states],
        }

    @extend_schema(responses=LearningCourseDetailSerializer, operation_id="learning_course")
    def get(self, request, company_id, pk):
        course, held = self.course(pk)
        return Response(self.detail(course, held))


class StartView(CourseView):
    http_method_names = ["post", "options"]

    @extend_schema(
        request=None,
        responses=LearningAssignmentCardSerializer,
        operation_id="learning_course_start",
    )
    def post(self, request, company_id, pk):
        """Start a course meant for me (or carry on with the one I have)."""
        course, _held = self.course(pk)
        assignment = courses.start(course, self.membership)
        assignment = _assignments(self.membership).get(pk=assignment.pk)
        return Response(
            assignment_card(assignment, links=CertificateLinks(request.user), now=timezone.now())
        )


class LessonView(LearningMemberView):
    """A lesson to watch: the signed MP4 and poster (6 hours) or the YouTube id, the notes,
    my progress and, inside a course (`?course=`), its next step."""

    def lesson(self, pk) -> Lesson:
        found = (
            Lesson.objects.filter(company_id=self.membership.company_id, pk=pk)
            .select_related("video", "company")
            .prefetch_related("topics")
            .first()
        )
        if found is None or not queries.can_open_lesson(self.membership, found):
            raise NotFound
        return found

    def next_step(self, lesson: Lesson) -> dict | None:
        raw = self.request.query_params.get("course")
        if not raw or not raw.isdigit():
            return None
        course = (
            Course.objects.filter(company_id=self.membership.company_id, pk=int(raw))
            .filter(LIVE)
            .first()
        )
        if course is None:
            return None
        steps = list(course.steps.select_related("lesson", "page", "quiz"))
        index = next((i for i, step in enumerate(steps) if step.lesson_id == lesson.pk), None)
        if index is None or index + 1 >= len(steps):
            return None
        step = steps[index + 1]
        target = step.lesson or step.page or step.quiz
        return {"kind": step.kind, "id": target.pk, "title": target.title}

    @extend_schema(
        parameters=[OpenApiParameter("course", int, description="The course it is watched in.")],
        responses=LearningLessonPlaySerializer,
        operation_id="learning_lesson",
    )
    def get(self, request, company_id, pk):
        lesson = self.lesson(pk)
        return Response(
            lesson_json(
                lesson, self.membership, user=request.user, next_step=self.next_step(lesson)
            )
        )


class ProgressView(LessonView):
    http_method_names = ["post", "options"]

    @extend_schema(
        request=LearningProgressReportSerializer,
        responses=LearningProgressResultSerializer,
        operation_id="learning_lesson_progress",
    )
    def post(self, request, company_id, pk):
        """The player's report: every 10 s while playing, on pause, on seek, on leaving."""
        lesson = self.lesson(pk)
        data = LearningProgressReportSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        result = progress.report(lesson, self.membership, **data.validated_data)
        return Response(
            {
                "percent": result.percent,
                "position": result.position,
                "completed": result.completed,
                "completed_now": result.completed_now,
                "points": result.points,
            }
        )


class CertificateView(LearningMemberView):
    """My certificate of a finished course, as a PDF (also while my access is paused)."""

    allow_suspended = True

    def perform_content_negotiation(self, request, force=False):
        return super().perform_content_negotiation(request, force=True)

    @extend_schema(
        responses={
            (200, "application/pdf"): OpenApiResponse(OpenApiTypes.BINARY),
        },
        operation_id="learning_certificate",
    )
    def get(self, request, company_id, pk):
        assignment = (
            Assignment.objects.filter(
                membership=self.membership, pk=pk, state=Assignment.State.COMPLETED
            )
            .exclude(certificate_no="")
            .first()
        )
        if assignment is None:
            raise NotFound
        stored = certificates.ensure_pdf(assignment)
        if stored is None:
            raise NotFound
        response = FileResponse(
            stored.open("rb"),
            content_type="application/pdf",
            as_attachment=False,
            filename=certificates.file_name(assignment),
        )
        for header, value in SANDBOX_HEADERS.items():
            response[header] = value
        response["Cache-Control"] = "private, no-store"
        return response
