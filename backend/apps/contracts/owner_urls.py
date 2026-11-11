"""Owner endpoints of business contracts, mounted at `/api/v1/owner/companies/<int:company_id>/`."""

from django.urls import path

from apps.contracts import owner_api

urlpatterns = [
    path("contracts/", owner_api.ContractsView.as_view(), name="contracts-list"),
    path("contracts/settings/", owner_api.SettingsView.as_view(), name="contracts-settings"),
    path("contracts/summary/", owner_api.SummaryView.as_view(), name="contracts-summary"),
    path("contracts/options/", owner_api.OptionsView.as_view(), name="contracts-options"),
    path("contracts/files/<int:file_id>/", owner_api.FileView.as_view(), name="contracts-file"),
    path("contracts/<int:contract_id>/", owner_api.ContractView.as_view(), name="contracts-detail"),
    path(
        "contracts/<int:contract_id>/renew/",
        owner_api.RenewView.as_view(),
        name="contracts-renew",
    ),
    path(
        "contracts/<int:contract_id>/terminate/",
        owner_api.TerminateView.as_view(),
        name="contracts-terminate",
    ),
    path(
        "contracts/<int:contract_id>/keep-renewing/",
        owner_api.KeepRenewingView.as_view(),
        name="contracts-keep-renewing",
    ),
    path(
        "contracts/<int:contract_id>/stop-renewing/",
        owner_api.StopRenewingView.as_view(),
        name="contracts-stop-renewing",
    ),
    path(
        "contracts/<int:contract_id>/files/",
        owner_api.FilesView.as_view(),
        name="contracts-files",
    ),
]
