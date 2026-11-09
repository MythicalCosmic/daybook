"""Owner dashboard endpoints of package Q1, routed by `owner_urls_courses.py` under
`/api/v1/owner/companies/<id>/learning/…` (docs/PLAN-LEARNING.md §11, §13):

    overview/                      compliance, who is late, time watched, courses
    courses/ (+ {id}/)             courses; publish, archive, restore, reorder
    courses/{id}/steps/…           steps: add, require or not, remove, reorder
    courses/{id}/people/           everyone assigned; assign/, remind/, candidates/
    lessons/ (+ {id}/)             lessons; publish, archive, restore, delete; viewers/
    videos/ (+ {id}/)              uploads: start, chunk/?offset=, finish, delete
    assignments/{id}/…             exempt/, cancel/, due/, certificate/
    people/ (+ {id}/)              people against mandatory courses; one person's training
    step-targets/?kind=            lessons, pages and quizzes a step can point at
    settings/                      the Settings > Training panel

Reading needs `learning.view` (or `learning.manage`), every change `learning.manage`. People
are branch-scoped: someone outside the caller's branches answers 404. Everything answers 404
while the module is off.
"""

from __future__ import annotations

from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import BaseParser
from rest_framework.response import Response

from apps.console.base import AnyOf, OwnerAPIView, OwnerViewSet
from apps.knowledge.models import Page
from apps.learning import certificates, conf, courses, lessons, media, queries, transcripts
from apps.learning.api_courses import _steps
from apps.learning.models import Assignment, Course, CourseStep, Lesson, Quiz, Status, Video
from apps.learning.serializers_courses import (
    LearningAssignmentRowSerializer,
    LearningAssignSerializer,
    LearningCandidateSerializer,
    LearningChunkResultSerializer,
    LearningCountSerializer,
    LearningCoursePeopleSerializer,
    LearningCourseWriteSerializer,
    LearningDueSerializer,
    LearningExemptSerializer,
    LearningFileLinkSerializer,
    LearningIdsSerializer,
    LearningLessonWriteSerializer,
    LearningOverviewSerializer,
    LearningOwnerCourseRowSerializer,
    LearningOwnerCourseSerializer,
    LearningOwnerLessonRowSerializer,
    LearningOwnerLessonSerializer,
    LearningPeopleGridSerializer,
    LearningPersonPageSerializer,
    LearningPickSerializer,
    LearningRemindSerializer,
    LearningSettingsSerializer,
    LearningStepUpdateSerializer,
    LearningStepWriteSerializer,
    LearningVideoSerializer,
    LearningVideoStartSerializer,
    LearningViewersSerializer,
    owner_course,
    owner_course_row,
    owner_lesson,
    owner_lesson_row,
    video_json,
)
from apps.members.models import Membership
from apps.members.permissions import Perm

READ = AnyOf(Perm.LEARNING_VIEW, Perm.LEARNING_MANAGE)
MANAGE = Perm.LEARNING_MANAGE
BRANCH = OpenApiParameter("branch", int, description="One branch (in the caller's scope).")


class LearningOn:
    """404 while the company's learning module is off."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not conf.is_on(self.company):
            raise NotFound


class Scope:
    def branches(self) -> list[int] | None:
        """The caller's branches, narrowed to `?branch=` (another one answers 404)."""
        asked = self.request.query_params.get("branch")
        allowed = self.branch_scope
        if not asked:
            return allowed
        try:
            branch = int(asked)
        except ValueError as exc:
            raise ValidationError({"branch": [_("Give a number.")]}) from exc
        if allowed is not None and branch not in allowed:
            raise NotFound
        return [branch]

    def scoped_people(self, ids) -> list[Membership]:
        """Approved people of `ids` the caller sees; anyone else answers 404."""
        wanted = {int(pk) for pk in ids}
        found = list(
            queries.people_in_scope(self.company, branch_ids=self.branch_scope).filter(
                pk__in=wanted
            )
        )
        if len(found) != len(wanted):
            raise NotFound
        return found

    def scoped_person(self, pk) -> Membership:
        return self.scoped_people([pk])[0]

    def assignment(self, pk) -> Assignment:
        found = (
            Assignment.objects.filter(company=self.company, pk=pk)
            .select_related("course", "membership__user", "company")
            .first()
        )
        if found is None:
            raise NotFound
        self.scoped_person(found.membership_id)
        return found


