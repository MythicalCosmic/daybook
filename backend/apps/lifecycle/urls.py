"""Employee endpoints, mounted at `/api/v1/companies/<int:company_id>/`."""

from django.urls import path

from apps.lifecycle import api, review_urls

urlpatterns = [
    path("lifecycle/records/", api.MyRecordsView.as_view(), name="lifecycle-my-records"),
    path("lifecycle/records/<int:pk>/", api.MyRecordView.as_view(), name="lifecycle-my-record"),
    path(
        "lifecycle/records/<int:pk>/acknowledge/",
        api.AcknowledgeView.as_view(),
        name="lifecycle-my-record-acknowledge",
    ),
    path(
        "lifecycle/records/<int:pk>/explain/",
        api.ExplainView.as_view(),
        name="lifecycle-my-record-explain",
    ),
    path("lifecycle/leaving/", api.MyLeavingView.as_view(), name="lifecycle-my-leaving"),
    path(
        "lifecycle/leaving/<int:pk>/withdraw/",
        api.WithdrawLeavingView.as_view(),
        name="lifecycle-my-leaving-withdraw",
    ),
    path(
        "lifecycle/leaving/<int:pk>/exit/",
        api.ExitAnswersView.as_view(),
        name="lifecycle-my-leaving-exit",
    ),
    path("lifecycle/career/", api.MyCareerView.as_view(), name="lifecycle-my-career"),
    # Performance reviews.
    *review_urls.urlpatterns,
]
