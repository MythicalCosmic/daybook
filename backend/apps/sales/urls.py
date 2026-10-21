"""Employee endpoints, mounted at `/api/v1/companies/<int:company_id>/` (all under `sales/`)."""

from django.urls import path

from apps.sales import api

urlpatterns = [
    path("sales/shifts/current/", api.CurrentView.as_view(), name="sales-kassa-current"),
    path("sales/shifts/", api.ShiftListView.as_view(), name="sales-kassa-shifts"),
    path("sales/shifts/<int:pk>/", api.ShiftDetailView.as_view(), name="sales-kassa-shift"),
    path("sales/shifts/<int:pk>/close/", api.CloseView.as_view(), name="sales-kassa-close"),
    path(
        "sales/shifts/<int:pk>/movements/", api.MovementView.as_view(), name="sales-kassa-movements"
    ),
    path("sales/entries/", api.EntryView.as_view(), name="sales-kassa-entries"),
    path(
        "sales/entries/<int:pk>/void/", api.EntryVoidView.as_view(), name="sales-kassa-entry-void"
    ),
    path(
        "sales/handovers/pending/", api.PendingHandoversView.as_view(), name="sales-kassa-handovers"
    ),
    path(
        "sales/handovers/<int:pk>/confirm/",
        api.HandoverAnswerView.as_view(answer="confirm"),
        name="sales-kassa-handover-confirm",
    ),
    path(
        "sales/handovers/<int:pk>/decline/",
        api.HandoverAnswerView.as_view(answer="decline"),
        name="sales-kassa-handover-decline",
    ),
]
