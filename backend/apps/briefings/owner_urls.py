"""Owner endpoints, mounted at `/api/v1/owner/companies/<int:company_id>/`.

An optional `root_urlpatterns` list is mounted at `/api/v1/owner/` instead, for the few
owner endpoints outside a company.
"""

from django.urls import path

from apps.briefings import owner_api as views

urlpatterns = [
    path("briefings/", views.BriefingListView.as_view(), name="owner-briefings"),
    path("briefings/latest/", views.BriefingLatestView.as_view(), name="owner-briefings-latest"),
    path(
        "briefings/regenerate/",
        views.BriefingRegenerateView.as_view(),
        name="owner-briefings-regenerate",
    ),
    path(
        "briefings/settings/",
        views.BriefingSettingsView.as_view(),
        name="owner-briefings-settings",
    ),
    path(
        "briefings/advisor/conversations/",
        views.AdvisorConversationsView.as_view(),
        name="owner-briefings-advisor-conversations",
    ),
    path(
        "briefings/<int:briefing_id>/",
        views.BriefingDetailView.as_view(),
        name="owner-briefings-detail",
    ),
]
