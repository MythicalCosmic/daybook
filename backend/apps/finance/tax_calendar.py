"""Tax calendar templates (Package I, §1.6, §14.8): one set of recurring tax bills per regime.

Applying a set makes ordinary, editable recurring rules: bills whose amount varies (it starts
unknown and becomes the last amount paid), owed to the tax office, in the system categories
"taxes" and "payroll_taxes". The due days are typical deadlines, not legal advice: every one
is a setting the company edits, and the screen says to confirm them with an accountant.

Template keys are shared between regimes where the tax is the same (income tax, pension
contributions and social tax are due whatever the sales tax), so switching regime and applying
the new set never doubles them.
"""

from dataclasses import dataclass
from datetime import date

from django.db import transaction
from django.utils import translation
from django.utils.translation import gettext_lazy as _

from apps.core.exceptions import DomainError
from apps.finance import recurring, services
from apps.finance.audit_actions import FinanceAction
from apps.finance.models import Category, FinanceSettings, RecurringRule
from apps.members.models import Membership

Frequency = RecurringRule.Frequency
Regime = FinanceSettings.TaxRegime


@dataclass(frozen=True)
class Item:
    key: str  # RecurringRule.template_key, "tax.<name>"
    name: object  # lazy text, rendered in the company's language when applied
    frequency: str
    day: int
    category_code: str  # a system category


TURNOVER_TAX = Item("tax.turnover", _("Turnover tax"), Frequency.QUARTERLY, 25, "taxes")
VAT = Item("tax.vat", _("VAT (QQS)"), Frequency.MONTHLY, 20, "taxes")
SIMPLIFIED_VAT = Item("tax.vat_simplified", _("Simplified VAT"), Frequency.MONTHLY, 20, "taxes")
PROFIT_TAX = Item("tax.profit", _("Profit tax"), Frequency.QUARTERLY, 25, "taxes")
INCOME_TAX = Item(
    "tax.income_tax", _("Personal income tax (JShDS)"), Frequency.MONTHLY, 15, "payroll_taxes"
)
PENSION = Item(
    "tax.inps", _("Pension contributions (INPS)"), Frequency.MONTHLY, 15, "payroll_taxes"
)
SOCIAL_TAX = Item("tax.social_tax", _("Social tax"), Frequency.MONTHLY, 15, "payroll_taxes")

PAYROLL_TAXES = (INCOME_TAX, PENSION, SOCIAL_TAX)
TEMPLATES: dict[str, tuple[Item, ...]] = {
    Regime.TURNOVER: (TURNOVER_TAX, *PAYROLL_TAXES),
    Regime.VAT: (VAT, PROFIT_TAX, *PAYROLL_TAXES),
    Regime.VAT_SIMPLIFIED: (SIMPLIFIED_VAT, *PAYROLL_TAXES),
}
NOTE = _("Typical due days; confirm them with your accountant.")


def first_day(item: Item, today: date) -> date:
    """Where an applied rule's schedule starts: monthly taxes this month, quarterly ones in the
    first month of a quarter (January, April, July, October), for the previous quarter."""
    if item.frequency == Frequency.QUARTERLY:
        month = (today.month - 1) // 3 * 3 + 1
        return date(today.year, month, 1)
    return date(today.year, today.month, 1)


def templates(company) -> list[dict]:
    """Every regime's set, the company's own regime first, with what is already applied."""
    current = services.get_settings(company).tax_regime
    applied = dict(
        RecurringRule.objects.for_company(company)
        .filter(is_active=True)
        .exclude(template_key="")
        .values_list("template_key", "pk")
    )
    order = [current, *(regime for regime in TEMPLATES if regime != current)]
    return [
        {
            "key": str(regime),
            "label": str(Regime(regime).label),
            "current": regime == current,
            "note": str(NOTE),
            "items": [
                {
                    "template_key": item.key,
                    "name": str(item.name),
                    "frequency": str(item.frequency),
                    "day": item.day,
                    "category_code": item.category_code,
                    "applied": item.key in applied,
                    "rule_id": applied.get(item.key),
                }
                for item in TEMPLATES[regime]
            ],
        }
        for regime in order
    ]


def apply(company, *, by: Membership, key: str) -> list[RecurringRule]:
    """Make the set's rules the company doesn't have yet (switched-on ones by template key)."""
    if key not in TEMPLATES:
        raise DomainError(_("There is no tax calendar for that regime."))
    today = recurring._today(company)
    made = []
    with transaction.atomic():
        have = set(
            RecurringRule.objects.for_company(company)
            .select_for_update()
            .filter(is_active=True)
            .exclude(template_key="")
            .values_list("template_key", flat=True)
        )
        office = recurring.tax_office(company, by=by)
        for item in TEMPLATES[key]:
            if item.key in have:
                continue
            category = Category.objects.filter(
                company=company, system_code=item.category_code
            ).first() or services._category(company, item.category_code)
            with translation.override(company.default_language or "uz"):
                name = str(item.name)
            made.append(
                recurring.create_rule(
                    company,
                    by=by,
                    name=name,
                    kind=Category.Kind.EXPENSE,
                    mode=RecurringRule.Mode.BILL,
                    frequency=item.frequency,
                    day=item.day,
                    on_holiday=RecurringRule.OnHoliday.AFTER,
                    category=category,
                    counterparty=office,
                    amount=0,
                    amount_varies=True,
                    starts_on=first_day(item, today),
                    remind_days_before=5,
                    template_key=item.key,
                )
            )
        if made:
            services._audit(
                FinanceAction.TAX_CALENDAR_APPLIED,
                company,
                by.user,
                services.get_settings(company),
                regime=key,
                rules=[rule.pk for rule in made],
            )
    return made
