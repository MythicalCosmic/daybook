"""Owner endpoints of the finance ledger, mounted at `/api/v1/owner/companies/<int:company_id>/`
(docs/PLAN-OWNER.md §4.7: everything lives under `finance/`). Package I adds its rows here.
"""

from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.finance import owner_api, planning_api

router = SimpleRouter()
router.register("finance/accounts", owner_api.AccountViewSet, basename="finance-account")
router.register("finance/categories", owner_api.CategoryViewSet, basename="finance-category")
router.register(
    "finance/counterparties", owner_api.CounterpartyViewSet, basename="finance-counterparty"
)
router.register(
    "finance/transactions", owner_api.TransactionViewSet, basename="finance-transaction"
)
router.register("finance/transfers", owner_api.TransferViewSet, basename="finance-transfer")
router.register("finance/debts", owner_api.DebtViewSet, basename="finance-debt")
# Package I: money planning.
router.register("finance/recurring", planning_api.RecurringViewSet, basename="finance-recurring")
router.register("finance/claims", planning_api.ClaimViewSet, basename="finance-claim")

planning = [
    path(
        "finance/recurring/templates/",
        planning_api.TemplatesView.as_view(),
        name="finance-recurring-templates",
    ),
    path(
        "finance/recurring/templates/<str:key>/apply/",
        planning_api.TemplateApplyView.as_view(),
        name="finance-recurring-template-apply",
    ),
    path("finance/upcoming/", planning_api.UpcomingView.as_view(), name="finance-upcoming"),
    path(
        "finance/reports/forecast/",
        planning_api.ForecastView.as_view(),
        name="finance-report-forecast",
    ),
    path("finance/budgets/", planning_api.BudgetsView.as_view(), name="finance-budgets"),
    path(
        "finance/budgets/copy/", planning_api.BudgetCopyView.as_view(), name="finance-budgets-copy"
    ),
    path("finance/payables/", planning_api.PayablesView.as_view(), name="finance-payables"),
    path(
        "finance/payables/pay/",
        planning_api.PayablesPayView.as_view(),
        name="finance-payables-pay",
    ),
    path(
        "finance/debts/<int:pk>/credit/",
        planning_api.DebtCreditView.as_view(),
        name="finance-debt-credit",
    ),
]

urlpatterns = [
    *planning,
    path("finance/overview/", owner_api.OverviewView.as_view(), name="finance-overview"),
    path("finance/options/", owner_api.OptionsView.as_view(), name="finance-options"),
    path("finance/receipts/", owner_api.ReceiptUploadView.as_view(), name="finance-receipts"),
    path("finance/rates/", owner_api.RatesView.as_view(), name="finance-rates"),
    path("finance/rates/fetch/", owner_api.RateFetchView.as_view(), name="finance-rates-fetch"),
    path("finance/rates/<int:pk>/", owner_api.RateDeleteView.as_view(), name="finance-rate"),
    path("finance/reports/pnl/", owner_api.PnlView.as_view(), name="finance-report-pnl"),
    path(
        "finance/reports/cash-flow/",
        owner_api.CashFlowView.as_view(),
        name="finance-report-cash-flow",
    ),
    path(
        "finance/reports/balances/",
        owner_api.BalancesView.as_view(),
        name="finance-report-balances",
    ),
    path(
        "finance/reports/debts-aging/", owner_api.AgingView.as_view(), name="finance-report-aging"
    ),
    path(
        "finance/reports/category-trend/",
        owner_api.CategoryTrendView.as_view(),
        name="finance-report-category-trend",
    ),
    path("finance/settings/", owner_api.SettingsView.as_view(), name="finance-settings"),
    path("finance/settings/lock/", owner_api.LockView.as_view(), name="finance-settings-lock"),
    path("finance/tax-summary/", owner_api.TaxSummaryView.as_view(), name="finance-tax-summary"),
    *router.urls,
]
