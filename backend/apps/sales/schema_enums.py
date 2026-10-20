"""drf-spectacular enum names of sales and cash, merged into `ENUM_NAME_OVERRIDES`.

Read by file path when the settings load: name choices with an import string, e.g.
`{"SalesThingStatusEnum": "apps.sales.models.Thing.Status"}`. Names start with the
app label in PascalCase and must be unique (duplicates stop the settings).
"""

ENUM_NAME_OVERRIDES = {
    "SalesModeEnum": "apps.sales.models.SalesSettings.Mode",
    "SalesPaymentMethodKindEnum": "apps.sales.models.PaymentMethod.Kind",
    "SalesCashShiftStatusEnum": "apps.sales.models.CashShift.Status",
    "SalesCashShiftSourceEnum": "apps.sales.models.CashShift.Source",
    "SalesSaleKindEnum": "apps.sales.models.Sale.Kind",
    "SalesSaleSourceEnum": "apps.sales.models.Sale.Source",
    "SalesCashMovementKindEnum": "apps.sales.models.CashMovement.Kind",
}
