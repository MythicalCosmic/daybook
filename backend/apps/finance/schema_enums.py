"""drf-spectacular enum names of the finance ledger, merged into `ENUM_NAME_OVERRIDES`.

Read by file path when the settings load: name choices with an import string, e.g.
`{"FinanceThingStatusEnum": "apps.finance.models.Thing.Status"}`. Names start with the
app label in PascalCase and must be unique (duplicates stop the settings).
"""

ENUM_NAME_OVERRIDES = {
    "FinanceAccountKindEnum": "apps.finance.models.MoneyAccount.Kind",
    "FinanceCategoryKindEnum": "apps.finance.models.Category.Kind",
    "FinanceCounterpartyKindEnum": "apps.finance.models.Counterparty.Kind",
    "FinanceRateSourceEnum": "apps.finance.models.RateSource",
    "FinanceReimburseViaEnum": "apps.finance.models.FinanceSettings.ReimburseVia",
    "FinanceTransactionKindEnum": "apps.finance.models.Transaction.Kind",
    "FinanceTransactionStatusEnum": "apps.finance.models.Transaction.Status",
    "FinanceTransferStatusEnum": "apps.finance.models.Transfer.Status",
    "FinanceDebtDirectionEnum": "apps.finance.models.Debt.Direction",
    "FinanceDebtKindEnum": "apps.finance.models.Debt.Kind",
    "FinanceDebtStatusEnum": "apps.finance.models.Debt.Status",
}
