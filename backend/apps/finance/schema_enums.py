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
    # Package I.
    "FinanceTaxRegimeEnum": "apps.finance.models.FinanceSettings.TaxRegime",
    "FinanceRecurringModeEnum": "apps.finance.models.RecurringRule.Mode",
    "FinanceRecurringFrequencyEnum": "apps.finance.models.RecurringRule.Frequency",
    "FinanceRecurringOnHolidayEnum": "apps.finance.models.RecurringRule.OnHoliday",
    "FinanceClaimPaidFromEnum": "apps.finance.models.Claim.PaidFrom",
    "FinanceClaimStatusEnum": "apps.finance.models.Claim.Status",
    # v12: reports for banks and investors.
    "FinanceStatementPeriodEnum": "apps.finance.models.StatementPack.Period",
    "FinanceStatementPurposeEnum": "apps.finance.models.StatementPack.Purpose",
    "FinanceStatementPackStatusEnum": "apps.finance.models.StatementPack.Status",
    # v12: loans and the tax calendar.
    "FinanceLoanMethodEnum": "apps.finance.models.Loan.Method",
    "FinanceLoanBasisEnum": "apps.finance.models.Loan.Basis",
    "FinanceLoanLineStatusEnum": "apps.finance.loans.LINE_STATUSES",
    "FinanceTaxDeadlineStatusEnum": "apps.finance.taxes.DEADLINE_STATUSES",
}
