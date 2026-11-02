"""drf-spectacular enum names of payroll, merged into `ENUM_NAME_OVERRIDES`.

Read by file path when the settings load: name choices with an import string, e.g.
`{"PayrollThingStatusEnum": "apps.payroll.models.Thing.Status"}`. Names start with the
app label in PascalCase and must be unique (duplicates stop the settings).
"""

ENUM_NAME_OVERRIDES = {
    "PayrollPayTypeEnum": "apps.payroll.models.PayType",
    "PayrollPayoutMethodEnum": "apps.payroll.models.PayoutMethod",
    "PayrollProrationEnum": "apps.payroll.models.Compensation.Proration",
    "PayrollAdjustmentKindEnum": "apps.payroll.models.Adjustment.Kind",
    "PayrollAdjustmentSourceEnum": "apps.payroll.models.Adjustment.Source",
    "PayrollAdjustmentStatusEnum": "apps.payroll.models.Adjustment.Status",
    "PayrollAdvanceStatusEnum": "apps.payroll.models.Advance.Status",
    "PayrollRuleKindEnum": "apps.payroll.models.AdjustmentRule.Kind",
    "PayrollRuleMetricEnum": "apps.payroll.models.AdjustmentRule.Metric",
    "PayrollRuleModeEnum": "apps.payroll.models.AdjustmentRule.Mode",
    "PayrollRuleOpEnum": "apps.payroll.models.AdjustmentRule.Op",
    "PayrollRuleAmountTypeEnum": "apps.payroll.models.AdjustmentRule.AmountType",
    "PayrollRuleEvaluateEnum": "apps.payroll.models.AdjustmentRule.Evaluate",
    "PayrollRunKindEnum": "apps.payroll.models.PayrollRun.Kind",
    "PayrollRunStatusEnum": "apps.payroll.models.PayrollRun.Status",
    "PayrollPayslipStatusEnum": "apps.payroll.models.Payslip.Status",
    "PayrollLineKindEnum": "apps.payroll.models.PayslipLine.Kind",
}
