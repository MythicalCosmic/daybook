"""Employee endpoints, mounted at `/api/v1/companies/<int:company_id>/`."""

from django.urls import path

from apps.attendance import api

urlpatterns = [
    path("attendance/", api.MonthView.as_view(), name="attendance-month"),
    path("attendance/today/", api.TodayView.as_view(), name="attendance-today"),
    path("attendance/check-in/", api.CheckInView.as_view(), name="attendance-check-in"),
    path("attendance/check-out/", api.CheckOutView.as_view(), name="attendance-check-out"),
    path("attendance/shifts/", api.ShiftsView.as_view(), name="attendance-my-shifts"),
    path(
        "attendance/corrections/", api.CorrectionsView.as_view(), name="attendance-my-corrections"
    ),
    path("attendance/swaps/", api.SwapsView.as_view(), name="attendance-my-swaps"),
    path(
        "attendance/swaps/candidates/",
        api.CandidatesView.as_view(),
        name="attendance-swap-candidates",
    ),
    path(
        "attendance/swaps/<int:pk>/<str:verb>/",
        api.SwapActionView.as_view(),
        name="attendance-swap-action",
    ),
    path("attendance/open-shifts/", api.OpenShiftsView.as_view(), name="attendance-open-shifts"),
    path(
        "attendance/open-shifts/<int:pk>/claim/",
        api.ClaimView.as_view(),
        name="attendance-open-shift-claim",
    ),
    path("attendance/board/", api.BoardView.as_view(), name="attendance-my-board"),
]
