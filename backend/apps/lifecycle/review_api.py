"""Employee (mini app) endpoints of performance reviews, under
`/api/v1/companies/<id>/lifecycle/reviews/…` (docs/PLAN-OWNER.md §13.4: "Self-review forms and
my goals"):

    GET   lifecycle/reviews/                   my open rounds, my published reviews, my goals
    GET   lifecycle/reviews/{id}/              one of mine (the reviewer's part once published)
    PATCH lifecycle/reviews/{id}/ {answers}    my draft, kept as I go
    POST  lifecycle/reviews/{id}/send/ {answers?}   I send my answers
    POST  lifecycle/reviews/{id}/acknowledge/  I have read my published review

Only the person's own; nobody else's review is ever here. A suspended person may still read
theirs (changes are refused). While the HR module is off the endpoints answer 403.
"""

from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.lifecycle import review_queries, reviews
from apps.lifecycle import review_serializers as rs
from apps.lifecycle.api import MemberView
from apps.lifecycle.models import Review, ReviewCycle


class MyReviewView(MemberView):
    def mine(self):
        return Review.objects.filter(membership=self.membership).select_related(
            "cycle", "company", "reviewer", "promotion_position", "job_change"
        )

    def review(self, pk) -> Review:
        found = self.mine().exclude(cycle__status=ReviewCycle.Status.DRAFT).filter(pk=pk).first()
        if found is None:
            raise NotFound
        return found

    def shown(self, review: Review) -> dict:
        return rs.MyReviewSerializer(self.review(review.pk), context=self.context()).data


class MyReviewsView(MyReviewView):
    @extend_schema(
        responses=rs.MyReviewsSerializer, operation_id="v1_companies_lifecycle_my_reviews"
    )
    def get(self, request, company_id):
        rows = list(
            self.mine()
            .exclude(cycle__status=ReviewCycle.Status.DRAFT)
            .order_by("-cycle__period_end", "-pk")
        )
        current = [
            row for row in rows if row.published_at is None and row.cycle.status in reviews.OPEN
        ]
        past = sorted(
            (row for row in rows if row.published_at is not None),
            key=lambda row: row.published_at,
            reverse=True,
        )
        goals = review_queries.open_goals(self.membership).select_related("review__cycle")
        context = self.context()
        return Response(
            {
                "open": rs.MyReviewRowSerializer(current, many=True, context=context).data,
                "past": rs.MyReviewRowSerializer(past, many=True, context=context).data,
                "goals": rs.MyGoalSerializer(goals, many=True).data,
            }
        )


class MyReviewDetailView(MyReviewView):
    @extend_schema(responses=rs.MyReviewSerializer)
    def get(self, request, company_id, pk):
        return Response(self.shown(self.review(pk)))

    @extend_schema(request=rs.SelfWriteSerializer, responses=rs.MyReviewSerializer)
    def patch(self, request, company_id, pk):
        serializer = rs.SelfWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        answers = {key: dict(value) for key, value in serializer.validated_data["answers"].items()}
        review = reviews.save_self(self.review(pk), by=self.membership, answers=answers)
        return Response(self.shown(review))


class SendView(MyReviewView):
    @extend_schema(request=rs.SelfSendSerializer, responses=rs.MyReviewSerializer)
    def post(self, request, company_id, pk):
        serializer = rs.SelfSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        answers = serializer.validated_data.get("answers")
        if answers is not None:
            answers = {key: dict(value) for key, value in answers.items()}
        review = reviews.send_self(self.review(pk), by=self.membership, answers=answers)
        return Response(self.shown(review))


class AcknowledgeReviewView(MyReviewView):
    @extend_schema(request=None, responses=rs.MyReviewSerializer)
    def post(self, request, company_id, pk):
        review = reviews.acknowledge(self.review(pk), by=self.membership)
        return Response(self.shown(review))
