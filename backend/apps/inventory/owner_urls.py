"""Owner endpoints of stock, mounted at `/api/v1/owner/companies/<int:company_id>/`."""

from django.urls import path

from apps.inventory import owner_api as v

P = "stock/"

urlpatterns = [
    path(f"{P}settings/", v.SettingsView.as_view(), name="stock-settings"),
    path(f"{P}summary/", v.SummaryView.as_view(), name="stock-summary"),
    path(f"{P}branches/", v.BranchesView.as_view(), name="stock-branches"),
    path(f"{P}products/", v.ProductsView.as_view(), name="stock-products"),
    path(f"{P}products/import/", v.ProductImportView.as_view(), name="stock-products-import"),
    path(f"{P}products/<int:pk>/", v.ProductView.as_view(), name="stock-product"),
    path(f"{P}products/<int:pk>/analogs/", v.ProductAnalogsView.as_view(), name="stock-analogs"),
    path(
        f"{P}products/<int:pk>/batches/",
        v.ProductBatchesView.as_view(),
        name="stock-product-batches",
    ),
    path(
        f"{P}products/<int:pk>/movements/",
        v.ProductMovementsView.as_view(),
        name="stock-product-movements",
    ),
    path(f"{P}products/<int:pk>/codes/", v.ProductCodesView.as_view(), name="stock-product-codes"),
    path(
        f"{P}products/<int:pk>/codes/<int:code_id>/",
        v.ProductCodeView.as_view(),
        name="stock-product-code",
    ),
    path(f"{P}products/<int:pk>/merge/", v.ProductMergeView.as_view(), name="stock-product-merge"),
    path(f"{P}categories/", v.CategoriesView.as_view(), name="stock-categories"),
    path(f"{P}categories/<int:pk>/", v.CategoryView.as_view(), name="stock-category"),
    path(f"{P}manufacturers/", v.ManufacturersView.as_view(), name="stock-manufacturers"),
    path(f"{P}manufacturers/<int:pk>/", v.ManufacturerView.as_view(), name="stock-manufacturer"),
    path(f"{P}suppliers/", v.SuppliersView.as_view(), name="stock-suppliers"),
    path(f"{P}suppliers/<int:pk>/", v.SupplierView.as_view(), name="stock-supplier"),
    path(f"{P}levels/", v.LevelsView.as_view(), name="stock-levels"),
    path(f"{P}levels/<int:pk>/", v.LevelView.as_view(), name="stock-level"),
    path(f"{P}batches/", v.BatchesView.as_view(), name="stock-batches"),
    path(f"{P}batches/opening/", v.OpeningView.as_view(), name="stock-opening"),
    path(f"{P}batches/<int:pk>/quarantine/", v.QuarantineView.as_view(), name="stock-quarantine"),
    path(f"{P}batches/<int:pk>/release/", v.ReleaseView.as_view(), name="stock-release"),
    path(f"{P}batches/<int:pk>/markdown/", v.MarkdownView.as_view(), name="stock-markdown"),
    path(f"{P}expiry/", v.ExpiryView.as_view(), name="stock-expiry"),
    path(f"{P}movements/", v.MovementsView.as_view(), name="stock-movements"),
    path(f"{P}receipts/", v.ReceiptsView.as_view(), name="stock-receipts"),
    path(f"{P}receipts/<int:pk>/", v.ReceiptView.as_view(), name="stock-receipt"),
    path(f"{P}receipts/<int:pk>/lines/", v.ReceiptLinesView.as_view(), name="stock-receipt-lines"),
    path(
        f"{P}receipts/<int:pk>/lines/import/",
        v.ReceiptLinesImportView.as_view(),
        name="stock-receipt-lines-import",
    ),
    path(
        f"{P}receipts/<int:pk>/lines/<int:line_id>/",
        v.ReceiptLineView.as_view(),
        name="stock-receipt-line",
    ),
    path(f"{P}receipts/<int:pk>/file/", v.ReceiptFileView.as_view(), name="stock-receipt-file"),
    path(
        f"{P}receipts/<int:pk>/submit/", v.ReceiptSubmitView.as_view(), name="stock-receipt-submit"
    ),
    path(f"{P}receipts/<int:pk>/post/", v.ReceiptPostView.as_view(), name="stock-receipt-post"),
    path(f"{P}receipts/<int:pk>/void/", v.ReceiptVoidView.as_view(), name="stock-receipt-void"),
    path(f"{P}transfers/", v.TransfersView.as_view(), name="stock-transfers"),
    path(f"{P}transfers/<int:pk>/", v.TransferView.as_view(), name="stock-transfer"),
    path(f"{P}transfers/<int:pk>/send/", v.TransferSendView.as_view(), name="stock-transfer-send"),
    path(
        f"{P}transfers/<int:pk>/receive/",
        v.TransferReceiveView.as_view(),
        name="stock-transfer-receive",
    ),
    path(
        f"{P}transfers/<int:pk>/resolve/",
        v.TransferResolveView.as_view(),
        name="stock-transfer-resolve",
    ),
    path(f"{P}transfers/<int:pk>/void/", v.TransferVoidView.as_view(), name="stock-transfer-void"),
    path(f"{P}write-offs/", v.WriteOffsView.as_view(), name="stock-writeoffs"),
    path(f"{P}write-offs/<int:pk>/", v.WriteOffView.as_view(), name="stock-writeoff"),
    path(
        f"{P}write-offs/<int:pk>/approve/",
        v.WriteOffApproveView.as_view(),
        name="stock-writeoff-approve",
    ),
    path(
        f"{P}write-offs/<int:pk>/destroyed/",
        v.WriteOffDestroyedView.as_view(),
        name="stock-writeoff-destroyed",
    ),
    path(f"{P}write-offs/<int:pk>/void/", v.WriteOffVoidView.as_view(), name="stock-writeoff-void"),
    path(
        f"{P}write-offs/<int:pk>/files/", v.WriteOffFilesView.as_view(), name="stock-writeoff-files"
    ),
    path(f"{P}write-offs/<int:pk>/act/", v.WriteOffActView.as_view(), name="stock-writeoff-act"),
    path(f"{P}counts/", v.CountsView.as_view(), name="stock-counts"),
    path(f"{P}counts/<int:pk>/", v.CountView.as_view(), name="stock-count"),
    path(f"{P}counts/<int:pk>/lines/", v.CountLinesView.as_view(), name="stock-count-lines"),
    path(f"{P}counts/<int:pk>/found/", v.CountFoundView.as_view(), name="stock-count-found"),
    path(f"{P}counts/<int:pk>/submit/", v.CountSubmitView.as_view(), name="stock-count-submit"),
    path(f"{P}counts/<int:pk>/apply/", v.CountApplyView.as_view(), name="stock-count-apply"),
    path(f"{P}recalls/", v.RecallsView.as_view(), name="stock-recalls"),
    path(f"{P}recalls/import/", v.RecallImportView.as_view(), name="stock-recalls-import"),
    path(f"{P}recalls/<int:pk>/", v.RecallView.as_view(), name="stock-recall"),
    path(f"{P}recalls/<int:pk>/close/", v.RecallCloseView.as_view(), name="stock-recall-close"),
    path(f"{P}pricing-rules/", v.PricingRulesView.as_view(), name="stock-pricing-rules"),
    path(f"{P}pricing-rules/<int:pk>/", v.PricingRuleView.as_view(), name="stock-pricing-rule"),
    path(f"{P}price-tags/", v.PriceTagsView.as_view(), name="stock-price-tags"),
    path(f"{P}defektura/", v.DefekturaView.as_view(), name="stock-defektura"),
    path(f"{P}defektura/<int:pk>/", v.DefekturaItemView.as_view(), name="stock-defektura-item"),
    path(f"{P}journals/rx/", v.RxJournalView.as_view(), name="stock-journal-rx"),
    path(f"{P}journals/rx/pdf/", v.RxJournalPdfView.as_view(), name="stock-journal-rx-pdf"),
    path(
        f"{P}journals/controlled/",
        v.ControlledJournalView.as_view(),
        name="stock-journal-controlled",
    ),
    path(
        f"{P}journals/controlled/pdf/",
        v.ControlledPdfView.as_view(),
        name="stock-journal-controlled-pdf",
    ),
    path(
        f"{P}journals/controlled/close/",
        v.ControlledCloseView.as_view(),
        name="stock-journal-controlled-close",
    ),
    path(
        f"{P}journals/controlled/<int:pk>/reported/",
        v.ControlledReportedView.as_view(),
        name="stock-journal-controlled-reported",
    ),
]
