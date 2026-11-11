"""Shapes of the loans and tax calendar endpoints (v12, `loans_api`, `taxes_api`). Money is a
string in the loan's currency (or the base currency where it says so)."""

from rest_framework import serializers

from apps.core.money import Currency, MoneySerializerField
from apps.finance import loan_math
from apps.finance.models import Debt, Loan, TaxMark
from apps.finance.owner_serializers import (
    FinanceAccountRefSerializer,
    FinanceRefSerializer,
    TransactionSerializer,
    money_out,
)

# Loans ------------------------------------------------------------------------------------


class LoanLineSerializer(serializers.Serializer):
    """One payment of the schedule and what is paid of it."""

    id = serializers.IntegerField()
    position = serializers.IntegerField()
    due_on = serializers.DateField()
    principal = money_out()
    interest = money_out()
    payment = money_out()
    principal_paid = money_out()
    interest_paid = money_out()
    rest = money_out(help_text="What is still to pay of it, principal and interest.")
    balance = money_out(help_text="The principal still owed after it.")
    status = serializers.ChoiceField(["paid", "partial", "due", "overdue"])
    early = serializers.BooleanField()

    class Meta:
        ref_name = "FinanceLoanLine"


class LoanSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    debt_id = serializers.IntegerField()
    direction = serializers.ChoiceField(Debt.Direction.choices)
    direction_label = serializers.CharField()
    counterparty = FinanceRefSerializer()
    branch = FinanceRefSerializer(allow_null=True)
    account = FinanceAccountRefSerializer(allow_null=True)
    description = serializers.CharField()
    currency = serializers.CharField()
    status = serializers.ChoiceField(Debt.Status.choices)
    is_opening = serializers.BooleanField()
    issued_on = serializers.DateField()
    ends_on = serializers.DateField(allow_null=True)
    annual_rate = serializers.DecimalField(max_digits=6, decimal_places=3, coerce_to_string=True)
    method = serializers.ChoiceField(Loan.Method.choices)
    method_label = serializers.CharField()
    basis = serializers.ChoiceField(Loan.Basis.choices)
    term_months = serializers.IntegerField()
    first_due_on = serializers.DateField()
    grace_months = serializers.IntegerField()
    fee = money_out()
    amount = money_out(help_text="The principal.")
    owed = money_out(help_text="The principal still owed.")
    paid_principal = money_out()
    interest_paid = money_out()
    interest_left = money_out()
    next = LoanLineSerializer(allow_null=True)
    overdue_count = serializers.IntegerField()
    overdue_amount = money_out()
    payments_left = serializers.IntegerField()
    payments = serializers.IntegerField()

    class Meta:
        ref_name = "FinanceLoan"


class LoanDetailSerializer(serializers.Serializer):
    loan = LoanSerializer()
    schedule = LoanLineSerializer(many=True)
    payments = TransactionSerializer(many=True)
    can_pay = serializers.BooleanField()
    can_edit_schedule = serializers.BooleanField(help_text="Nothing paid yet: terms can change.")
    can_undo = serializers.BooleanField()

    class Meta:
        ref_name = "FinanceLoanDetail"


class LoanListSerializer(serializers.Serializer):
    currency = serializers.CharField(help_text="The base currency of the totals.")
    owed = money_out(help_text="What the company owes on its loans, in the base currency.")
    owed_to_us = money_out(help_text="What is owed to the company on loans it gave.")
    due_30 = money_out(help_text="Loan payments due in the next 30 days, in the base currency.")
    overdue = money_out(help_text="Loan payments overdue, in the base currency.")
    loans = LoanSerializer(many=True)

    class Meta:
        ref_name = "FinanceLoanList"


class ScheduleRowSerializer(serializers.Serializer):
    due_on = serializers.DateField()
    principal = MoneySerializerField(positive=False, min_value=0)
    interest = MoneySerializerField(positive=False, min_value=0, required=False, default=0)

    class Meta:
        ref_name = "FinanceLoanScheduleRow"


class LoanTermsSerializer(serializers.Serializer):
    """The terms a schedule is made from (or the typed rows of the bank's own schedule)."""

    amount = MoneySerializerField()
    currency = serializers.ChoiceField(Currency.choices, default=Currency.UZS)
    issued_on = serializers.DateField()
    annual_rate = serializers.DecimalField(
        max_digits=6, decimal_places=3, min_value=0, max_value=100, default=0
    )
    method = serializers.ChoiceField(Loan.Method.choices, default=Loan.Method.ANNUITY)
    basis = serializers.ChoiceField(Loan.Basis.choices, default=Loan.Basis.MONTHLY)
    term_months = serializers.IntegerField(min_value=1, max_value=loan_math.MAX_MONTHS, default=12)
    first_due_on = serializers.DateField(required=False, allow_null=True)
    grace_months = serializers.IntegerField(min_value=0, max_value=120, default=0)
    fee = MoneySerializerField(positive=False, min_value=0, required=False, default=0)
    rows = ScheduleRowSerializer(many=True, required=False, max_length=loan_math.MAX_MONTHS)

    class Meta:
        ref_name = "FinanceLoanTerms"


