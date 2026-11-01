"""Owner endpoints, mounted at `/api/v1/owner/companies/<int:company_id>/`.

An optional `root_urlpatterns` list is mounted at `/api/v1/owner/` instead, for the few
owner endpoints outside a company.
"""

from django.urls import path

from apps.ai import owner_api

urlpatterns = [
    path("ai/status/", owner_api.StatusView.as_view(), name="owner-ai-status"),
    path("ai/settings/", owner_api.SettingsView.as_view(), name="owner-ai-settings"),
    path("ai/settings/enable/", owner_api.EnableView.as_view(), name="owner-ai-enable"),
    path("ai/settings/disable/", owner_api.DisableView.as_view(), name="owner-ai-disable"),
    path("ai/task-drafts/", owner_api.TaskDraftListView.as_view(), name="owner-ai-task-drafts"),
    path(
        "ai/task-drafts/<int:draft_id>/",
        owner_api.TaskDraftDetailView.as_view(),
        name="owner-ai-task-draft",
    ),
    path(
        "ai/task-drafts/<int:draft_id>/apply/",
        owner_api.TaskDraftApplyView.as_view(),
        name="owner-ai-task-draft-apply",
    ),
    path(
        "ai/task-drafts/<int:draft_id>/discard/",
        owner_api.TaskDraftDiscardView.as_view(),
        name="owner-ai-task-draft-discard",
    ),
    path("ai/agents/", owner_api.AgentListView.as_view(), name="owner-ai-agents"),
    path("ai/agents/<str:key>/", owner_api.AgentView.as_view(), name="owner-ai-agent"),
    path("ai/agents/<str:key>/run/", owner_api.AgentRunView.as_view(), name="owner-ai-agent-run"),
    path("ai/activity/", owner_api.ActivityView.as_view(), name="owner-ai-activity"),
]
