"""Owner endpoints of business goals, mounted at `/api/v1/owner/companies/<int:company_id>/`."""

from django.urls import path

from apps.goals import owner_api

urlpatterns = [
    path("goals/", owner_api.GoalsView.as_view(), name="goals"),
    path("goals/metrics/", owner_api.MetricsView.as_view(), name="goals-metrics"),
    path("goals/preview/", owner_api.PreviewView.as_view(), name="goals-preview"),
    path("goals/<int:pk>/", owner_api.GoalView.as_view(), name="goal"),
    path("goals/<int:pk>/archive/", owner_api.GoalArchiveView.as_view(), name="goal-archive"),
    path("goals/<int:pk>/restore/", owner_api.GoalRestoreView.as_view(), name="goal-restore"),
]