def _int(value, name: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except TypeError, ValueError:
        raise ValidationError({name: [_("Must be a whole number.")]}) from None


# Overview -------------------------------------------------------------------------------


class OverviewView(LearningOn, Scope, OwnerAPIView):
    perm = READ

    @extend_schema(parameters=[BRANCH], responses=LearningOverviewSerializer)
    def get(self, request, company_id):
        return Response(queries.overview(self.company, branch_ids=self.branches()))


# Courses --------------------------------------------------------------------------------


class RawChunk(BaseParser):
    """The bytes of one piece of an upload, read from the stream by the view."""

    media_type = "application/octet-stream"

    def parse(self, stream, media_type=None, parser_context=None):
        return None


class CourseViewSet(LearningOn, Scope, OwnerViewSet):
    """Courses (`?status=draft|published|archived`, `?q=`), with completion in the caller's
    scope; the editor's steps; the People tab."""

    lookup_value_regex = r"\d+"
    perm = READ
    perms_by_action = {
        "create": MANAGE,
        "partial_update": MANAGE,
        "publish": MANAGE,
        "archive": MANAGE,
        "restore": MANAGE,
        "reorder": MANAGE,
        "steps": MANAGE,
        "step": MANAGE,
        "steps_reorder": MANAGE,
        "assign": MANAGE,
        "remind": MANAGE,
    }

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Course.objects.none()
        return (
            Course.objects.filter(company=self.company)
            .prefetch_related("positions", "branches", Prefetch("steps", queryset=_steps()))
            .order_by("position", "pk")
        )

    def course(self, pk) -> Course:
        found = self.get_queryset().filter(pk=pk).first()
        if found is None:
            raise NotFound
        return found

    def stats(self) -> dict:
        return queries.course_stats(self.company, branch_ids=self.branch_scope, now=timezone.now())

    def shown(self, pk) -> Response:
        course = self.course(pk)
        return Response(owner_course(course, self.stats().get(course.pk, queries.EMPTY_STATS)))

    @extend_schema(
        parameters=[
            OpenApiParameter("status", str, enum=["draft", "published", "archived"]),
            OpenApiParameter("q", str),
        ],
        responses=LearningOwnerCourseRowSerializer(many=True),
    )
    def list(self, request, company_id):
        rows = self.get_queryset()
        wanted = request.query_params.get("status")
        if wanted in Status.values:
            rows = rows.filter(status=wanted)
        else:
            rows = rows.exclude(status=Status.ARCHIVED)
        if q := (request.query_params.get("q") or "").strip():
            rows = rows.filter(title__icontains=q)
        stats = self.stats()
        return Response(
            [owner_course_row(row, stats.get(row.pk, queries.EMPTY_STATS)) for row in rows]
        )

    @extend_schema(responses=LearningOwnerCourseSerializer)
    def retrieve(self, request, company_id, pk):
        return self.shown(pk)

    @extend_schema(
        request=LearningCourseWriteSerializer, responses={201: LearningOwnerCourseSerializer}
    )
    def create(self, request, company_id):
        data = LearningCourseWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        course = courses.create_course(
            self.company, by=self.membership, title=values.pop("title"), **values
        )
        response = self.shown(course.pk)
        response.status_code = status.HTTP_201_CREATED
        return response

    @extend_schema(request=LearningCourseWriteSerializer, responses=LearningOwnerCourseSerializer)
    def partial_update(self, request, company_id, pk):
        data = LearningCourseWriteSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        courses.update_course(self.course(pk), by=self.membership, **data.validated_data)
        return self.shown(pk)

    @extend_schema(request=None, responses=LearningOwnerCourseSerializer)
    @action(detail=True, methods=["post"])
    def publish(self, request, company_id, pk):
        courses.publish_course(self.course(pk), by=self.membership)
        return self.shown(pk)

    @extend_schema(request=None, responses=LearningOwnerCourseSerializer)
    @action(detail=True, methods=["post"])
    def archive(self, request, company_id, pk):
        courses.archive_course(self.course(pk), by=self.membership)
        return self.shown(pk)

    @extend_schema(request=None, responses=LearningOwnerCourseSerializer)
    @action(detail=True, methods=["post"])
    def restore(self, request, company_id, pk):
        courses.restore_course(self.course(pk), by=self.membership)
        return self.shown(pk)

    @extend_schema(request=LearningIdsSerializer, responses={204: None})
    @action(detail=False, methods=["post"])
    def reorder(self, request, company_id):
        data = LearningIdsSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        courses.reorder_courses(self.company, data.validated_data["ids"], by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        request=LearningStepWriteSerializer, responses={201: LearningOwnerCourseSerializer}
    )
    @action(detail=True, methods=["post"])
    def steps(self, request, company_id, pk):
        """Add a step: a lesson, a page or a quiz of this company that isn't archived."""
        data = LearningStepWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        courses.add_step(self.course(pk), by=self.membership, **data.validated_data)
        response = self.shown(pk)
        response.status_code = status.HTTP_201_CREATED
        return response

    @extend_schema(
        methods=["PATCH"],
        request=LearningStepUpdateSerializer,
        responses=LearningOwnerCourseSerializer,
    )
    @extend_schema(methods=["DELETE"], request=None, responses=LearningOwnerCourseSerializer)
    @action(detail=True, methods=["patch", "delete"], url_path=r"steps/(?P<step_id>\d+)")
    def step(self, request, company_id, pk, step_id):
        course = self.course(pk)
        found = get_object_or_404(CourseStep.objects.filter(course=course), pk=step_id)
        if request.method == "DELETE":
            courses.remove_step(found, by=self.membership)
        else:
            data = LearningStepUpdateSerializer(data=request.data)
            data.is_valid(raise_exception=True)
            courses.update_step(found, by=self.membership, **data.validated_data)
        return self.shown(pk)

    @extend_schema(request=LearningIdsSerializer, responses=LearningOwnerCourseSerializer)
    @action(detail=True, methods=["post"], url_path="steps/reorder")
    def steps_reorder(self, request, company_id, pk):
        data = LearningIdsSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        courses.reorder_steps(self.course(pk), data.validated_data["ids"], by=self.membership)
        return self.shown(pk)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "state", str, enum=["open", "late", "completed", "closed"], description="Filter."
            )
        ],
        responses=LearningCoursePeopleSerializer,
    )
    @action(detail=True)
    def people(self, request, company_id, pk):
        """Everyone assigned (their newest cycle), in the caller's scope."""
        rows = queries.course_people(
            self.course(pk), branch_ids=self.branch_scope, now=timezone.now()
        )
        counts = {"open": 0, "late": 0, "completed": 0, "closed": 0}
        for row in rows:
            counts[_bucket(row["assignment"])] += 1
        wanted = request.query_params.get("state")
        if wanted in counts:
            rows = [row for row in rows if _bucket(row["assignment"]) == wanted]
        return Response({"counts": counts, "results": rows})

    @extend_schema(
        parameters=[OpenApiParameter("q", str)], responses=LearningCandidateSerializer(many=True)
    )
    @action(detail=True)
    def candidates(self, request, company_id, pk):
        """People the caller may assign the course to, those who already have it marked."""
        course = self.course(pk)
        people = queries.people_in_scope(self.company, branch_ids=self.branch_scope)
        if q := (request.query_params.get("q") or "").strip():
            people = people.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q))
        now = timezone.now()
        current = queries.current_assignments(self.company)
        rows = []
        for person in people.order_by("first_name", "last_name", "pk")[:200]:
            rows.append(
                {
                    **queries.person_ref(person),
                    "assigned": courses.holds(current.get((course.pk, person.pk)), now),
                }
            )
        return Response(rows)

    @extend_schema(request=LearningAssignSerializer, responses=LearningCountSerializer)
    @action(detail=True, methods=["post"])
    def assign(self, request, company_id, pk):
        """Give the course to people the caller sees, with an optional deadline."""
        data = LearningAssignSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        course = self.course(pk)
        people = self.scoped_people(data.validated_data["member_ids"])
        due_on = data.validated_data.get("due_on")
        made = courses.assign(
            course,
            people,
            by=self.membership,
            due_at=courses.end_of_day(self.company, due_on) if due_on else None,
        )
        return Response({"count": len(made)})

    @extend_schema(request=LearningRemindSerializer, responses=LearningCountSerializer)
    @action(detail=True, methods=["post"])
    def remind(self, request, company_id, pk):
        """Remind everyone with this course open (or the people given) to carry on."""
        data = LearningRemindSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        ids = data.validated_data.get("member_ids")
        if ids:
            self.scoped_people(ids)
        sent = courses.remind(self.course(pk), by=self.membership, member_ids=ids or None)
        return Response({"count": sent})