class LoanCreateSerializer(LoanTermsSerializer):
    direction = serializers.ChoiceField(Debt.Direction.choices, default=Debt.Direction.PAYABLE)
    counterparty = serializers.IntegerField()
    account = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Where the money arrived (or left from). Empty: a loan from before the books.",
    )
    branch = serializers.IntegerField(required=False, allow_null=True)
    responsible = serializers.IntegerField(required=False, allow_null=True)
    description = serializers.CharField(max_length=300, required=False, allow_blank=True)

    class Meta:
        ref_name = "FinanceLoanCreate"


class PreviewRowSerializer(serializers.Serializer):
    position = serializers.IntegerField()
    due_on = serializers.DateField()
    principal = money_out()
    interest = money_out()
    payment = money_out()
    balance = money_out()

    class Meta:
        ref_name = "FinanceLoanPreviewRow"


class PreviewTotalsSerializer(serializers.Serializer):
    principal = money_out()
    interest = money_out()
    payments = money_out()
    fee = money_out()
    cost = money_out(help_text="Interest and the fee: what the loan costs.")

    class Meta:
        ref_name = "FinanceLoanPreviewTotals"


class LoanPreviewSerializer(serializers.Serializer):
    rows = PreviewRowSerializer(many=True)
    totals = PreviewTotalsSerializer()
    first_payment = money_out()
    effective_rate = serializers.DecimalField(
        max_digits=8,
        decimal_places=2,
        coerce_to_string=True,
        help_text="Interest and fee per year of the loan's average life, in per cent.",
    )

    class Meta:
        ref_name = "FinanceLoanPreview"


class ScheduleUpdateSerializer(serializers.Serializer):
    annual_rate = serializers.DecimalField(
        max_digits=6, decimal_places=3, min_value=0, max_value=100, required=False
    )
    method = serializers.ChoiceField(Loan.Method.choices, required=False)
    basis = serializers.ChoiceField(Loan.Basis.choices, required=False)
    term_months = serializers.IntegerField(
        min_value=1, max_value=loan_math.MAX_MONTHS, required=False
    )
    first_due_on = serializers.DateField(required=False)
    grace_months = serializers.IntegerField(min_value=0, max_value=120, required=False)
    rows = ScheduleRowSerializer(many=True, required=False, max_length=loan_math.MAX_MONTHS)

    class Meta:
        ref_name = "FinanceLoanScheduleUpdate"


class LoanPaySerializer(serializers.Serializer):
    installment = serializers.IntegerField()
    account = serializers.IntegerField()
    paid_on = serializers.DateField()
    principal = MoneySerializerField(positive=False, min_value=0, required=False, allow_null=True)
    interest = MoneySerializerField(positive=False, min_value=0, required=False, allow_null=True)

    class Meta:
        ref_name = "FinanceLoanPay"


class LoanEarlySerializer(serializers.Serializer):
    account = serializers.IntegerField()
    paid_on = serializers.DateField()
    amount = MoneySerializerField()
    interest = MoneySerializerField(positive=False, min_value=0, required=False, default=0)
    mode = serializers.ChoiceField(
        [loan_math.REDUCE_PAYMENT, loan_math.REDUCE_TERM], default=loan_math.REDUCE_PAYMENT
    )

    class Meta:
        ref_name = "FinanceLoanEarly"


class LoanUndoSerializer(serializers.Serializer):
    transaction = serializers.IntegerField()
    reason = serializers.CharField(max_length=300)

    class Meta:
        ref_name = "FinanceLoanUndo"


# The tax calendar -------------------------------------------------------------------------


class TaxDeadlineSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="<rule>:<period start>")
    rule = serializers.CharField()
    tax = serializers.CharField()
    tax_name = serializers.CharField()
    name = serializers.CharField()
    period = serializers.ChoiceField(["month", "quarter", "year"])
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    period_label = serializers.CharField()
    due_on = serializers.DateField()
    action = serializers.ChoiceField(["file_pay", "file", "pay"])
    action_label = serializers.CharField()
    estimate = money_out(allow_null=True)
    basis = serializers.CharField(help_text="How the estimate is worked out.")
    booked = serializers.BooleanField(help_text="The amount is a booked tax debt.")
    currency = serializers.CharField()
    status = serializers.ChoiceField(["due", "overdue", "done"])
    done_on = serializers.DateField(allow_null=True)
    mark_id = serializers.IntegerField(allow_null=True)
    paid = money_out(allow_null=True)
    transaction_id = serializers.IntegerField(allow_null=True)
    debt_id = serializers.IntegerField(allow_null=True)
    rule_id = serializers.IntegerField(allow_null=True, help_text="The recurring tax bill.")
    rate = serializers.CharField(allow_null=True)
    law = serializers.CharField()
    url = serializers.CharField()
    confidence = serializers.ChoiceField(["H", "M"])
    note = serializers.CharField()

    class Meta:
        ref_name = "FinanceTaxDeadline"


class TaxProfileSerializer(serializers.Serializer):
    payroll = serializers.BooleanField()
    property = serializers.BooleanField()
    land = serializers.BooleanField()
    big_income = serializers.BooleanField()

    class Meta:
        ref_name = "FinanceTaxProfile"


class TaxSourceSerializer(serializers.Serializer):
    label = serializers.CharField()
    url = serializers.CharField()

    class Meta:
        ref_name = "FinanceTaxSource"


class TaxCalendarSerializer(serializers.Serializer):
    today = serializers.DateField()
    _from = serializers.DateField()
    to = serializers.DateField()
    currency = serializers.CharField()
    regime = serializers.CharField()
    regime_label = serializers.CharField()
    profile = TaxProfileSerializer()
    remind_days = serializers.IntegerField()
    warnings = serializers.ListField(child=serializers.CharField())
    deadlines = TaxDeadlineSerializer(many=True)
    checked_on = serializers.DateField()
    sources = TaxSourceSerializer(many=True)
    disclaimer = serializers.CharField()

    class Meta:
        ref_name = "FinanceTaxCalendar"

    def get_fields(self):
        fields = super().get_fields()
        fields["from"] = fields.pop("_from")
        return fields


class TaxMarkSerializer(serializers.Serializer):
    rule = serializers.CharField()
    period_start = serializers.DateField()
    done_on = serializers.DateField()
    transaction = serializers.IntegerField(required=False, allow_null=True)
    account = serializers.IntegerField(required=False, allow_null=True)
    amount = MoneySerializerField(required=False, allow_null=True)
    note = serializers.CharField(max_length=300, required=False, allow_blank=True)

    class Meta:
        ref_name = "FinanceTaxMarkWrite"


class TaxMarkOutSerializer(serializers.ModelSerializer):
    amount = money_out(allow_null=True)

    class Meta:
        ref_name = "FinanceTaxMark"
        model = TaxMark
        fields = (
            "id",
            "tax",
            "kind",
            "period_start",
            "period_end",
            "due_on",
            "done_on",
            "transaction",
            "amount",
            "note",
        )


class TaxCandidateSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    occurred_on = serializers.DateField()
    amount = money_out(help_text="Money out, in the base currency (positive).")
    description = serializers.CharField()
    account = serializers.CharField()
    category = serializers.CharField(allow_null=True)

    class Meta:
        ref_name = "FinanceTaxCandidate"


class ComparePartSerializer(serializers.Serializer):
    name = serializers.CharField()
    amount = money_out()
    formula = serializers.CharField()

    class Meta:
        ref_name = "FinanceTaxComparePart"


class CompareOptionSerializer(serializers.Serializer):
    regime = serializers.CharField()
    label = serializers.CharField()
    total = money_out()
    parts = ComparePartSerializer(many=True)
    available = serializers.BooleanField()
    why_not = serializers.CharField()
    law = serializers.CharField()
    current = serializers.BooleanField()
    cheapest = serializers.BooleanField()

    class Meta:
        ref_name = "FinanceTaxCompareOption"


class TaxCompareSerializer(serializers.Serializer):
    _from = serializers.DateField()
    to = serializers.DateField()
    days = serializers.IntegerField()
    currency = serializers.CharField()
    income = money_out()
    goods = money_out()
    expense = money_out()
    profit = money_out()
    enough = serializers.BooleanField(help_text="The books cover the whole twelve months.")
    threshold = money_out()
    threshold_law = serializers.CharField()
    over_threshold = serializers.BooleanField()
    regime = serializers.CharField()
    options = CompareOptionSerializer(many=True)
    assumptions = serializers.ListField(child=serializers.CharField())
    disclaimer = serializers.CharField()

    class Meta:
        ref_name = "FinanceTaxCompare"

    def get_fields(self):
        fields = super().get_fields()
        fields["from"] = fields.pop("_from")
        return fields
