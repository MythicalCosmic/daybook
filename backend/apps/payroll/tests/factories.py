"""factory_boy factories for the models of payroll.

Most tests make rows through the services; these build plain rows for the queries and the
calculator.
"""

from datetime import date
from decimal import Decimal

import factory
from factory.django import DjangoModelFactory

from apps.payroll.models import Adjustment, Advance, Compensation, PayType, TaskRate


class CompensationFactory(DjangoModelFactory):
    class Meta:
        model = Compensation

    company = factory.SelfAttribute("membership.company")
    effective_from = date(2026, 1, 1)
    pay_type = PayType.MONTHLY
    amount = Decimal("5200000")


class AdjustmentFactory(DjangoModelFactory):
    class Meta:
        model = Adjustment

    company = factory.SelfAttribute("membership.company")
    period = date(2026, 10, 1)
    kind = Adjustment.Kind.BONUS
    amount = Decimal("100000")
    reason = "Good work"
    status = Adjustment.Status.APPROVED


class AdvanceFactory(DjangoModelFactory):
    class Meta:
        model = Advance

    company = factory.SelfAttribute("membership.company")
    amount = Decimal("1000000")
    first_period = date(2026, 10, 1)
    status = Advance.Status.APPROVED


class TaskRateFactory(DjangoModelFactory):
    class Meta:
        model = TaskRate

    amount = Decimal("5000")
