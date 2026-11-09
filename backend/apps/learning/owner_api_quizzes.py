"""Owner dashboard endpoints of package Q2 (`learning/…`), routed in `owner_urls_quizzes.py`:

    GET/POST         learning/questions/?topic&kind&difficulty&state&source&q&draft_job
    GET/PATCH/DELETE learning/questions/{id}/          DELETE: only a question nobody was asked
    POST             learning/questions/bulk/          {ids, state}: activate or archive many
    POST             learning/questions/images/        a picture (multipart "file")
    GET/PATCH        learning/questions/daily/         the question of the day's settings
    GET/POST         learning/quizzes/  ·  GET/PATCH/DELETE learning/quizzes/{id}/
    POST             learning/quizzes/{id}/publish|archive|restore|reset/
    GET              learning/quizzes/{id}/preview|results/
    GET              learning/attempts/{id}/           one attempt with every answer
    GET/POST         learning/checks/  ·  GET/PATCH learning/checks/{id}/
    POST             learning/checks/{id}/pause|resume|archive/
    GET              learning/checks/{id}/rounds/  ·  learning/checks/{id}/rounds/{round}/
    GET              learning/skills/?branch&position&topic&sort   the skill matrix
    GET              learning/skills/{member}/         one person's skills and attempts
    GET              learning/suggestions/?state&kind  ·  POST …/{id}/accept|dismiss/
    GET/POST         learning/drafts/  ·  GET learning/drafts/{id}/

Reading results needs `learning.view` or `learning.manage`; the bank, writing, deciding and
drafting need `learning.manage`. Everything is company-scoped and answers 404 while the
`learning` module is off; people's results keep to the viewer's branches (a person outside them
answers 404). Changes are audited by the services, which move the pulse keys after commit.
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.console.base import OwnerAPIView, OwnerViewSet
from apps.console.perms import AnyOf
from apps.core.api import Pagination
from apps.learning import (
    attempts,
    checks,
    conf,
    daily,
    drafting,
    grading,
    quiz_queries,
    quizzes,
    skills,
    suggestions,
)
from apps.learning import serializers_quizzes as s
from apps.learning.models import (
    Attempt,
    CheckRound,
    Question,
    QuestionDraftJob,
    Quiz,
    RegularCheck,
    TutorSuggestion,
)
from apps.members.models import Membership
from apps.members.permissions import Perm

READ = AnyOf(Perm.LEARNING_VIEW, Perm.LEARNING_MANAGE)
MANAGE = Perm.LEARNING_MANAGE
BRANCH_PARAM = OpenApiParameter("branch", int, description="One branch (in the viewer's scope).")


class LearningOn:
    """404 while the company's `learning` module is off."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not conf.is_on(self.company):
            raise NotFound


class Scope:
    def branches(self) -> list[int] | None:
        """The viewer's branches, narrowed to `?branch=` when given (and theirs)."""
        asked = self.request.query_params.get("branch")
        allowed = self.branch_scope
        if not asked:
            return allowed
        try:
            branch = int(asked)
        except ValueError as exc:
            raise ValidationError({"branch": ["Give a number."]}) from exc
        if allowed is not None and branch not in allowed:
            raise NotFound
        return [branch]

    def member(self, pk) -> Membership:
        """A person of the company the viewer sees, else 404."""
        found = (
            Membership.objects.for_company(self.company)
            .select_related("user", "position", "company")
            .filter(pk=pk)
            .first()
        )
        if found is None or not quiz_queries.in_scope(found, branch_ids=self.branch_scope):
            raise NotFound
        return found


def _clean(form_class, data, *, partial=False) -> dict:
    form = form_class(data=data, partial=partial)
    form.is_valid(raise_exception=True)
    return dict(form.validated_data)


def _invalid(exc: grading.InvalidQuestion):
    return ValidationError(exc.errors)


# Questions ---------------------------------------------------------------------------------