def _bucket(row: dict) -> str:
    if row["state"] in ("exempt", "cancelled"):
        return "closed"
    if row["state"] == "completed":
        return "completed"
    return "late" if row["late"] else "open"


# Lessons and videos ---------------------------------------------------------------------


class LessonViewSet(LearningOn, Scope, OwnerViewSet):
    """Lessons (`?status=`, `?q=`, `?topic=`), with how many watched in the caller's scope."""

    lookup_value_regex = r"\d+"
    perm = READ
    perms_by_action = {
        "create": MANAGE,
        "partial_update": MANAGE,
        "destroy": MANAGE,
        "publish": MANAGE,
        "archive": MANAGE,
        "restore": MANAGE,
        "transcribe": MANAGE,
    }

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Lesson.objects.none()
        return (
            Lesson.objects.filter(company=self.company)
            .select_related("video")
            .prefetch_related("topics", "positions")
            .order_by("-updated_at", "-pk")
        )

    def lesson(self, pk) -> Lesson:
        found = self.get_queryset().filter(pk=pk).first()
        if found is None:
            raise NotFound
        return found

    def shown(self, pk) -> Response:
        lesson = self.lesson(pk)
        counts = queries.viewer_counts([lesson], branch_ids=self.branch_scope)
        return Response(owner_lesson(lesson, counts.get(lesson.pk), user=self.request.user))

    @extend_schema(
        parameters=[
            OpenApiParameter("status", str, enum=["draft", "published", "archived"]),
            OpenApiParameter("q", str),
            OpenApiParameter("topic", int),
        ],
        responses=LearningOwnerLessonRowSerializer(many=True),
    )
    def list(self, request, company_id):
        rows = self.get_queryset()
        wanted = request.query_params.get("status")
        if wanted in Status.values:
            rows = rows.filter(status=wanted)
        else:
            rows = rows.exclude(status=Status.ARCHIVED)
        if q := (request.query_params.get("q") or "").strip():
            rows = rows.filter(title__icontains=q)
        if topic := _int(request.query_params.get("topic"), "topic"):
            rows = rows.filter(topics=topic)
        rows = list(rows.distinct())
        counts = queries.viewer_counts(rows, branch_ids=self.branch_scope)
        return Response([owner_lesson_row(row, counts.get(row.pk)) for row in rows])

    @extend_schema(responses=LearningOwnerLessonSerializer)
    def retrieve(self, request, company_id, pk):
        return self.shown(pk)

    @extend_schema(
        request=LearningLessonWriteSerializer, responses={201: LearningOwnerLessonSerializer}
    )
    def create(self, request, company_id):
        data = LearningLessonWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        lesson = lessons.create_lesson(
            self.company, by=self.membership, title=values.pop("title"), **values
        )
        response = self.shown(lesson.pk)
        response.status_code = status.HTTP_201_CREATED
        return response

    @extend_schema(request=LearningLessonWriteSerializer, responses=LearningOwnerLessonSerializer)
    def partial_update(self, request, company_id, pk):
        data = LearningLessonWriteSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        lessons.update_lesson(self.lesson(pk), by=self.membership, **data.validated_data)
        return self.shown(pk)

    @extend_schema(responses={204: None})
    def destroy(self, request, company_id, pk):
        lessons.delete_lesson(self.lesson(pk), by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=None, responses=LearningOwnerLessonSerializer)
    @action(detail=True, methods=["post"])
    def publish(self, request, company_id, pk):
        lessons.publish_lesson(self.lesson(pk), by=self.membership)
        return self.shown(pk)

    @extend_schema(request=None, responses=LearningOwnerLessonSerializer)
    @action(detail=True, methods=["post"])
    def archive(self, request, company_id, pk):
        lessons.archive_lesson(self.lesson(pk), by=self.membership)
        return self.shown(pk)

    @extend_schema(request=None, responses=LearningOwnerLessonSerializer)
    @action(detail=True, methods=["post"])
    def restore(self, request, company_id, pk):
        lessons.restore_lesson(self.lesson(pk), by=self.membership)
        return self.shown(pk)

    @extend_schema(
        methods=["POST"],
        request=None,
        responses=LearningOwnerLessonSerializer,
        description=(
            "Write down what is said in the uploaded video (the speech service, a piece at a "
            "time on the ai queue); a running job is left alone. 400 when it can't start "
            "(`transcription.unavailable` says why)."
        ),
    )
    @extend_schema(
        methods=["DELETE"],
        request=None,
        responses=LearningOwnerLessonSerializer,
        description="Stop writing it down, or forget a failed attempt.",
    )
    @action(detail=True, methods=["post", "delete"])
    def transcribe(self, request, company_id, pk):
        lesson = self.lesson(pk)
        if request.method == "DELETE":
            transcripts.stop(lesson, by=self.membership)
        else:
            transcripts.start(lesson, by=self.membership)
        return self.shown(pk)

    @extend_schema(
        parameters=[OpenApiParameter("state", str, enum=["never", "watching", "watched"])],
        responses=LearningViewersSerializer,
    )
    @action(detail=True)
    def viewers(self, request, company_id, pk):
        """Who watched what: everyone it is for, in the caller's scope."""
        lesson = self.lesson(pk)
        rows = queries.lesson_viewers(lesson, branch_ids=self.branch_scope)
        counts = {"never": 0, "watching": 0, "watched": 0}
        for row in rows:
            counts[row["state"]] += 1
        wanted = request.query_params.get("state")
        if wanted in counts:
            rows = [row for row in rows if row["state"] == wanted]
        return Response(
            {"counts": counts, "duration_seconds": lesson.duration_seconds, "results": rows}
        )


