"""Serializers of the statements endpoints (v12): the balance sheet, what the business is worth
and the statement packs. Money is a string, days are company-local YYYY-MM-DD."""

from decimal import Decimal

from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core import files
from apps.core.money import MoneySerializerField
from apps.finance import statement_pack
from apps.finance.models import StatementPack


def money(**kwargs):
    return MoneySerializerField(positive=False, read_only=True, **kwargs)


class StatementLineSerializer(serializers.Serializer):
    key = serializers.CharField()
    amount = money()
    count = serializers.IntegerField(required=False)
    cost = money(required=False)


class StatementSectionSerializer(serializers.Serializer):
    key = serializers.CharField()
    lines = StatementLineSerializer(many=True)
    total = money()


class StatementSideSerializer(serializers.Serializer):
    sections = StatementSectionSerializer(many=True)
    total = money()


class StatementEquitySerializer(serializers.Serializer):
    lines = StatementLineSerializer(many=True)
    total = money()


class StatementCheckSerializer(serializers.Serializer):
    assets = money()
    liabilities_and_equity = money()
    balanced = serializers.BooleanField()


class StatementAccountSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    kind = serializers.CharField()
    currency = serializers.CharField()
    branch_id = serializers.IntegerField(allow_null=True)
    balance = money()
    base = money(allow_null=True)


class StatementForeignSerializer(serializers.Serializer):
    currency = serializers.CharField()
    amount = money()
    base = money(allow_null=True)
    rate = serializers.DecimalField(max_digits=18, decimal_places=6, allow_null=True)
    rate_date = serializers.DateField()
    stale = serializers.BooleanField()


class StatementRateSerializer(serializers.Serializer):
    rate = serializers.DecimalField(max_digits=18, decimal_places=6, allow_null=True)
    stale = serializers.BooleanField()
    source = serializers.CharField()
    date = serializers.DateField()


class StatementReconciliationSerializer(serializers.Serializer):
    lines = StatementLineSerializer(many=True)
    retained = money()
    unexplained = money()


class StatementGapSerializer(serializers.Serializer):
    key = serializers.CharField()
    params = serializers.DictField()

    def to_representation(self, instance):
        params = {
            key: str(value) if isinstance(value, Decimal) else value
            for key, value in instance["params"].items()
        }
        params = {
            key: value.isoformat() if hasattr(value, "isoformat") else value
            for key, value in params.items()
        }
        return {"key": instance["key"], "params": params}


class BalanceSheetSerializer(serializers.Serializer):
    on = serializers.DateField()
    currency = serializers.CharField()
    whole_company = serializers.BooleanField()
    books_start = serializers.DateField(allow_null=True)
    assets = StatementSideSerializer()
    liabilities = StatementSideSerializer()
    equity = StatementEquitySerializer()
    check = StatementCheckSerializer()
    current_assets = money()
    current_liabilities = money()
    accounts = StatementAccountSerializer(many=True)
    foreign = StatementForeignSerializer(many=True)
    rate = StatementRateSerializer()
    complete = serializers.BooleanField()
    reconciliation = StatementReconciliationSerializer(allow_null=True)
    gaps = StatementGapSerializer(many=True)


class ValuationEarningsSerializer(serializers.Serializer):
    to = serializers.DateField()
    days = serializers.IntegerField()
    enough = serializers.BooleanField()
    profit = money()
    lines = StatementLineSerializer(many=True)
    earnings = money()
    yearly = money(allow_null=True)

    def get_fields(self):
        # "from" is a Python keyword: added here instead of declared.
        return {"from": serializers.DateField(), **super().get_fields()}


class ValuationMethodSerializer(serializers.Serializer):
    applies = serializers.BooleanField()
    reason = serializers.ChoiceField(["too_early", "loss"], allow_null=True)
    business_low = money(allow_null=True)
    business_high = money(allow_null=True)
    cash = money()
    debt = money()
    low = money(allow_null=True)
    high = money(allow_null=True)


class ValuationNetAssetsSerializer(serializers.Serializer):
    value = money()
    assets = money()
    liabilities = money()
    stock = money(allow_null=True)
    fixed_assets = money(allow_null=True)


