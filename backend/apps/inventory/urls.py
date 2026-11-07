"""Employee endpoints of stock, mounted at `/api/v1/companies/<int:company_id>/`."""

from django.urls import path

from apps.inventory import api

urlpatterns = [
    path("stock/settings/", api.SettingsView.as_view(), name="stock-app-settings"),
    path("stock/lookup/", api.LookupView.as_view(), name="stock-app-lookup"),
    path("stock/products/<int:pk>/", api.ProductView.as_view(), name="stock-app-product"),
    path("stock/receipts/", api.ReceiptsView.as_view(), name="stock-app-receipts"),
    path(
        "stock/receipts/<int:pk>/lines/",
        api.ReceiptLinesView.as_view(),
        name="stock-app-receipt-lines",
    ),
    path(
        "stock/receipts/<int:pk>/lines/<int:line_id>/",
        api.ReceiptLineView.as_view(),
        name="stock-app-receipt-line",
    ),
    path(
        "stock/receipts/<int:pk>/submit/",
        api.ReceiptSubmitView.as_view(),
        name="stock-app-receipt-submit",
    ),
    path("stock/counts/<int:pk>/lines/", api.CountLinesView.as_view(), name="stock-app-count"),
    path("stock/expiry/", api.ExpiryView.as_view(), name="stock-app-expiry"),
    path(
        "stock/batches/<int:pk>/expiry-action/",
        api.ExpiryActionView.as_view(),
        name="stock-app-expiry-action",
    ),
    path("stock/transfers/incoming/", api.IncomingView.as_view(), name="stock-app-incoming"),
    path("stock/transfers/<int:pk>/receive/", api.ReceiveView.as_view(), name="stock-app-receive"),
    path("stock/defektura/", api.DefekturaView.as_view(), name="stock-app-defektura"),
    path("stock/rx/", api.RxView.as_view(), name="stock-app-rx"),
]
