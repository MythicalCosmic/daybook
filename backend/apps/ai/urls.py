"""Employee endpoints, mounted at `/api/v1/companies/<int:company_id>/`."""

from django.urls import path

from apps.ai import api

urlpatterns = [
    path("ai/status/", api.StatusView.as_view(), name="ai-status"),
    path("ai/task-drafts/", api.TaskDraftCreateView.as_view(), name="ai-task-drafts"),
    path(
        "ai/task-drafts/<int:draft_id>/",
        api.TaskDraftDetailView.as_view(),
        name="ai-task-draft",
    ),
    path(
        "ai/task-drafts/<int:draft_id>/apply/",
        api.TaskDraftApplyView.as_view(),
        name="ai-task-draft-apply",
    ),
    path(
        "ai/task-drafts/<int:draft_id>/discard/",
        api.TaskDraftDiscardView.as_view(),
        name="ai-task-draft-discard",
    ),
]
