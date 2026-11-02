"""Owner endpoints, mounted at `/api/v1/owner/companies/<int:company_id>/`.

An optional `root_urlpatterns` list is mounted at `/api/v1/owner/` instead, for the few
owner endpoints outside a company.
"""

from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.payroll.owner_api import (
    AdjustmentViewSet,
    AdvanceViewSet,
    CompensationViewSet,
    SettingsView,
    TaskRateViewSet,
)

router = SimpleRouter()
router.register("payroll/compensations", CompensationViewSet, basename="payroll-compensation")
router.register("payroll/task-rates", TaskRateViewSet, basename="payroll-task-rate")
router.register("payroll/adjustments", AdjustmentViewSet, basename="payroll-adjustment")
router.register("payroll/advances", AdvanceViewSet, basename="payroll-advance")

urlpatterns = [
    path("payroll/settings/", SettingsView.as_view(), name="payroll-settings"),
    *router.urls,
]