class VideoViewSet(LearningOn, OwnerViewSet):
    """Uploads (§5): start with the name and size, send the pieces in order (`chunk/?offset=`;
    a 409 says where to continue), finish; then the media worker makes the MP4."""

    lookup_value_regex = r"\d+"
    perm = READ
    perms_by_action = {
        "create": MANAGE,
        "destroy": MANAGE,
        "chunk": MANAGE,
        "finish": MANAGE,
    }

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Video.objects.none()
        return (
            Video.objects.filter(company=self.company)
            .prefetch_related("lessons")
            .order_by("-created_at", "-pk")
        )

    def video(self, pk) -> Video:
        found = self.get_queryset().filter(pk=pk).first()
        if found is None:
            raise NotFound
        return found

    def one(self, video: Video, code: int = status.HTTP_200_OK) -> Response:
        return Response(video_json(self.video(video.pk), user=self.request.user), status=code)

    @extend_schema(responses=LearningVideoSerializer(many=True))
    def list(self, request, company_id):
        rows = self.get_queryset().exclude(state=Video.State.UPLOADING)[:100]
        return Response([video_json(row, user=request.user) for row in rows])

    @extend_schema(responses=LearningVideoSerializer)
    def retrieve(self, request, company_id, pk):
        return self.one(self.video(pk))

    @extend_schema(request=LearningVideoStartSerializer, responses={201: LearningVideoSerializer})
    def create(self, request, company_id):
        data = LearningVideoStartSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        video = media.start_upload(
            self.company,
            by=self.membership,
            name=data.validated_data["name"],
            size=data.validated_data["size"],
        )
        return self.one(video, status.HTTP_201_CREATED)

    @extend_schema(responses={204: None})
    def destroy(self, request, company_id, pk):
        media.delete_video(self.video(pk), by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        parameters=[OpenApiParameter("offset", int, required=True)],
        request={"application/octet-stream": OpenApiTypes.BINARY},
        responses={
            200: LearningChunkResultSerializer,
            409: OpenApiResponse(
                LearningChunkResultSerializer, description="Continue from `received_bytes`."
            ),
        },
    )
    @action(detail=True, methods=["put"], parser_classes=[RawChunk])
    def chunk(self, request, company_id, pk):
        """One piece of the upload (at most 8 MB), at `offset`."""
        offset = _int(request.query_params.get("offset"), "offset")
        if offset is None:
            raise ValidationError({"offset": [_("Give the offset of this piece.")]})
        stream = request.stream
        data = stream.read(media.CHUNK_BYTES + 1) if stream is not None else b""
        video = self.video(pk)
        try:
            video = media.receive_chunk(video, by=self.membership, offset=offset, data=data)
        except media.OffsetMismatch as mismatch:
            return Response(
                {
                    "detail": str(mismatch),
                    "id": video.pk,
                    "state": video.state,
                    "received_bytes": mismatch.received,
                    "original_bytes": video.original_bytes,
                },
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            {
                "id": video.pk,
                "state": video.state,
                "received_bytes": video.received_bytes,
                "original_bytes": video.original_bytes,
            }
        )

    @extend_schema(request=None, responses=LearningVideoSerializer)
    @action(detail=True, methods=["post"])
    def finish(self, request, company_id, pk):
        """Every piece is in: the video goes to the media worker."""
        return self.one(media.finish_upload(self.video(pk), by=self.membership))