QUESTION_FILTERS = [
    OpenApiParameter("topic", int),
    OpenApiParameter("kind", str, enum=list(Question.Kind.values)),
    OpenApiParameter("difficulty", str, enum=list(Question.Difficulty.values)),
    OpenApiParameter("state", str, enum=list(Question.State.values)),
    OpenApiParameter("source", str, enum=list(Question.Source.values)),
    OpenApiParameter("q", str, description="Words of the question's text."),
    OpenApiParameter("draft_job", int, description="Questions a drafting job wrote."),
]


class QuestionViewSet(
    LearningOn,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    OwnerViewSet,
):
    perm = MANAGE
    pagination_class = Pagination
    serializer_class = s.LearningQuestionSerializer
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Question.objects.none()
        params = self.request.query_params
        return quiz_queries.questions(
            self.company,
            topic=_int(params.get("topic")),
            kind=params.get("kind") or None,
            difficulty=params.get("difficulty") or None,
            state=params.get("state") or None,
            source=params.get("source") or None,
            q=params.get("q") or None,
            draft_job=_int(params.get("draft_job")),
        )

    def _one(self, question: Question) -> dict:
        found = self.get_queryset().get(pk=question.pk)
        return quiz_queries.question_rows([found], self.request.user)[0]

    @extend_schema(parameters=QUESTION_FILTERS, responses=s.LearningQuestionSerializer(many=True))
    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(quiz_queries.question_rows(page, request.user))

    @extend_schema(responses=s.LearningQuestionSerializer)
    def retrieve(self, request, *args, **kwargs):
        return Response(self._one(self.get_object()))

    @extend_schema(
        request=s.LearningQuestionWriteSerializer, responses={201: s.LearningQuestionSerializer}
    )
    def create(self, request, company_id):
        data = _clean(s.LearningQuestionWriteSerializer, request.data)
        try:
            question = quizzes.create_question(
                self.company,
                by=self.membership,
                kind=data.pop("kind", ""),
                text=data.pop("text", ""),
                data=data.pop("data", None),
                state=data.pop("state", Question.State.ACTIVE),
                **data,
            )
        except grading.InvalidQuestion as exc:
            raise _invalid(exc) from exc
        return Response(self._one(question), status=status.HTTP_201_CREATED)

    @extend_schema(
        request=s.LearningQuestionWriteSerializer, responses=s.LearningQuestionSerializer
    )
    def partial_update(self, request, company_id, pk):
        question = self.get_object()
        data = _clean(s.LearningQuestionWriteSerializer, request.data, partial=True)
        state = data.pop("state", None)
        try:
            question = quizzes.update_question(question, by=self.membership, **data)
            if state is not None:
                question = quizzes.set_question_state(question, state, by=self.membership)
        except grading.InvalidQuestion as exc:
            raise _invalid(exc) from exc
        return Response(self._one(question))

    def destroy(self, request, company_id, pk):
        quizzes.delete_question(self.get_object(), by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=s.LearningQuestionBulkSerializer, responses=s.LearningChangedSerializer)
    @action(detail=False, methods=["post"])
    def bulk(self, request, company_id):
        data = _clean(s.LearningQuestionBulkSerializer, request.data)
        try:
            changed = quizzes.bulk_state(
                self.company, data["ids"], data["state"], by=self.membership
            )
        except grading.InvalidQuestion as exc:
            raise _invalid(exc) from exc
        return Response({"changed": changed})


def _int(value) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except ValueError:
        raise ValidationError({"detail": ["Give a number."]}) from None


class ImageView(LearningOn, OwnerAPIView):
    perm = MANAGE
    parser_classes = (MultiPartParser, FormParser)

    @extend_schema(
        request={"multipart/form-data": s.LearningImageUploadSerializer},
        responses={201: s.LearningImageSerializer},
    )
    def post(self, request, company_id):
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": ["Choose a picture."]})
        image = quizzes.save_image(self.company, upload, by=self.membership)
        return Response(quiz_queries.image_ref(image, request.user), status=status.HTTP_201_CREATED)


