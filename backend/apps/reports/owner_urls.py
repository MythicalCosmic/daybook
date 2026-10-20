"""Owner endpoints of team reports, mounted at `/api/v1/owner/companies/<int:company_id>/`
(docs/PLAN-OWNER.md §4.1: `reports/`)."""

from django.urls import path

from apps.reports.owner_api import RoutineReportView, TeamReportView

urlpatterns = [
    path("reports/team/", TeamReportView.as_view(), name="owner-reports-team"),
    path("reports/routines/", RoutineReportView.as_view(), name="owner-reports-routines"),
]
