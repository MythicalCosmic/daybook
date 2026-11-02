"""Default rows of payroll for a company: example rules, shipped switched off, named in the
company's language. A company switches on (and tunes) the ones it wants."""

from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import translation
from django.utils.translation import gettext as _

from apps.payroll.models import AdjustmentRule

Rule = AdjustmentRule


def examples() -> list[dict]:
    """The shipped examples (names in the active language)."""
    return [
        {
            "example_key": "on_time",
            "name": _("On-time bonus"),
            "kind": Rule.Kind.BONUS,
            "metric": Rule.Metric.TASKS_ON_TIME_PERCENT,
            "mode": Rule.Mode.TIERED,
            "op": Rule.Op.GTE,
            "tiers": [
                {"threshold": "90", "amount": "100000.00"},
                {"threshold": "95", "amount": "300000.00"},
                {"threshold": "99", "amount": "500000.00"},
            ],
            "min_tasks": 10,
        },
        {
            "example_key": "late_arrivals",
            "name": _("Late arrival fine"),
            "kind": Rule.Kind.FINE,
            "metric": Rule.Metric.LATE_ARRIVALS,
            "mode": Rule.Mode.PER_UNIT,
            "free_units": Decimal(2),
            "amount": Decimal("20000"),
            "cap": Decimal("200000"),
        },
        {
            "example_key": "sales_bonus",
            "name": _("Sales bonus, 1%"),
            "kind": Rule.Kind.BONUS,
            "metric": Rule.Metric.SALES_NET,
            "mode": Rule.Mode.ONCE,
            "op": Rule.Op.GT,
            "threshold": Decimal(0),
            "amount_type": Rule.AmountType.PERCENT,
            "amount": Decimal("1.00"),
        },
    ]


def ensure(company) -> None:
    """Create the missing default rows. Idempotent: it runs from the `company_created`
    receiver and from `manage.py ensure_company_defaults` after every deploy."""
    have = set(
        AdjustmentRule.objects.for_company(company)
        .exclude(example_key="")
        .values_list("example_key", flat=True)
    )
    with translation.override(company.default_language or "uz"):
        wanted = [row for row in examples() if row["example_key"] not in have]
    for row in wanted:
        try:
            with transaction.atomic():
                AdjustmentRule.objects.create(company=company, is_active=False, **row)
        except IntegrityError:
            continue