class DailySettingsView(LearningOn, OwnerAPIView):
    perm = READ
    perms_by_action = {"patch": MANAGE}

    def shape(self) -> dict:
        row = conf.get_settings(self.company)
        return {
            "daily_question": row.daily_question,
            "daily_at": row.daily_at,
            "daily_position_ids": list(row.daily_position_ids or []),
            "today": daily.today_stats(self.company),
        }

    @extend_schema(responses=s.LearningDailySettingsSerializer)
    def get(self, request, company_id):
        return Response(s.LearningDailySettingsSerializer(self.shape()).data)

    @extend_schema(
        request=s.LearningDailySettingsWriteSerializer, responses=s.LearningDailySettingsSerializer
    )
    def patch(self, request, company_id):
        data = _clean(s.LearningDailySettingsWriteSerializer, request.data, partial=True)
        daily.update_settings(self.company, by=self.membership, **data)
        return Response(s.LearningDailySettingsSerializer(self.shape()).data)


# Quizzes -----------------------------------------------------------------------------------


class QuizViewSet(
    LearningOn,
    Scope,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    OwnerViewSet,
):
    perm = READ
    perms_by_action = {
        "create": MANAGE,
        "partial_update": MANAGE,
        "destroy": MANAGE,
        "publish": MANAGE,
        "archive": MANAGE,
        "restore": MANAGE,
        "reset": MANAGE,
        "preview": MANAGE,
    }
    pagination_class = None
    serializer_class = s.LearningQuizSerializer
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Quiz.objects.none()
        rows = Quiz.objects.filter(company=self.company).prefetch_related("topics")
        status_ = self.request.query_params.get("status")
        if status_:
            rows = rows.filter(status=status_)
        return rows.order_by("-updated_at", "-pk")

    def _stats(self, ids: list[int]) -> dict:
        return quiz_queries.quiz_stats(self.company, ids, branch_ids=self.branch_scope)

    def _one(self, quiz: Quiz) -> dict:
        quiz = self.get_queryset().get(pk=quiz.pk)
        return s.LearningQuizSerializer(
            quiz_queries.quiz_detail(quiz, self._stats([quiz.pk])[quiz.pk])
        ).data

    @extend_schema(
        parameters=[OpenApiParameter("status", str, enum=["draft", "published", "archived"])],
        responses=s.LearningQuizRowSerializer(many=True),
    )
    def list(self, request, *args, **kwargs):
        rows = list(self.get_queryset())
        stats = self._stats([quiz.pk for quiz in rows])
        return Response(
            s.LearningQuizRowSerializer(
                [quiz_queries.quiz_row(quiz, stats[quiz.pk]) for quiz in rows], many=True
            ).data
        )

    @extend_schema(responses=s.LearningQuizSerializer)
    def retrieve(self, request, *args, **kwargs):
        return Response(self._one(self.get_object()))

    @extend_schema(request=s.LearningQuizWriteSerializer, responses={201: s.LearningQuizSerializer})
    def create(self, request, company_id):
        data = _clean(s.LearningQuizWriteSerializer, request.data)
        quiz = quizzes.create_quiz(self.company, by=self.membership, **data)
        return Response(self._one(quiz), status=status.HTTP_201_CREATED)

    @extend_schema(request=s.LearningQuizWriteSerializer, responses=s.LearningQuizSerializer)
    def partial_update(self, request, company_id, pk):
        data = _clean(s.LearningQuizWriteSerializer, request.data, partial=True)
        quiz = quizzes.update_quiz(self.get_object(), by=self.membership, **data)
        return Response(self._one(quiz))

    def destroy(self, request, company_id, pk):
        quizzes.delete_quiz(self.get_object(), by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=None, responses=s.LearningQuizSerializer)
    @action(detail=True, methods=["post"])
    def publish(self, request, company_id, pk):
        return Response(self._one(quizzes.publish_quiz(self.get_object(), by=self.membership)))

    @extend_schema(request=None, responses=s.LearningQuizSerializer)
    @action(detail=True, methods=["post"])
    def archive(self, request, company_id, pk):
        return Response(self._one(quizzes.archive_quiz(self.get_object(), by=self.membership)))

    @extend_schema(request=None, responses=s.LearningQuizSerializer)
    @action(detail=True, methods=["post"])
    def restore(self, request, company_id, pk):
        return Response(self._one(quizzes.restore_quiz(self.get_object(), by=self.membership)))

    @extend_schema(responses=s.LearningPreviewSerializer)
    @action(detail=True, methods=["get"])
    def preview(self, request, company_id, pk):
        """A draw as a learner would get it now, with the right answers."""
        quiz = self.get_object()
        rows = quiz_queries.preview(quiz, self.membership, request.user)
        return Response(s.LearningPreviewSerializer({"questions": rows}).data)

    @extend_schema(
        parameters=[
            BRANCH_PARAM,
            OpenApiParameter("from", str, description="YYYY-MM-DD, the company's day."),
            OpenApiParameter("to", str, description="YYYY-MM-DD, the company's day (included)."),
        ],
        responses=s.LearningResultsSerializer,
    )
    @action(detail=True, methods=["get"])
    def results(self, request, company_id, pk):
        quiz = self.get_object()
        start, end = self._days()
        found = quiz_queries.results(quiz, branch_ids=self.branches(), start=start, end=end)
        return Response(s.LearningResultsSerializer(found).data)

    def _days(self) -> tuple[datetime | None, datetime | None]:
        zone = ZoneInfo(self.company.timezone)
        found = []
        for name in ("from", "to"):
            value = self.request.query_params.get(name)
            if not value:
                found.append(None)
                continue
            try:
                day = datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError as exc:
                raise ValidationError({name: ["Use YYYY-MM-DD."]}) from exc
            moment = datetime.combine(day, time.min, zone)
            found.append(moment if name == "from" else moment + timedelta(days=1))
        return found[0], found[1]

    @extend_schema(request=s.LearningResetSerializer, responses=s.LearningChangedSerializer)
    @action(detail=True, methods=["post"])
    def reset(self, request, company_id, pk):
        data = _clean(s.LearningResetSerializer, request.data)
        member = self.member(data["member"])
        changed = attempts.reset(self.get_object(), member, by=self.membership)
        return Response({"changed": changed})


