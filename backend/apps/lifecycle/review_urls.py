"""Employee endpoints of performance reviews, included by `urls.py` (mounted at
`/api/v1/companies/<int:company_id>/`)."""

from django.urls import path

from apps.lifecycle import review_api

urlpatterns = [
    path("lifecycle/reviews/", review_api.MyReviewsView.as_view(), name="lifecycle-my-reviews"),
    path(
        "lifecycle/reviews/<int:pk>/",
        review_api.MyReviewDetailView.as_view(),
        name="lifecycle-my-review",
    ),
    path(
        "lifecycle/reviews/<int:pk>/send/",
        review_api.SendView.as_view(),
        name="lifecycle-my-review-send",
    ),
    path(
        "lifecycle/reviews/<int:pk>/acknowledge/",
        review_api.AcknowledgeReviewView.as_view(),
        name="lifecycle-my-review-acknowledge",
    ),
]
