"""Employee endpoints, mounted at `/api/v1/companies/<int:company_id>/`."""

from django.urls import path

from apps.lifecycle import api

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
]