class AttemptView(LearningOn, Scope, OwnerAPIView):
    perm = READ

    @extend_schema(responses=s.LearningOwnerAttemptSerializer)
    def get(self, request, company_id, pk):
        attempt = (
            Attempt.objects.filter(company=self.company, pk=pk)
            .select_related("quiz", "membership__user", "membership__position")
            .first()
        )
        if attempt is None:
            raise NotFound
        self.member(attempt.membership_id)
        attempts.expire_due(quiz=attempt.quiz, member=attempt.membership)
        attempt.refresh_from_db()
        shape = attempts.result_shape(attempt, request.user, full=True) | {
            "member": quiz_queries.person(attempt.membership),
            "quiz": quiz_queries.ref(attempt.quiz),
            "number": attempt.number,
            "started_at": attempt.started_at,
            "finished_at": attempt.finished_at,
            "trial": attempt.trial,
        }
        return Response(s.LearningOwnerAttemptSerializer(shape).data)


# Checks ------------------------------------------------------------------------------------


class CheckViewSet(
    LearningOn, Scope, mixins.ListModelMixin, mixins.RetrieveModelMixin, OwnerViewSet
):
    perm = READ
    perms_by_action = {
        "create": MANAGE,
        "partial_update": MANAGE,
        "pause": MANAGE,
        "resume": MANAGE,
        "archive": MANAGE,
    }
    pagination_class = None
    serializer_class = s.LearningCheckSerializer
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return RegularCheck.objects.none()
        rows = RegularCheck.objects.filter(company=self.company).select_related("quiz")
        if self.request.query_params.get("archived") != "true":
            rows = rows.exclude(state=RegularCheck.State.ARCHIVED)
        return rows.order_by("title", "pk")

    def _row(self, check: RegularCheck) -> dict:
        return s.LearningCheckSerializer(
            quiz_queries.check_row(check, branch_ids=self.branch_scope)
        ).data

    @extend_schema(
        parameters=[OpenApiParameter("archived", bool)],
        responses=s.LearningCheckSerializer(many=True),
    )
    def list(self, request, *args, **kwargs):
        return Response([self._row(check) for check in self.get_queryset()])

    @extend_schema(responses=s.LearningCheckSerializer)
    def retrieve(self, request, *args, **kwargs):
        return Response(self._row(self.get_object()))

    def get_object(self):
        found = RegularCheck.objects.filter(company=self.company, pk=self.kwargs["pk"]).first()
        if found is None:
            raise NotFound
        return found

    @extend_schema(
        request=s.LearningCheckWriteSerializer, responses={201: s.LearningCheckSerializer}
    )
    def create(self, request, company_id):
        data = _clean(s.LearningCheckWriteSerializer, request.data)
        check = checks.create_check(self.company, by=self.membership, **data)
        return Response(self._row(check), status=status.HTTP_201_CREATED)

    @extend_schema(request=s.LearningCheckWriteSerializer, responses=s.LearningCheckSerializer)
    def partial_update(self, request, company_id, pk):
        data = _clean(s.LearningCheckWriteSerializer, request.data, partial=True)
        check = checks.update_check(self.get_object(), by=self.membership, **data)
        return Response(self._row(check))

    def _state(self, state: str) -> Response:
        check = checks.set_check_state(self.get_object(), state, by=self.membership)
        return Response(self._row(check))

    @extend_schema(request=None, responses=s.LearningCheckSerializer)
    @action(detail=True, methods=["post"])
    def pause(self, request, company_id, pk):
        return self._state(RegularCheck.State.PAUSED)

    @extend_schema(request=None, responses=s.LearningCheckSerializer)
    @action(detail=True, methods=["post"])
    def resume(self, request, company_id, pk):
        return self._state(RegularCheck.State.ACTIVE)

    @extend_schema(request=None, responses=s.LearningCheckSerializer)
    @action(detail=True, methods=["post"])
    def archive(self, request, company_id, pk):
        return self._state(RegularCheck.State.ARCHIVED)

    @extend_schema(responses=s.LearningRoundSerializer(many=True))
    @action(detail=True, methods=["get"])
    def rounds(self, request, company_id, pk):
        check = self.get_object()
        rows = CheckRound.objects.filter(regular_check=check).order_by("-starts_at")[:52]
        scope = self.branch_scope
        return Response(
            s.LearningRoundSerializer(
                [quiz_queries.round_row(row, branch_ids=scope) for row in rows], many=True
            ).data
        )

    @extend_schema(responses=s.LearningRoundDetailSerializer)
    @action(detail=True, methods=["get"], url_path=r"rounds/(?P<round_id>\d+)")
    def round(self, request, company_id, pk, round_id):
        check = self.get_object()
        found = get_object_or_404(CheckRound, regular_check=check, pk=round_id)
        shape = quiz_queries.round_detail(found, branch_ids=self.branch_scope)
        return Response(s.LearningRoundDetailSerializer(shape).data)


