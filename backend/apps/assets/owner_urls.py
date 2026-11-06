"""Owner endpoints of fixed assets, mounted at `/api/v1/owner/companies/<int:company_id>/`."""

from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.assets import owner_api

router = SimpleRouter()
router.register("assets/categories", owner_api.CategoryViewSet, basename="assets-category")
router.register("assets/items", owner_api.AssetViewSet, basename="assets-item")

urlpatterns = [
    path("assets/settings/", owner_api.SettingsView.as_view(), name="assets-settings"),
    path("assets/summary/", owner_api.SummaryView.as_view(), name="assets-summary"),
    path("assets/files/<int:file_id>/", owner_api.FileView.as_view(), name="assets-file"),
    path("assets/depreciation/", owner_api.DepreciationView.as_view(), name="assets-depreciation"),
    path("assets/movement/", owner_api.MovementView.as_view(), name="assets-movement"),
    path("assets/planning/", owner_api.PlanningView.as_view(), name="assets-planning"),
    path("assets/custody/", owner_api.CustodyView.as_view(), name="assets-custody"),
    path("assets/purchases/", owner_api.PurchasesView.as_view(), name="assets-purchases"),
    path("assets/counts/", owner_api.CountsView.as_view(), name="assets-counts"),
    path("assets/counts/<int:count_id>/", owner_api.CountView.as_view(), name="assets-count"),
    path(
        "assets/counts/<int:count_id>/close/",
        owner_api.CountCloseView.as_view(),
        name="assets-count-close",
    ),
    path(
        "assets/counts/<int:count_id>/lines/<int:line_id>/",
        owner_api.CountLineView.as_view(),
        name="assets-count-line",
    ),
    path("assets/permits/", owner_api.PermitsView.as_view(), name="assets-permits"),
    path("assets/permits/<int:permit_id>/", owner_api.PermitView.as_view(), name="assets-permit"),
    path(
        "assets/permits/<int:permit_id>/file/",
        owner_api.PermitFileView.as_view(),
        name="assets-permit-file",
    ),
    *router.urls,
]
