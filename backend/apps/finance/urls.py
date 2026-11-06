"""Employee endpoints, mounted at `/api/v1/companies/<int:company_id>/`."""

from django.urls import path

from apps.finance import api

urlpatterns = [
    path("finance/claims/", api.MyClaimsView.as_view(), name="finance-my-claims"),
    path(
        "finance/claims/<int:pk>/cancel/",
        api.CancelClaimView.as_view(),
        name="finance-my-claim-cancel",
    ),
    path(
        "finance/categories/",
        api.ClaimCategoriesView.as_view(),
        name="finance-claim-categories",
    ),
    path("finance/wallet/", api.WalletView.as_view(), name="finance-my-wallet"),
]