# Skills ------------------------------------------------------------------------------------


class SkillsView(LearningOn, Scope, OwnerAPIView):
    perm = READ

    @extend_schema(
        parameters=[
            BRANCH_PARAM,
            OpenApiParameter("position", int),
            OpenApiParameter("topic", int, description="Only this topic."),
            OpenApiParameter("sort", int, description="This topic's weakest people first."),
        ],
        responses=s.LearningSkillMatrixSerializer,
    )
    def get(self, request, company_id):
        params = request.query_params
        scope = self.branch_scope
        branch = self.branches() if params.get("branch") else None
        topic = _int(params.get("topic"))
        found = skills.matrix(
            self.company,
            branch_ids=scope,
            branch=branch,
            position_id=_int(params.get("position")),
            topic_ids=[topic] if topic else None,
            sort_topic=_int(params.get("sort")),
        )
        return Response(s.LearningSkillMatrixSerializer(quiz_queries.matrix_shape(found)).data)


class PersonSkillsView(LearningOn, Scope, OwnerAPIView):
    perm = READ

    @extend_schema(
        operation_id="owner_learning_person_skills", responses=s.LearningPersonSkillsSerializer
    )
    def get(self, request, company_id, member_id):
        member = self.member(member_id)
        return Response(s.LearningPersonSkillsSerializer(quiz_queries.person_skills(member)).data)


