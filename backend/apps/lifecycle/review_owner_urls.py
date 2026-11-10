"""Owner endpoints of performance reviews, included by `owner_urls.py` (mounted at
`/api/v1/owner/companies/<int:company_id>/`)."""

from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.lifecycle import review_owner_api

router = SimpleRouter()
router.register(
    "lifecycle/review-rounds", review_owner_api.RoundViewSet, basename="lifecycle-review-round"
)
router.register("lifecycle/reviews", review_owner_api.ReviewViewSet, basename="lifecycle-review")
router.register(
    "lifecycle/review-goals", review_owner_api.GoalViewSet, basename="lifecycle-review-goal"
)

urlpatterns = [
    *router.urls,
    path(
        "lifecycle/people/<int:member_id>/reviews/",
        review_owner_api.PersonReviewsView.as_view(),
        name="lifecycle-person-reviews",
    ),
]
