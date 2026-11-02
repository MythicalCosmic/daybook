"""Employee endpoints, mounted at `/api/v1/companies/<int:company_id>/`."""

from django.urls import path

from apps.payroll import api

urlpatterns = [
    path("payroll/adjustments/", api.MyAdjustmentsView.as_view(), name="payroll-my-adjustments"),
    path(
        "payroll/adjustments/<int:pk>/dispute/",
        api.DisputeView.as_view(),
        name="payroll-my-adjustment-dispute",
    ),
    path("payroll/advances/", api.MyAdvancesView.as_view(), name="payroll-my-advances"),
    path(
        "payroll/advances/<int:pk>/cancel/",
        api.CancelAdvanceView.as_view(),
        name="payroll-my-advance-cancel",
    ),
]
