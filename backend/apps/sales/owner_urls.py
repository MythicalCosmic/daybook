"""Owner endpoints, mounted at `/api/v1/owner/companies/<int:company_id>/` (all under `sales/`).

An optional `root_urlpatterns` list is mounted at `/api/v1/owner/` instead, for the few
owner endpoints outside a company.
"""

from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.sales import owner_api

router = SimpleRouter()
router.register(
    "sales/payment-methods", owner_api.PaymentMethodViewSet, basename="sales-payment-method"
)
router.register("sales/registers", owner_api.RegisterViewSet, basename="sales-register")
router.register("sales/targets", owner_api.TargetViewSet, basename="sales-target")
router.register("sales/daily", owner_api.DailyViewSet, basename="sales-daily")
router.register("sales/shifts", owner_api.ShiftViewSet, basename="sales-shift")
router.register("sales/cash-movements", owner_api.MovementViewSet, basename="sales-cash-movement")
router.register("sales/handovers", owner_api.HandoverViewSet, basename="sales-handover")
router.register("sales/entries", owner_api.EntryViewSet, basename="sales-entry")

urlpatterns = [
    path("sales/settings/", owner_api.SettingsView.as_view(), name="sales-settings"),
    path("sales/today/", owner_api.TodayView.as_view(), name="sales-today"),
    path("sales/summary/", owner_api.SummaryView.as_view(), name="sales-summary"),
    path("sales/cashiers/", owner_api.CashiersView.as_view(), name="sales-cashiers"),
    path(
        "sales/cash/positions/", owner_api.CashPositionsView.as_view(), name="sales-cash-positions"
    ),
    path("sales/options/", owner_api.OptionsView.as_view(), name="sales-options"),
    *router.urls,
]