class ValuationRangeSerializer(serializers.Serializer):
    low = money()
    high = money()


MULTIPLE = {"max_digits": 4, "decimal_places": 1}


class ValuationSerializer(serializers.Serializer):
    on = serializers.DateField()
    currency = serializers.CharField()
    multiple_low = serializers.DecimalField(**MULTIPLE)
    multiple_high = serializers.DecimalField(**MULTIPLE)
    default_low = serializers.DecimalField(**MULTIPLE)
    default_high = serializers.DecimalField(**MULTIPLE)
    earnings = ValuationEarningsSerializer()
    earnings_method = ValuationMethodSerializer()
    net_assets = ValuationNetAssetsSerializer()
    range = ValuationRangeSerializer()
    editable = serializers.BooleanField(help_text="Whether the caller may change the multiples.")


class ValuationUpdateSerializer(serializers.Serializer):
    """The multiple range of a year's earnings; null goes back to the default."""

    multiple_low = serializers.DecimalField(
        **MULTIPLE, min_value=Decimal("0.5"), max_value=Decimal(20), allow_null=True
    )
    multiple_high = serializers.DecimalField(
        **MULTIPLE, min_value=Decimal("0.5"), max_value=Decimal(20), allow_null=True
    )


class StatementPackSerializer(serializers.ModelSerializer):
    branches = serializers.SerializerMethodField()
    expires_at = serializers.SerializerMethodField()
    file_name = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = StatementPack
        fields = (
            "id",
            "period",
            "start",
            "end",
            "purpose",
            "language",
            "branches",
            "status",
            "progress",
            "pages",
            "error",
            "deliver_telegram",
            "created_at",
            "finished_at",
            "expires_at",
            "file_name",
            "file_url",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.ListField(child=serializers.IntegerField(), allow_null=True))
    def get_branches(self, pack: StatementPack):
        return pack.params.get("branch")

    @extend_schema_field(serializers.DateTimeField())
    def get_expires_at(self, pack: StatementPack) -> str:
        return serializers.DateTimeField().to_representation(pack.created_at + statement_pack.KEEP)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_file_name(self, pack: StatementPack) -> str | None:
        return statement_pack.download_name(pack) if pack.file else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_file_url(self, pack: StatementPack) -> str | None:
        """A signed link valid for 10 minutes, checked again when used."""
        if pack.status != StatementPack.Status.READY or not pack.file:
            return None
        return files.signed_url(
            pack.file,
            user=self.context["request"].user,
            company_id=pack.company_id,
            check=f"finance.statement_pack:{pack.pk}",
            filename=statement_pack.download_name(pack),
        )


class StatementPackRequestSerializer(serializers.Serializer):
    period = serializers.ChoiceField(StatementPack.Period.choices)
    of = serializers.DateField(help_text="Any day of the month, quarter or year.")
    purpose = serializers.ChoiceField(StatementPack.Purpose.choices)
    language = serializers.CharField(max_length=2, help_text="uz, ru or en.")
    branch = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list, max_length=100
    )
    multiple_low = serializers.DecimalField(
        **MULTIPLE, min_value=Decimal("0.5"), max_value=Decimal(20), required=False
    )
    multiple_high = serializers.DecimalField(
        **MULTIPLE, min_value=Decimal("0.5"), max_value=Decimal(20), required=False
    )
    deliver_telegram = serializers.BooleanField(required=False, default=False)

    def validate_language(self, value: str) -> str:
        if value not in statement_pack.LANGUAGES:
            raise serializers.ValidationError(_("Pick Uzbek, Russian or English."))
        return value


class StatementOptionsSerializer(serializers.Serializer):
    today = serializers.DateField()
    books_start = serializers.DateField(allow_null=True)
    last_activity = serializers.DateField(allow_null=True)
    language = serializers.CharField(help_text="The caller's language, the default.")
    whole_company = serializers.BooleanField(help_text="Whether the caller sees every branch.")
    may_prepare = serializers.BooleanField()
    telegram = serializers.BooleanField(
        help_text="Whether the PDF can go to the caller's Telegram."
    )