# Suggestions -------------------------------------------------------------------------------


class SuggestionViewSet(LearningOn, mixins.ListModelMixin, OwnerViewSet):
    perm = READ
    perms_by_action = {"accept": MANAGE, "dismiss": MANAGE}
    pagination_class = None
    serializer_class = s.LearningSuggestionSerializer
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return TutorSuggestion.objects.none()
        state = self.request.query_params.get("state", TutorSuggestion.State.OPEN)
        rows = suggestions.visible(self.membership, state=None if state == "all" else state)
        kind = self.request.query_params.get("kind")
        return rows.filter(kind=kind) if kind else rows

    @extend_schema(
        parameters=[
            OpenApiParameter("state", str, enum=["open", "accepted", "dismissed", "done", "all"]),
            OpenApiParameter("kind", str, enum=list(TutorSuggestion.Kind.values)),
        ],
        responses=s.LearningSuggestionSerializer(many=True),
    )
    def list(self, request, *args, **kwargs):
        rows = self.get_queryset()[:200]
        return Response(
            s.LearningSuggestionSerializer(
                [quiz_queries.suggestion_row(row) for row in rows], many=True
            ).data
        )

    def _found(self) -> TutorSuggestion:
        found = (
            suggestions.visible(self.membership, state=None).filter(pk=self.kwargs["pk"]).first()
        )
        if found is None:
            raise NotFound
        return found

    @extend_schema(request=None, responses=s.LearningSuggestionSerializer)
    @action(detail=True, methods=["post"])
    def accept(self, request, company_id, pk):
        row = suggestions.accept(self._found(), by=self.membership)
        row.refresh_from_db()
        return Response(s.LearningSuggestionSerializer(quiz_queries.suggestion_row(row)).data)

    @extend_schema(request=None, responses=s.LearningSuggestionSerializer)
    @action(detail=True, methods=["post"])
    def dismiss(self, request, company_id, pk):
        row = suggestions.dismiss(self._found(), by=self.membership)
        row.refresh_from_db()
        return Response(s.LearningSuggestionSerializer(quiz_queries.suggestion_row(row)).data)


# Drafts ------------------------------------------------------------------------------------


class DraftViewSet(LearningOn, mixins.ListModelMixin, mixins.RetrieveModelMixin, OwnerViewSet):
    perm = MANAGE
    pagination_class = None
    serializer_class = s.LearningDraftJobSerializer
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return QuestionDraftJob.objects.none()
        return (
            QuestionDraftJob.objects.filter(company=self.company)
            .select_related("page", "lesson", "topic")
            .order_by("-created_at", "-pk")
        )

    @extend_schema(responses=s.LearningDraftJobSerializer(many=True))
    def list(self, request, *args, **kwargs):
        rows = self.get_queryset()[:50]
        return Response(
            s.LearningDraftJobSerializer(
                [quiz_queries.draft_row(job) for job in rows], many=True
            ).data
        )

    @extend_schema(responses=s.LearningDraftJobDetailSerializer)
    def retrieve(self, request, *args, **kwargs):
        job = self.get_object()
        written = quiz_queries.questions(self.company, draft_job=job.pk)
        shape = quiz_queries.draft_row(job) | {
            "questions": quiz_queries.question_rows(written, request.user)
        }
        return Response(s.LearningDraftJobDetailSerializer(shape).data)

    @extend_schema(
        request=s.LearningDraftCreateSerializer, responses={201: s.LearningDraftJobSerializer}
    )
    def create(self, request, company_id):
        data = _clean(s.LearningDraftCreateSerializer, request.data)
        job = drafting.create_job(self.company, by=self.membership, **data)
        return Response(
            s.LearningDraftJobSerializer(quiz_queries.draft_row(job)).data,
            status=status.HTTP_201_CREATED,
        )