# Assignments ----------------------------------------------------------------------------


class AssignmentViewSet(LearningOn, Scope, OwnerViewSet):
    """A person's assignment: excuse them, take it back, move the deadline, the certificate."""

    lookup_value_regex = r"\d+"
    perm = READ
    perms_by_action = {"exempt": MANAGE, "cancel": MANAGE, "due": MANAGE}

    def get_queryset(self):
        return Assignment.objects.none()

    def row(self, assignment: Assignment) -> Response:
        assignment = Assignment.objects.select_related("company").get(pk=assignment.pk)
        return Response(queries.assignment_row(assignment, timezone.now()))

    @extend_schema(request=LearningExemptSerializer, responses=LearningAssignmentRowSerializer)
    @action(detail=True, methods=["post"])
    def exempt(self, request, company_id, pk):
        data = LearningExemptSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return self.row(
            courses.exempt(
                self.assignment(pk), by=self.membership, reason=data.validated_data["reason"]
            )
        )

    @extend_schema(request=None, responses=LearningAssignmentRowSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, company_id, pk):
        return self.row(courses.cancel(self.assignment(pk), by=self.membership))

    @extend_schema(request=LearningDueSerializer, responses=LearningAssignmentRowSerializer)
    @action(detail=True, methods=["post"])
    def due(self, request, company_id, pk):
        data = LearningDueSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        due_on = data.validated_data["due_on"]
        return self.row(
            courses.move_due(
                self.assignment(pk),
                by=self.membership,
                due_at=courses.end_of_day(self.company, due_on) if due_on else None,
            )
        )

    @extend_schema(responses=LearningFileLinkSerializer)
    @action(detail=True)
    def certificate(self, request, company_id, pk):
        """A short-lived link to the certificate PDF."""
        assignment = self.assignment(pk)
        if not certificates.ensure_pdf(assignment):
            raise NotFound
        assignment.refresh_from_db(fields=["certificate_file"])
        return Response(
            {
                "url": certificates.link(assignment, user=request.user),
                "name": certificates.file_name(assignment),
                "expires_in": certificates.LINK_TTL,
            }
        )


