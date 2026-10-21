"""Owner endpoints, mounted at `/api/v1/owner/companies/<int:company_id>/`.

An optional `root_urlpatterns` list is mounted at `/api/v1/owner/` instead, for the few
owner endpoints outside a company.
"""

from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.attendance.owner_api import (
    BoardView,
    CorrectionViewSet,
    MemberView,
    RecordViewSet,
    RosterView,
    ScheduleViewSet,
    SettingsView,
    ShiftViewSet,
    StaffView,
    SummaryView,
    SwapViewSet,
    TemplateViewSet,
    TimesheetView,
)

router = SimpleRouter()
router.register("attendance/records", RecordViewSet, basename="attendance-record")
router.register("attendance/schedules", ScheduleViewSet, basename="attendance-schedule")
router.register("attendance/templates", TemplateViewSet, basename="attendance-template")
router.register("attendance/shifts", ShiftViewSet, basename="attendance-shift")
router.register("attendance/swaps", SwapViewSet, basename="attendance-swap")
router.register("attendance/corrections", CorrectionViewSet, basename="attendance-correction")

urlpatterns = [
    path("attendance/settings/", SettingsView.as_view(), name="attendance-settings"),
    path("attendance/board/", BoardView.as_view(), name="attendance-board"),
    path("attendance/timesheet/", TimesheetView.as_view(), name="attendance-timesheet"),
    path("attendance/summary/", SummaryView.as_view(), name="attendance-summary"),
    path("attendance/roster/", RosterView.as_view(), name="attendance-roster"),
    path("attendance/staff/", StaffView.as_view(), name="attendance-staff"),
    path(
        "attendance/members/<int:member_id>/",
        MemberView.as_view(),
        name="attendance-member",
    ),
    *router.urls,
]
