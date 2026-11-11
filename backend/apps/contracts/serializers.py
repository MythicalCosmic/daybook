"""Shapes of the business contract endpoints. Money goes out as strings, dates as company-local
`YYYY-MM-DD`; every component name starts with "Contracts" (see the end of the file)."""

from datetime import date
from pathlib import PurePosixPath

from rest_framework import serializers

from apps.contracts import queries, services
from apps.contracts.models import BusinessContract, ContractFile
from apps.core.files import signed_url
from apps.core.money import Currency, MoneySerializerField

Status = BusinessContract.Status
WRITABLE_STATUSES = [
    (value, label) for value, label in Status.choices if value in ("draft", "active")
]
ATTENTION = [("ending", "ending"), ("notice", "notice")]
DATE_KEYS = [
    ("signed", "signed"),
    ("starts", "starts"),
    ("renewed", "renewed"),
    ("notice", "notice"),
    ("renews", "renews"),
    ("ends", "ends"),
    ("terminated", "terminated"),
]


class Ref(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


def ref(item):
    if item is None:
        return None
    return {"id": item.pk, "name": str(getattr(item, "name", None) or item)}


# Input ------------------------------------------------------------------------------------------


class ContractWriteSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=BusinessContract.Kind.choices, required=False)
    title = serializers.CharField(max_length=200, required=False)
    branch = serializers.IntegerField(required=False, allow_null=True)
    counterparty = serializers.IntegerField(required=False, allow_null=True)
    counterparty_name = serializers.CharField(
        max_length=200,
        required=False,
        allow_blank=True,
        help_text="A party by name: the existing one called so, or a new one.",
    )
    number = serializers.CharField(max_length=64, required=False, allow_blank=True)
    signed_on = serializers.DateField(required=False, allow_null=True)
    starts_on = serializers.DateField(required=False, allow_null=True)
    ends_on = serializers.DateField(required=False, allow_null=True)
    auto_renews = serializers.BooleanField(required=False)
    renewal_months = serializers.IntegerField(required=False, min_value=1, max_value=120)
    notice_days = serializers.IntegerField(required=False, min_value=0, max_value=365)
    amount = MoneySerializerField(positive=False, required=False, allow_null=True, min_value=0)
    period = serializers.ChoiceField(choices=BusinessContract.Period.choices, required=False)
    currency = serializers.ChoiceField(choices=Currency.choices, required=False)
    payment_day = serializers.IntegerField(
        required=False, allow_null=True, min_value=1, max_value=31
    )
    notes = serializers.CharField(required=False, allow_blank=True, max_length=4000)
    status = serializers.ChoiceField(choices=WRITABLE_STATUSES, required=False)
    responsible = serializers.IntegerField(required=False, allow_null=True)
    in_forecast = serializers.BooleanField(required=False)
    category = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="The expense category of a new recurring payment (by kind when empty).",
    )
    account = serializers.IntegerField(
        required=False, allow_null=True, help_text="The account the recurring payment is paid from."
    )
    link_rule = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Take over this existing recurring payment instead of making one.",
    )


class RenewSerializer(serializers.Serializer):
    ends_on = serializers.DateField()


class TerminateSerializer(serializers.Serializer):
    on = serializers.DateField()
    reason = serializers.CharField(required=False, allow_blank=True, max_length=300)


class FileUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    kind = serializers.ChoiceField(choices=ContractFile.Kind.choices, required=False)
    label = serializers.CharField(required=False, allow_blank=True, max_length=120)


class SettingsSerializer(serializers.Serializer):
    remind_days = serializers.IntegerField(min_value=1, max_value=365, required=False)
    notice_remind_days = serializers.IntegerField(min_value=1, max_value=180, required=False)


# Output -----------------------------------------------------------------------------------------


class RowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=BusinessContract.Kind.choices)
    title = serializers.CharField()
    number = serializers.CharField()
    branch = Ref(allow_null=True)
    counterparty = Ref(allow_null=True)
    responsible = Ref(allow_null=True)
    status = serializers.ChoiceField(choices=Status.choices)
    starts_on = serializers.DateField(allow_null=True)
    term_starts_on = serializers.DateField(
        allow_null=True, help_text="The current term's first day: the last renewal, else the start."
    )
    ends_on = serializers.DateField(allow_null=True)
    auto_renews = serializers.BooleanField()
    notice_deadline = serializers.DateField(allow_null=True)
    key_day = serializers.DateField(
        allow_null=True, help_text="The next date that matters: the notice deadline, else the end."
    )
    days_left = serializers.IntegerField(allow_null=True, help_text="Days to `key_day`.")
    attention = serializers.ChoiceField(
        choices=ATTENTION,
        allow_null=True,
        help_text="ending: it ends within the warning days; notice: a renewal decision is due.",
    )
    amount = MoneySerializerField(positive=False, allow_null=True)
    period = serializers.ChoiceField(choices=BusinessContract.Period.choices)
    currency = serializers.CharField()
    per_month = MoneySerializerField(positive=False, allow_null=True)
    in_forecast = serializers.BooleanField()
    has_rule = serializers.BooleanField()
    files = serializers.IntegerField(help_text="How many files it has.")


class FileSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=ContractFile.Kind.choices)
    label = serializers.CharField()
    size = serializers.IntegerField()
    is_pdf = serializers.BooleanField()
    url = serializers.CharField(help_text="A signed link, valid for ten minutes.")
    uploaded_by = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField()


class DateSerializer(serializers.Serializer):
    key = serializers.ChoiceField(choices=DATE_KEYS)
    day = serializers.DateField()
    past = serializers.BooleanField()


class RuleSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    is_active = serializers.BooleanField()
    category = Ref()
    account = Ref(allow_null=True)
    amount = MoneySerializerField(positive=False)
    currency = serializers.CharField()
    frequency = serializers.CharField()
    day = serializers.IntegerField()
    next_due_on = serializers.DateField(allow_null=True)
    ends_on = serializers.DateField(allow_null=True)


class PaymentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    occurred_on = serializers.DateField()
    amount = MoneySerializerField(positive=False)
    currency = serializers.CharField()
    base_amount = MoneySerializerField(positive=False)
    description = serializers.CharField()
    account = serializers.CharField(allow_null=True)
    by_rule = serializers.BooleanField(help_text="Paid as a bill of its recurring payment.")


class NextBillSerializer(serializers.Serializer):
    due_on = serializers.DateField(allow_null=True)
    amount = MoneySerializerField(positive=False)
    currency = serializers.CharField()


class PaymentsSerializer(serializers.Serializer):
    items = PaymentSerializer(many=True)
    count = serializers.IntegerField()
    total = MoneySerializerField(positive=False)
    this_year = MoneySerializerField(positive=False)
    currency = serializers.CharField()
    last_paid_on = serializers.DateField(allow_null=True)
    next = NextBillSerializer(allow_null=True)


class CanSerializer(serializers.Serializer):
    manage = serializers.BooleanField()


class DetailSerializer(RowSerializer):
    signed_on = serializers.DateField(allow_null=True)
    renewal_months = serializers.IntegerField()
    notice_days = serializers.IntegerField()
    payment_day = serializers.IntegerField(allow_null=True)
    notes = serializers.CharField()
    terminated_on = serializers.DateField(allow_null=True)
    termination_reason = serializers.CharField()
    last_renewed_on = serializers.DateField(allow_null=True)
    renewal_confirmed = serializers.BooleanField(
        help_text="The owner confirmed this term's auto-renewal."
    )
    file_list = FileSerializer(many=True)
    dates = DateSerializer(many=True)
    rule = RuleSerializer(allow_null=True)
    payments = PaymentsSerializer(
        allow_null=True, help_text="Null while the Finance module is off."
    )
    created_at = serializers.DateTimeField()
    can = CanSerializer()


class SummarySerializer(serializers.Serializer):
    today = serializers.DateField()
    counts = serializers.DictField(child=serializers.IntegerField(), help_text="By status.")
    total = serializers.IntegerField()
    in_force = serializers.IntegerField()
    ending_soon = serializers.IntegerField()
    notice_due = serializers.IntegerField()
    monthly_cost = MoneySerializerField(positive=False)
    currency = serializers.CharField()
    unpriced = serializers.IntegerField(help_text="In force in a currency without a rate today.")
    remind_days = serializers.IntegerField()
    notice_remind_days = serializers.IntegerField()


class OptionCategorySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    system_code = serializers.CharField()


class OptionAccountSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    currency = serializers.CharField()


class OptionRuleSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    amount = MoneySerializerField(positive=False)
    currency = serializers.CharField()
    frequency = serializers.CharField()
    counterparty = serializers.IntegerField(allow_null=True)
    branch = serializers.IntegerField(allow_null=True)


class OptionPartySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    kind = serializers.CharField()


class OptionsSerializer(serializers.Serializer):
    finance = serializers.BooleanField(help_text="The Finance module is on.")
    base_currency = serializers.CharField()
    categories = OptionCategorySerializer(many=True)
    accounts = OptionAccountSerializer(many=True)
    rules = OptionRuleSerializer(many=True, help_text="Recurring payments no contract has.")
    parties = OptionPartySerializer(many=True)


# Building the output ----------------------------------------------------------------------------


def _attention(contract: BusinessContract, today: date, settings) -> str | None:
    if services.ends_soon(contract, today, settings.remind_days):
        return "ending"
    if services.notice_due(contract, today, settings.notice_remind_days):
        return "notice"
    return None


def term_start(contract: BusinessContract) -> date | None:
    """The current term's first day: the last renewal (inside the contract's dates), else its
    start. A lease renewed every year shows this year's term, not the years since it began."""
    renewed = contract.last_renewed_on
    if renewed is None or contract.starts_on is None or renewed < contract.starts_on:
        return contract.starts_on
    if contract.ends_on is not None and renewed > contract.ends_on:
        return contract.starts_on
    return renewed


