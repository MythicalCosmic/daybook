"""Employee (mini app) endpoints of package Q2, routed in `urls_quizzes.py` under
`/api/v1/companies/<id>/` (docs/PLAN-LEARNING.md §13, the contract with the mini app):

    GET  learning/quizzes/{id}/?assignment=&entry=   the quiz's intro: may I start, and why not
    POST learning/quizzes/{id}/attempts/             start (201) or resume (200) -> AttemptPlay
    GET  learning/attempts/{id}/                     AttemptPlay in progress, else AttemptResult
    PUT  learning/attempts/{id}/answers/             {question, answer} -> 204 (autosave)
    POST learning/attempts/{id}/finish/              -> AttemptResult
    GET  learning/daily/                             today's question of the day and the streak
    POST learning/daily/{id}/answer/                 {answer} -> the result
    GET  learning/checks/                            my check entries: open, then the last closed

A person only ever sees their own; anything else answers 404, like everything here while the
company's `learning` module is off. No right answer leaves before the question is answered.
"""

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, PolymorphicProxySerializer, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.learning import attempts, checks, conf, daily
from apps.learning import serializers_quizzes as s
from apps.learning.models import Assignment, Attempt, CheckEntry, DailyQuestion, Quiz
from apps.members.api import IsCompanyMember
from apps.members.models import Membership


class LearningOn(BasePermission):
    """Everything of learning is 404 while the module is off."""

    def has_permission(self, request, view):
        if not conf.is_on(view.membership.company):
            raise NotFound
        return True


class LearnerView(APIView):
    permission_classes = (IsAuthenticated, IsCompanyMember, LearningOn)
    membership: Membership

    def quiz(self, pk: int) -> Quiz:
        return get_object_or_404(Quiz, company_id=self.membership.company_id, pk=pk)

    def context(self, data) -> tuple[Assignment | None, CheckEntry | None]:
        """The `assignment` and `entry` asked for: the person's own, else 404."""
        assignment = entry = None
        for name in ("assignment", "entry"):
            value = data.get(name)
            if value in (None, ""):
                continue
            try:
                pk = int(value)
            except TypeError, ValueError:
                raise ValidationError({name: ["Give an id."]}) from None
            if name == "assignment":
                assignment = (
                    Assignment.objects.filter(membership=self.membership, pk=pk)
                    .select_related("course")
                    .first()
                )
                if assignment is None:
                    raise NotFound
            else:
                entry = (
                    CheckEntry.objects.filter(membership=self.membership, pk=pk)
                    .select_related("check_round__regular_check")
                    .first()
                )
                if entry is None:
                    raise NotFound
        return assignment, entry

    def attempt(self, pk: int) -> Attempt:
        found = (
            Attempt.objects.filter(membership=self.membership, pk=pk).select_related("quiz").first()
        )
        if found is None:
            raise NotFound
        return found


def intro(quiz: Quiz, found: attempts.Standing) -> dict:
    best = found.best
    return {
        "id": quiz.pk,
        "title": quiz.title,
        "emoji": quiz.emoji,
        "description": quiz.description,
        "questions": found.questions,
        "time_limit_seconds": quiz.time_limit_seconds,
        "pass_percent": quiz.pass_percent,
        "max_attempts": found.max_attempts,
        "attempts_used": found.attempts_used,
        "retry_at": found.retry_at,
        "best": {"percent": best.percent or 0, "passed": bool(best.passed)} if best else None,
        "in_progress": found.in_progress.pk if found.in_progress else None,
        "can_start": found.can_start,
        "reason": found.reason,
    }


CONTEXT_PARAMETERS = [
    OpenApiParameter("assignment", int, description="The assignment it is taken for."),
    OpenApiParameter("entry", int, description="The check entry it answers."),
]


class QuizView(LearnerView):
    @extend_schema(parameters=CONTEXT_PARAMETERS, responses=s.LearningQuizIntroSerializer)
    def get(self, request, company_id, pk):
        quiz = self.quiz(pk)
        assignment, entry = self.context(request.query_params)
        try:
            found = attempts.standing(quiz, self.membership, assignment=assignment, entry=entry)
        except attempts.NotAllowed:
            raise NotFound from None
        return Response(s.LearningQuizIntroSerializer(intro(quiz, found)).data)


