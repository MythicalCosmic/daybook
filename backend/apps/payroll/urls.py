"""Employee endpoints, mounted at `/api/v1/companies/<int:company_id>/`."""

from django.urls import path

from apps.payroll import api

urlpatterns = [
    path("payroll/earnings/current/", api.EarningsView.as_view(), name="payroll-my-earnings"),
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
    path("payroll/payslips/", api.MyPayslipsView.as_view(), name="payroll-my-payslips"),
    path("payroll/payslips/<int:pk>/", api.MyPayslipView.as_view(), name="payroll-my-payslip"),
    path(
        "payroll/payslips/<int:pk>/pdf/",
        api.MyPayslipPdfView.as_view(),
        name="payroll-my-payslip-pdf",
    ),
    path(
        "payroll/payslips/<int:pk>/received/",
        api.ReceivedView.as_view(),
        name="payroll-my-payslip-received",
    ),
]