# People ---------------------------------------------------------------------------------


class PeopleView(LearningOn, Scope, OwnerAPIView):
    """Everyone in scope against the mandatory courses."""

    perm = READ

    @extend_schema(
        parameters=[
            BRANCH,
            OpenApiParameter("position", int),
            OpenApiParameter("q", str),
            OpenApiParameter("late", bool),
        ],
        responses=LearningPeopleGridSerializer,
        operation_id="learning_people",
    )
    def get(self, request, company_id):
        params = request.query_params
        return Response(
            queries.people_grid(
                self.company,
                branch_ids=self.branches(),
                now=timezone.now(),
                position_id=_int(params.get("position"), "position"),
                q=(params.get("q") or "").strip(),
                late_only=params.get("late") in ("1", "true"),
            )
        )


class PersonView(LearningOn, Scope, OwnerAPIView):
    """One person's training: courses, lessons watched, pages read."""

    perm = READ

    @extend_schema(responses=LearningPersonPageSerializer, operation_id="learning_person")
    def get(self, request, company_id, pk):
        return Response(queries.person_learning(self.scoped_person(pk), now=timezone.now()))


# Pickers and settings -------------------------------------------------------------------


class StepTargetsView(LearningOn, OwnerAPIView):
    """Lessons, pages or quizzes a step can point at: of this company, not archived."""

    perm = MANAGE

    @extend_schema(
        parameters=[
            OpenApiParameter("kind", str, enum=CourseStep.Kind.values, required=True),
            OpenApiParameter("q", str),
        ],
        responses=LearningPickSerializer(many=True),
    )
    def get(self, request, company_id):
        kind = request.query_params.get("kind")
        q = (request.query_params.get("q") or "").strip()
        if kind == CourseStep.Kind.PAGE:
            rows = Page.objects.filter(company=self.company, archived_at__isnull=True)
            if q:
                rows = rows.filter(title__icontains=q)
            found = [
                {
                    "id": row.pk,
                    "title": row.title,
                    "emoji": row.emoji,
                    "status": Status.PUBLISHED if row.published else Status.DRAFT,
                }
                for row in rows.order_by("title")[:50]
            ]
        elif kind in (CourseStep.Kind.LESSON, CourseStep.Kind.QUIZ):
            model = Lesson if kind == CourseStep.Kind.LESSON else Quiz
            rows = model.objects.filter(company=self.company, archived_at__isnull=True).exclude(
                status=Status.ARCHIVED
            )
            if q:
                rows = rows.filter(title__icontains=q)
            found = [
                {"id": row.pk, "title": row.title, "emoji": row.emoji, "status": row.status}
                for row in rows.order_by("title")[:50]
            ]
        else:
            raise ValidationError({"kind": [_("A step is a lesson, a page or a quiz.")]})
        return Response(found)


class SettingsView(LearningOn, OwnerAPIView):
    perm = READ
    perms_by_action = {"patch": MANAGE}

    def data(self) -> dict:
        row = conf.get_settings(self.company)
        return {
            "completion_percent": row.completion_percent,
            "max_speed_percent": row.max_speed_percent,
            "remind_before_days": row.remind_before_days,
            "escalate_after_days": row.escalate_after_days,
            "certificates": row.certificates,
            "certificate_prefix": row.certificate_prefix,
            "next_certificate_number": row.next_certificate_number,
            "catalog_for_staff": row.catalog_for_staff,
            "storage_limit_mb": row.storage_limit_mb,
            "storage_used_bytes": media.used_bytes(self.company),
        }

    @extend_schema(responses=LearningSettingsSerializer)
    def get(self, request, company_id):
        return Response(self.data())

    @extend_schema(request=LearningSettingsSerializer, responses=LearningSettingsSerializer)
    def patch(self, request, company_id):
        data = LearningSettingsSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        courses.update_settings(self.company, by=self.membership, **data.validated_data)
        return Response(self.data())