class StartAttemptView(LearnerView):
    @extend_schema(
        request=s.LearningStartAttemptSerializer,
        responses={
            201: s.LearningAttemptPlaySerializer,
            200: s.LearningAttemptPlaySerializer,
        },
    )
    def post(self, request, company_id, pk):
        quiz = self.quiz(pk)
        form = s.LearningStartAttemptSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        assignment, entry = self.context(form.validated_data)
        try:
            attempt, started = attempts.start(
                quiz, self.membership, assignment=assignment, entry=entry
            )
        except attempts.NotAllowed:
            raise NotFound from None
        attempt.quiz = quiz
        data = s.LearningAttemptPlaySerializer(attempts.play_shape(attempt, request.user)).data
        return Response(data, status=status.HTTP_201_CREATED if started else status.HTTP_200_OK)


ATTEMPT_VIEW = PolymorphicProxySerializer(
    component_name="LearningAttemptView",
    serializers=[s.LearningAttemptPlaySerializer, s.LearningAttemptResultSerializer],
    resource_type_field_name=None,
)


class AttemptView(LearnerView):
    @extend_schema(
        responses=ATTEMPT_VIEW,
        description="AttemptPlay while in progress (it has `questions`), AttemptResult once "
        "graded (it has `state`). Reading an attempt past its time limit grades it.",
    )
    def get(self, request, company_id, pk):
        attempt = self.attempt(pk)
        attempts.expire_due(quiz=attempt.quiz, member=self.membership)
        attempt.refresh_from_db()
        if attempt.state == Attempt.State.IN_PROGRESS:
            shape = attempts.play_shape(attempt, request.user)
            return Response(s.LearningAttemptPlaySerializer(shape).data)
        shape = attempts.result_shape(attempt, request.user)
        return Response(s.LearningAttemptResultSerializer(shape).data)


class SaveAnswerView(LearnerView):
    @extend_schema(request=s.LearningSaveAnswerSerializer, responses={204: None})
    def put(self, request, company_id, pk):
        attempt = self.attempt(pk)
        form = s.LearningSaveAnswerSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        attempts.save_answer(
            attempt, form.validated_data["question"], form.validated_data.get("answer")
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class FinishAttemptView(LearnerView):
    @extend_schema(request=None, responses=s.LearningAttemptResultSerializer)
    def post(self, request, company_id, pk):
        attempt = attempts.finish(self.attempt(pk))
        shape = attempts.result_shape(attempt, request.user)
        return Response(s.LearningAttemptResultSerializer(shape).data)


class DailyView(LearnerView):
    @extend_schema(responses=s.LearningDailySerializer)
    def get(self, request, company_id):
        found = daily.today_for(self.membership)
        shape = {
            "daily": daily.play_shape(found, request.user) if found else None,
            "streak": daily.streak_of(self.membership),
        }
        return Response(s.LearningDailySerializer(shape).data)


class DailyAnswerView(LearnerView):
    @extend_schema(
        request=s.LearningDailyAnswerSerializer, responses=s.LearningDailyOutcomeSerializer
    )
    def post(self, request, company_id, pk):
        found = DailyQuestion.objects.filter(membership=self.membership, pk=pk).first()
        if found is None:
            raise NotFound
        form = s.LearningDailyAnswerSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        result = daily.answer(found, self.membership, form.validated_data["answer"])
        shape = {
            "correct": result.correct,
            "share": result.share,
            "right_answer": result.right_answer,
            "explanation": result.explanation,
            "points": result.points,
            "streak": result.streak,
        }
        return Response(s.LearningDailyOutcomeSerializer(shape).data)


class ChecksView(LearnerView):
    @extend_schema(responses=s.LearningCheckCardSerializer(many=True))
    def get(self, request, company_id):
        rows = checks.my_checks(self.membership)
        return Response(s.LearningCheckCardSerializer(rows, many=True).data)
