"""Owner dashboard endpoints of performance reviews (`lifecycle/…`, docs/PLAN-OWNER.md §13.4
"Reviews"), all for reviews.manage:

    GET    lifecycle/review-rounds/?status            the rounds, with how far each has got
    POST   lifecycle/review-rounds/ {name, period_start, period_end, self_due_on,
           manager_due_on, questions, positions, branches, open}
    GET    lifecycle/review-rounds/template/          a pharmacy's ready questions
    GET    lifecycle/review-rounds/preview/?position&branch   who would be in it, their reviewers
    GET    PATCH DELETE lifecycle/review-rounds/{id}/  (a draft changes freely and is deleted)
    POST   lifecycle/review-rounds/{id}/open/ · …/advance/ · …/close/ · …/remind/
    GET    lifecycle/review-rounds/{id}/reviews/?q&state&mine&branch   its people
    GET    lifecycle/review-rounds/{id}/results/      ratings, outcomes, cost, by branch

    GET    PATCH lifecycle/reviews/{id}/              the review (its reviewer and owners)
    POST   lifecycle/reviews/{id}/publish/ · …/reviewer/ {reviewer_id}
    DELETE lifecycle/reviews/{id}/                    take them out of the round
    PATCH  lifecycle/review-goals/{id}/ {progress, status, note}
    GET    lifecycle/people/{member_id}/reviews/      Person 360's career line

Company- and branch-scoped (a review outside what the viewer may read answers 404), 403 while
the HR module is off. The rules are apps.lifecycle.reviews'.
"""

from django.db.models import Q
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from apps.console.base import OwnerAPIView, OwnerViewSet
from apps.hr import queries as hr_queries
from apps.lifecycle import review_queries, reviews
from apps.lifecycle import review_serializers as rs
from apps.lifecycle.models import Review, ReviewCycle, ReviewGoal
from apps.lifecycle.owner_api import ModuleOn
from apps.members.models import Membership, Position
from apps.members.permissions import Perm
from apps.members.queries import branch_ref, person_ref

ROUND_STATUSES = tuple(ReviewCycle.Status.values)
ROW_STATES = ("self_late", "self_waiting", "to_write", "published")


def _ids(params, name: str) -> list[int]:
    found = []
    for value in params.getlist(name):
        for part in str(value).split(","):
            if part.strip().isdigit():
                found.append(int(part))
    return found


class ReviewContext:
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["today"] = hr_queries.today(self.company)
        return context


