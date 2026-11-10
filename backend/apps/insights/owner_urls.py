"""Owner endpoints, mounted at `/api/v1/owner/companies/<int:company_id>/`.

An optional `root_urlpatterns` list is mounted at `/api/v1/owner/` instead, for the few
owner endpoints outside a company.
"""

from django.urls import path

from apps.insights import owner_api

urlpatterns = [
    path("cockpit/", owner_api.CockpitView.as_view(), name="insights-cockpit"),
    path("insights/", owner_api.InsightListView.as_view(), name="insights-list"),
    path("insights/settings/", owner_api.SettingsView.as_view(), name="insights-settings"),
    path("insights/check/", owner_api.CheckView.as_view(), name="insights-check"),
    path("insights/<int:pk>/", owner_api.InsightDetailView.as_view(), name="insights-detail"),
    path(
        "insights/<int:pk>/acknowledge/",
        owner_api.AcknowledgeView.as_view(),
        name="insights-acknowledge",
    ),
    path("insights/<int:pk>/dismiss/", owner_api.DismissView.as_view(), name="insights-dismiss"),
    path("insights/<int:pk>/resolve/", owner_api.ResolveView.as_view(), name="insights-resolve"),
    path(
        "insights/<int:pk>/make-task/",
        owner_api.MakeTaskView.as_view(),
        name="insights-make-task",
    ),
]