# The signed contract first, then its annexes, then the rest.
FILE_ORDER = {ContractFile.Kind.SIGNED: 0, ContractFile.Kind.ANNEX: 1, ContractFile.Kind.OTHER: 2}


def row_of(contract: BusinessContract, *, today: date, settings, files: int | None = None) -> dict:
    key_day = queries.key_day(contract) if contract.status in BusinessContract.IN_FORCE else None
    if key_day is None:
        key_day = contract.ends_on
    return {
        "id": contract.pk,
        "kind": contract.kind,
        "title": contract.title,
        "number": contract.number,
        "branch": ref(contract.branch),
        "counterparty": ref(contract.counterparty),
        "responsible": ref(contract.responsible),
        "status": contract.status,
        "starts_on": contract.starts_on,
        "term_starts_on": term_start(contract),
        "ends_on": contract.ends_on,
        "auto_renews": contract.auto_renews,
        "notice_deadline": contract.notice_deadline,
        "key_day": key_day,
        "days_left": (key_day - today).days if key_day else None,
        "attention": _attention(contract, today, settings),
        "amount": contract.amount,
        "period": contract.period,
        "currency": contract.currency,
        "per_month": queries.per_month(contract),
        "in_forecast": contract.in_forecast,
        "has_rule": contract.rule_id is not None,
        "files": files if files is not None else contract.files.count(),
    }


def download_name(row: ContractFile) -> str:
    """ "Chilonzor dorixonasi ijarasi - Signed contract.pdf": what the browser saves it as."""
    suffix = PurePosixPath(row.file.name).suffix.lower()
    name = f"{row.contract.title} - {row.label or row.get_kind_display()}"
    clean = "".join(" " if char in '/\\:*?"<>|' or ord(char) < 32 else char for char in name)
    return f"{' '.join(clean.split())[:150]}{suffix}"


def file_of(row: ContractFile, *, user) -> dict:
    return {
        "id": row.pk,
        "kind": row.kind,
        "label": row.label,
        "size": row.size,
        "is_pdf": row.file.name.lower().endswith(".pdf"),
        "url": signed_url(
            row.file,
            user=user,
            company_id=row.company_id,
            check=f"contracts.file:{row.pk}",
            filename=download_name(row),
        ),
        "uploaded_by": row.uploaded_by.get_full_name() if row.uploaded_by_id else None,
        "created_at": row.created_at,
    }


def rule_of(rule) -> dict | None:
    if rule is None:
        return None
    return {
        "id": rule.pk,
        "name": rule.name,
        "is_active": rule.is_active,
        "category": ref(rule.category),
        "account": ref(rule.account),
        "amount": rule.amount,
        "currency": rule.currency,
        "frequency": rule.frequency,
        "day": rule.day,
        "next_due_on": rule.next_due_on if rule.is_active else None,
        "ends_on": rule.ends_on,
    }


def detail_of(
    contract: BusinessContract, *, user, today: date, settings, branch_ids, can_manage: bool
) -> dict:
    files = sorted(
        contract.files.select_related("uploaded_by"),
        key=lambda row: (FILE_ORDER.get(row.kind, 9), row.created_at, row.pk),
    )
    data = row_of(contract, today=today, settings=settings, files=len(files))
    payments = None
    if contract.company.has_feature("finance"):
        payments = queries.payments(contract, branch_ids=branch_ids, today=today)
    data.update(
        {
            "signed_on": contract.signed_on,
            "renewal_months": contract.renewal_months,
            "notice_days": contract.notice_days,
            "payment_day": contract.payment_day,
            "notes": contract.notes,
            "terminated_on": contract.terminated_on,
            "termination_reason": contract.termination_reason,
            "last_renewed_on": contract.last_renewed_on,
            "renewal_confirmed": contract.auto_renews
            and contract.renewal_confirmed_for is not None
            and contract.renewal_confirmed_for == contract.ends_on,
            "file_list": [file_of(row, user=user) for row in files],
            "dates": queries.dates(contract, today),
            "rule": rule_of(contract.rule),
            "payments": payments,
            "created_at": contract.created_at,
            "can": {"manage": can_manage},
        }
    )
    return data


# Every shape here gets a "Contracts…" component name of its own, so none collides with another
# app's ("Ref", "Settings") and subclasses never inherit their parent's name.
for _name, _shape in list(globals().items()):
    if (
        isinstance(_shape, type)
        and issubclass(_shape, serializers.Serializer)
        and _shape.__module__ == __name__
        and "Meta" not in _shape.__dict__
    ):
        _shape.Meta = type(
            "Meta",
            (),
            {"ref_name": "Contracts" + _name.removesuffix("Serializer").removeprefix("Contract")},
        )