class RoundViewSet(
    ModuleOn,
    ReviewContext,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    OwnerViewSet,
):
    """Review rounds: drafts, open ones with their progress, closed ones with their results."""

    perm = Perm.REVIEWS_MANAGE
    serializer_class = rs.RoundSerializer
    pagination_class = None
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ReviewCycle.objects.none()
        rows = (
            review_queries.cycles_for(self.membership)
            .select_related("company", "created_by__user")
            .prefetch_related("positions", "branches")
        )
        if self.action == "list":
            wanted = [value for value in self.request.query_params.getlist("status") if value]
            wanted = [value for value in wanted if value in ROUND_STATUSES]
            if wanted:
                rows = rows.filter(status__in=wanted)
        return rows.order_by("-period_end", "-pk")

    @extend_schema(parameters=[OpenApiParameter("status", str, many=True, enum=[*ROUND_STATUSES])])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def shown(self, cycle: ReviewCycle) -> dict:
        return self.get_serializer(self.get_queryset().get(pk=cycle.pk)).data

    def _write(self, serializer_class, *, partial: bool) -> dict:
        serializer = serializer_class(data=self.request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        if "questions" in data:
            data["questions"] = [dict(question) for question in data["questions"]]
        return data

    @extend_schema(request=rs.RoundWriteSerializer, responses={201: rs.RoundSerializer})
    def create(self, request, company_id):
        data = self._write(rs.RoundWriteSerializer, partial=False)
        opening = data.pop("open", False)
        cycle = reviews.create_cycle(self.company, by=self.membership, **data)
        if opening:
            cycle = reviews.open_cycle(cycle, by=self.membership)
        return Response(self.shown(cycle), status=status.HTTP_201_CREATED)

    @extend_schema(request=rs.RoundUpdateSerializer, responses=rs.RoundSerializer)
    def partial_update(self, request, company_id, pk):
        data = self._write(rs.RoundUpdateSerializer, partial=True)
        cycle = reviews.update_cycle(self.get_object(), by=self.membership, **data)
        return Response(self.shown(cycle))

    @extend_schema(responses={204: None})
    def destroy(self, request, company_id, pk):
        reviews.delete_cycle(self.get_object(), by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=None, responses=rs.RoundSerializer)
    @action(detail=True, methods=["post"])
    def open(self, request, company_id, pk):
        cycle = reviews.open_cycle(self.get_object(), by=self.membership)
        return Response(self.shown(cycle))

    @extend_schema(request=None, responses=rs.RoundSerializer)
    @action(detail=True, methods=["post"])
    def advance(self, request, company_id, pk):
        cycle = reviews.advance(self.get_object(), by=self.membership)
        return Response(self.shown(cycle))

    @extend_schema(request=None, responses=rs.RoundSerializer)
    @action(detail=True, methods=["post"])
    def close(self, request, company_id, pk):
        cycle = reviews.close_cycle(self.get_object(), by=self.membership)
        return Response(self.shown(cycle))

    @extend_schema(request=None, responses=rs.RemindedSerializer)
    @action(detail=True, methods=["post"])
    def remind(self, request, company_id, pk):
        cycle = self.get_object()
        rows = review_queries.visible_reviews(self.membership, cycle)
        return Response(reviews.remind(cycle, by=self.membership, rows=rows))

    @extend_schema(
        parameters=[
            OpenApiParameter("q", str),
            OpenApiParameter("state", str, enum=[*ROW_STATES]),
            OpenApiParameter("mine", bool, description="Only the reviews the viewer gives."),
            OpenApiParameter("branch", int, many=True),
        ],
        responses=rs.ReviewRowSerializer(many=True),
    )
    @action(detail=True, methods=["get"], url_path="reviews")
    def people(self, request, company_id, pk):
        cycle = self.get_object()
        rows = (
            review_queries.visible_reviews(self.membership, cycle)
            .select_related(*review_queries.REVIEW_RELATIONS)
            .order_by("membership__first_name", "membership__last_name", "pk")
        )
        params = request.query_params
        if params.get("mine") in ("1", "true"):
            rows = rows.filter(reviewer=self.membership)
        if branches := _ids(params, "branch"):
            rows = rows.filter(membership__branches__in=branches).distinct()
        if q := (params.get("q") or "").strip():
            for word in q.split()[:4]:
                rows = rows.filter(
                    Q(membership__first_name__icontains=word)
                    | Q(membership__last_name__icontains=word)
                )
        rows = list(rows)
        today = hr_queries.today(self.company)
        late = reviews.late(cycle, rows, today=today)
        state = params.get("state")
        if state == "self_late":
            rows = [row for row in rows if "self" in late.get(row.pk, [])]
        elif state == "self_waiting":
            rows = [row for row in rows if row.self_sent_at is None and not row.published_at]
        elif state == "to_write":
            rows = [row for row in rows if row.published_at is None]
        elif state == "published":
            rows = [row for row in rows if row.published_at is not None]
        context = self.get_serializer_context() | {
            "late": late,
            "bonuses": review_queries.adjustments(self.company, [row.bonus_id for row in rows]),
        }
        return Response(rs.ReviewRowSerializer(rows, many=True, context=context).data)

    @extend_schema(responses=rs.ResultsSerializer)
    @action(detail=True, methods=["get"])
    def results(self, request, company_id, pk):
        cycle = self.get_object()
        rows = list(
            review_queries.visible_reviews(self.membership, cycle).select_related(
                *review_queries.REVIEW_RELATIONS
            )
        )
        return Response(review_queries.results(cycle, rows, member=self.membership))

    @extend_schema(responses=rs.QuestionSerializer(many=True))
    @action(detail=False, methods=["get"])
    def template(self, request, company_id):
        return Response(reviews.template())

    @extend_schema(
        parameters=[
            OpenApiParameter("position", int, many=True),
            OpenApiParameter("branch", int, many=True),
        ],
        responses=rs.PreviewSerializer,
    )
    @action(detail=False, methods=["get"])
    def preview(self, request, company_id):
        params = request.query_params
        found = reviews.preview(
            self.company,
            by=self.membership,
            positions=_ids(params, "position"),
            branches=_ids(params, "branch"),
        )
        counts: dict[int | None, list] = {}
        for _person, reviewer in found:
            key = reviewer.pk if reviewer else None
            entry = counts.setdefault(key, [reviewer, 0])
            entry[1] += 1
        return Response(
            {
                "count": len(found),
                "reviewers": [
                    {"reviewer": person_ref(reviewer), "people": count}
                    for reviewer, count in sorted(
                        counts.values(), key=lambda item: (-item[1], str(item[0] or ""))
                    )
                ],
                "people": [
                    {
                        "member": person_ref(person),
                        "position": person.position.name if person.position_id else None,
                        "home_branch": branch_ref(person.home_branch),
                        "reviewer": person_ref(reviewer),
                    }
                    for person, reviewer in found
                ],
            }
        )


class ReviewViewSet(
    ModuleOn,
    ReviewContext,
    mixins.RetrieveModelMixin,
    OwnerViewSet,
):
    """One review: its reviewer writes and publishes it; owners read it; a round's runner may
    give it to another reviewer or take the person out of the round."""

    perm = Perm.REVIEWS_MANAGE
    serializer_class = rs.ReviewSerializer
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Review.objects.none()
        return (
            Review.objects.for_company(self.company)
            .select_related(*review_queries.REVIEW_RELATIONS, "published_by__user")
            .prefetch_related("goals")
        )

    def readable(self) -> Review:
        review = self.get_object()
        if not reviews.may_read(self.membership, review):
            raise NotFound
        return review

    def run_target(self) -> Review:
        """A review the viewer may manage as its round's runner (inside their scope)."""
        review = self.get_object()
        visible = review_queries.visible_reviews(self.membership, review.cycle)
        if (
            not reviews.may_run(self.membership, review.cycle)
            or not visible.filter(pk=review.pk).exists()
        ):
            raise NotFound
        return review

    def shown(self, review: Review) -> dict:
        return self.get_serializer(self.get_queryset().get(pk=review.pk)).data

    def retrieve(self, request, company_id, pk):
        review = reviews.open_for_reviewer(self.readable(), by=self.membership)
        return Response(self.shown(review))

    @extend_schema(request=rs.ManagerWriteSerializer, responses=rs.ReviewSerializer)
    def partial_update(self, request, company_id, pk):
        review = self.readable()
        serializer = rs.ManagerWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        if "answers" in data:
            data["answers"] = {key: dict(value) for key, value in data["answers"].items()}
        if "goals" in data:
            data["goals"] = [dict(goal) for goal in data["goals"]]
        if "promotion_position_id" in data:
            position_id = data.pop("promotion_position_id")
            position = None
            if position_id is not None:
                position = Position.objects.filter(company=self.company, pk=position_id).first()
                if position is None:
                    raise ValidationError(
                        {"promotion_position_id": [_("Pick a position of this company.")]}
                    )
            data["promotion_position"] = position
        review = reviews.save_manager(review, by=self.membership, **data)
        return Response(self.shown(review))

    @extend_schema(request=None, responses=rs.ReviewSerializer)
    @action(detail=True, methods=["post"])
    def publish(self, request, company_id, pk):
        review = reviews.publish(self.readable(), by=self.membership)
        return Response(self.shown(review))

    @extend_schema(request=rs.ReassignSerializer, responses=rs.ReviewRowSerializer)
    @action(detail=True, methods=["post"])
    def reviewer(self, request, company_id, pk):
        review = self.run_target()
        serializer = rs.ReassignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reviewer = (
            Membership.objects.filter(
                company=self.company, pk=serializer.validated_data["reviewer_id"]
            )
            .select_related("role", "user", "company")
            .first()
        )
        if reviewer is None:
            raise ValidationError({"reviewer_id": [_("Pick someone of this company.")]})
        review = reviews.reassign(review, by=self.membership, reviewer=reviewer)
        review = self.get_queryset().get(pk=review.pk)
        context = self.get_serializer_context() | {
            "late": reviews.late(review.cycle, [review], today=hr_queries.today(self.company))
        }
        return Response(rs.ReviewRowSerializer(review, context=context).data)

    @extend_schema(responses={204: None})
    def destroy(self, request, company_id, pk):
        reviews.remove(self.run_target(), by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)


class GoalViewSet(ModuleOn, ReviewContext, OwnerViewSet):
    """A published improvement plan's goal, marked by the reviewer (or an owner)."""

    perm = Perm.REVIEWS_MANAGE
    serializer_class = rs.GoalSerializer
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ReviewGoal.objects.none()
        return ReviewGoal.objects.for_company(self.company).select_related(
            "review__cycle", "review__membership", "review__reviewer"
        )

    @extend_schema(request=rs.GoalUpdateSerializer, responses=rs.GoalSerializer)
    def partial_update(self, request, company_id, pk):
        goal = self.get_object()
        if not reviews.may_read(self.membership, goal.review):
            raise NotFound
        serializer = rs.GoalUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        goal = reviews.update_goal(goal, by=self.membership, **serializer.validated_data)
        return Response(rs.GoalSerializer(goal).data)


class PersonReviewsView(ModuleOn, OwnerAPIView):
    """Person 360's career line: the person's published reviews (reviews.manage)."""

    perm = Perm.REVIEWS_MANAGE

    @extend_schema(responses=rs.CareerReviewSerializer(many=True))
    def get(self, request, company_id, member_id):
        person = hr_queries.person(self.company, member_id, branch_ids=self.branch_scope)
        if person is None:
            raise NotFound
        rows = review_queries.published_for(person)
        return Response(rs.career_reviews(rows, viewer=self.membership))
