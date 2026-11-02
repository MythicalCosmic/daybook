"""What HR reads from payroll (package H), tolerant of its absence: payroll lands on its own
branch, so until both are in, a contract simply prints without the pay.

`payroll.Compensation` has the fields docs/PLAN-OWNER.md §3.13 fixes (membership,
effective_from, pay_type, amount, currency); anything else reads as "no pay known".
"""

import logging
from datetime import date

from django.apps import apps as django_apps
from django.core.exceptions import FieldError
from django.db import DatabaseError
from django.utils.translation import gettext as _

from apps.core.money import format_money

logger = logging.getLogger(__name__)


def salary_text(membership, day: date, language: str) -> str:
    """The person's pay on `day` as a contract states it ("5 200 000 so‘m a month"), or ""."""
    try:
        compensation = django_apps.get_model("payroll", "Compensation")
    except LookupError:
        return ""
    try:
        row = (
            compensation.objects.filter(membership=membership, effective_from__lte=day)
            .order_by("-effective_from")
            .first()
        )
        if row is None:
            return ""
        amount = format_money(row.amount, row.currency, language)
        pay_type = row.pay_type
    except FieldError, AttributeError, DatabaseError:
        logger.warning("payroll.Compensation can't be read for a contract", exc_info=True)
        return ""
    per = {
        # Translators: %(amount)s is money with its currency, e.g. "5 200 000 so‘m".
        "monthly": _("%(amount)s a month"),
        "daily": _("%(amount)s a day"),
        "hourly": _("%(amount)s an hour"),
        "per_task": _("%(amount)s a task"),
    }.get(pay_type)
    return per % {"amount": amount} if per else amount
