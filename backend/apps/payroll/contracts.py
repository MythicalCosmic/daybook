"""What payroll promises other apps (docs/PLAN-OWNER.md §13.3).

Projects (package T) price logged time with `cost_rate`, from the member's pay setup on the
day: a monthly salary over the month's working days times `daily_hours`, a daily rate over
`daily_hours`, an hourly rate as it is. Task pay has no hourly cost, so labour cost is left out.
"""

from datetime import date
from decimal import Decimal


def cost_rate(membership, day: date) -> Decimal | None:
    """What one hour of the member's time costs the company on `day`, in the company's base
    currency; None when unknown (no compensation, or a pay type without an hourly cost).
    A time entry's labour cost is `minutes / 60 * cost_rate`."""
    from apps.core.money import quantize
    from apps.payroll import conf, periods, queries
    from apps.payroll.models import PayType

    setup = queries.compensation(membership, on=day)
    if setup is None or setup.pay_type == PayType.PER_TASK:
        return None
    company = membership.company
    hours = conf.get_settings(company).daily_hours
    if setup.pay_type == PayType.MONTHLY:
        days = queries.plain_scheduled_days(company, periods.first_day(day))
        if not days:
            return None
        hourly = setup.amount / (Decimal(days) * hours)
    elif setup.pay_type == PayType.DAILY:
        hourly = setup.amount / hours
    else:
        hourly = setup.amount
    if setup.currency == company.base_currency:
        return quantize(hourly)
    from apps.core.exceptions import DomainError
    from apps.finance.rates import convert, rate_for

    try:
        rate = rate_for(company, "USD", day).rate
    except DomainError:
        return None
    return convert(hourly, setup.currency, company.base_currency, rate)
