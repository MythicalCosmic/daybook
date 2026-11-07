"""drf-spectacular enum names of stock, merged into `ENUM_NAME_OVERRIDES`.

Read by file path when the settings load: import strings only. Names start with the app label
in PascalCase and must be unique (duplicates stop the settings).
"""

ENUM_NAME_OVERRIDES = {
    "InventoryProductKindEnum": "apps.inventory.models.Product.Kind",
    "InventoryDosageFormEnum": "apps.inventory.models.Product.DosageForm",
    "InventoryControlClassEnum": "apps.inventory.models.Product.ControlClass",
    "InventoryStorageEnum": "apps.inventory.models.Product.Storage",
    "InventoryCodeKindEnum": "apps.inventory.models.ProductCode.Kind",
    "InventoryOrderChannelEnum": "apps.inventory.models.SupplierProfile.Channel",
    "InventoryBatchStatusEnum": "apps.inventory.models.StockBatch.Status",
    "InventoryMovementKindEnum": "apps.inventory.models.StockMovement.Kind",
    "InventoryReceiptStatusEnum": "apps.inventory.models.GoodsReceipt.Status",
    "InventoryReceiptWarningEnum": "apps.inventory.models.GoodsReceiptLine.Warning",
    "InventoryTransferStatusEnum": "apps.inventory.models.StockTransfer.Status",
    "InventoryTransferResolutionEnum": "apps.inventory.models.StockTransfer.Resolution",
    "InventoryWriteOffReasonEnum": "apps.inventory.models.WriteOff.Reason",
    "InventoryWriteOffStatusEnum": "apps.inventory.models.WriteOff.Status",
    "InventoryDestructionMethodEnum": "apps.inventory.models.WriteOff.Method",
    "InventoryWriteOffFileKindEnum": "apps.inventory.models.WriteOffFile.Kind",
    "InventoryCountKindEnum": "apps.inventory.models.StockCount.Kind",
    "InventoryCountStatusEnum": "apps.inventory.models.StockCount.Status",
    "InventoryRecallStatusEnum": "apps.inventory.models.RecallNotice.Status",
    "InventoryRequestSourceEnum": "apps.inventory.models.MissingRequest.Source",
    "InventoryRequestStatusEnum": "apps.inventory.models.MissingRequest.Status",
    "InventoryRxKindEnum": "apps.inventory.models.RxRecord.RxKind",
    "InventoryRxStatusEnum": "apps.inventory.models.RxRecord.Status",
    "InventoryImportActionEnum": "apps.inventory.serializers.IMPORT_ACTIONS",
    "InventoryLineImportActionEnum": "apps.inventory.serializers.LINE_IMPORT_ACTIONS",
}
