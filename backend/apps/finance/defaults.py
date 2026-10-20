"""Default rows of the finance ledger for a company: the system categories and two accounts.

The system categories carry a `system_code` the services book into (`category="sales"`), so
they're found by code, never by name: owners may rename them. The two accounts ("Kassa" and
"Terminal" in Uzbek) are made only for a company with no accounts yet, so one renamed or
archived never comes back.
"""

from django.db import IntegrityError, transaction
from django.utils import translation
from django.utils.translation import gettext_lazy as _

from apps.finance.models import Category, MoneyAccount

INCOME = Category.Kind.INCOME
EXPENSE = Category.Kind.EXPENSE

# (system_code, kind, name, is_sensitive), in the order the dashboard lists them.
SYSTEM_CATEGORIES = (
    ("sales", INCOME, _("Sales"), False),
    ("refunds", INCOME, _("Refunds"), False),
    ("cash_surplus", INCOME, _("Cash surplus"), False),
    ("other_income", INCOME, _("Other income"), False),
    ("goods", EXPENSE, _("Goods for sale"), False),
    ("rent", EXPENSE, _("Rent"), False),
    ("utilities", EXPENSE, _("Utilities"), False),
    ("salaries", EXPENSE, _("Salaries"), True),
    ("payroll_taxes", EXPENSE, _("Payroll taxes"), False),
    ("bank_fees", EXPENSE, _("Bank fees"), False),
    ("taxes", EXPENSE, _("Taxes"), False),
    ("marketing", EXPENSE, _("Marketing"), False),
    ("transport", EXPENSE, _("Transport"), False),
    ("repairs", EXPENSE, _("Repairs"), False),
    ("cash_shortage", EXPENSE, _("Cash shortage"), False),
    ("bad_debts", EXPENSE, _("Bad debts"), False),
    ("fx_diff", EXPENSE, _("Exchange differences"), False),
    ("other_expense", EXPENSE, _("Other expenses"), False),
)
SYSTEM_CODES = frozenset(code for code, *_rest in SYSTEM_CATEGORIES)

DEFAULT_ACCOUNTS = (
    (MoneyAccount.Kind.CASH, _("Cash desk")),
    (MoneyAccount.Kind.CLEARING, _("Card terminal")),
)


def ensure(company) -> None:
    """Create the missing default rows. Idempotent: it runs from the `company_created`
    receiver and from `manage.py ensure_company_defaults` after every deploy."""
    with translation.override(company.default_language), transaction.atomic():
        have = set(
            Category.objects.filter(company=company)
            .exclude(system_code="")
            .values_list("system_code", flat=True)
        )
        for order, (code, kind, name, sensitive) in enumerate(SYSTEM_CATEGORIES):
            if code not in have:
                _add_system_category(company, code, kind, str(name), order, sensitive)
        if not MoneyAccount.objects.filter(company=company).exists():
            for order, (kind, name) in enumerate(DEFAULT_ACCOUNTS):
                _create_quietly(
                    MoneyAccount,
                    company=company,
                    kind=kind,
                    name=str(name),
                    currency=company.base_currency,
                    order=order,
                )


def _add_system_category(company, code, kind, name, order, sensitive) -> None:
    same_name = Category.objects.filter(company=company, parent=None, name=name).first()
    if same_name is not None and same_name.kind == kind and not same_name.system_code:
        # The owner made it before the system did: adopt theirs.
        same_name.system_code = code
        same_name.is_sensitive = same_name.is_sensitive or sensitive
        same_name.save(update_fields=["system_code", "is_sensitive", "updated_at"])
        return
    if same_name is not None:
        name = free_name(Category.objects.filter(company=company, parent=None), name)
    _create_quietly(
        Category,
        company=company,
        system_code=code,
        kind=kind,
        name=name,
        order=order,
        is_sensitive=sensitive,
    )


def _create_quietly(model, **fields) -> None:
    """Create the row unless a concurrent `ensure` just did."""
    try:
        with transaction.atomic():
            model.objects.create(**fields)
    except IntegrityError:
        pass


def free_name(queryset, name: str, max_length: int = 100) -> str:
    """`name`, or `name (2)`, `name (3)`… whichever no row of `queryset` has yet."""
    taken = set(
        queryset.filter(name__startswith=name[: max_length - 6]).values_list("name", flat=True)
    )
    if name not in taken:
        return name
    number = 2
    while True:
        suffix = f" ({number})"
        candidate = name[: max_length - len(suffix)] + suffix
        if candidate not in taken:
            return candidate
        number += 1
