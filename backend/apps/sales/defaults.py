"""Default rows of sales and cash for a company: payment methods, a till per branch, safes.

Runs only for companies with the sales module on: switching the module on (package A's
`set_features`) runs it, and so does every deploy (`ensure_company_defaults`). A branch added
later gets its till from the `post_save` receiver in `hooks.py`.

Default names are data, written once in the company's language (the owner can rename them), so
they come from the tables below rather than the translation catalogue.
"""

from django.db import IntegrityError, transaction

from apps.companies.models import Feature
from apps.finance import services as finance
from apps.finance.models import MoneyAccount
from apps.sales import finance_bridge
from apps.sales.models import PaymentMethod, Register

Kind = PaymentMethod.Kind

# (system_code, kind, {language: name}) in the order the cashier sees them.
DEFAULT_METHODS = (
    ("cash", Kind.CASH, {"uz": "Naqd", "ru": "Наличные", "en": "Cash"}),
    ("uzcard", Kind.CARD, {"uz": "Uzcard", "ru": "Uzcard", "en": "Uzcard"}),
    ("humo", Kind.CARD, {"uz": "Humo", "ru": "Humo", "en": "Humo"}),
    (
        "visa",
        Kind.CARD,
        {"uz": "Visa/Mastercard", "ru": "Visa/Mastercard", "en": "Visa/Mastercard"},
    ),
    ("click", Kind.QR, {"uz": "Click", "ru": "Click", "en": "Click"}),
    ("payme", Kind.QR, {"uz": "Payme", "ru": "Payme", "en": "Payme"}),
    ("uzum", Kind.QR, {"uz": "Uzum", "ru": "Uzum", "en": "Uzum"}),
    ("transfer", Kind.TRANSFER, {"uz": "Pul o‘tkazma", "ru": "Перевод", "en": "Bank transfer"}),
    ("credit", Kind.CREDIT, {"uz": "Nasiya", "ru": "Насия", "en": "Credit (nasiya)"}),
    (
        "installment",
        Kind.INSTALLMENT,
        {"uz": "Muddatli to‘lov", "ru": "Рассрочка", "en": "Instalments"},
    ),
)
TILL_NAME = {"uz": "Kassa 1", "ru": "Касса 1", "en": "Till 1"}


def ensure(company) -> None:
    """Create the missing default rows. Idempotent: it runs from the `company_created`
    receiver and from `manage.py ensure_company_defaults` after every deploy."""
    if not company.has_feature(Feature.SALES):
        return
    with transaction.atomic():
        ensure_methods(company)
        for branch in company.branches.filter(is_active=True).order_by("order", "pk"):
            ensure_branch(branch)


def ensure_methods(company) -> None:
    language = _language(company)
    have = set(
        PaymentMethod.objects.filter(company=company)
        .exclude(system_code="")
        .values_list("system_code", flat=True)
    )
    clearing = (
        MoneyAccount.objects.filter(
            company=company,
            kind=MoneyAccount.Kind.CLEARING,
            branch=None,
            is_active=True,
            currency=company.base_currency,
        )
        .order_by("order", "pk")
        .first()
    )
    taken = set(PaymentMethod.objects.filter(company=company).values_list("name", flat=True))
    for order, (code, kind, names) in enumerate(DEFAULT_METHODS):
        if code in have:
            continue
        name = names.get(language, names["en"])
        if name in taken:  # the owner made one with this name first: adopt it
            PaymentMethod.objects.filter(company=company, name=name, system_code="").update(
                system_code=code
            )
            continue
        account = None
        if kind not in (Kind.CASH, Kind.CREDIT):
            account = clearing
        _create_quietly(
            PaymentMethod,
            company=company,
            system_code=code,
            kind=kind,
            name=name,
            account=account,
            order=order,
        )


def ensure_branch(branch) -> Register | None:
    """A till (with its cash account) and a safe for an active branch that has none."""
    company = branch.company
    if not company.has_feature(Feature.SALES) or not branch.is_active:
        return None
    finance.account_for_branch(branch, kind=MoneyAccount.Kind.SAFE, currency=company.base_currency)
    existing = Register.objects.filter(company=company, branch=branch).order_by("pk").first()
    if existing is not None:
        return existing
    name = TILL_NAME.get(_language(company), TILL_NAME["en"])
    try:
        with transaction.atomic():
            account = finance_bridge.create_till_account(name, branch, by=None)
            return Register.objects.create(
                company=company, branch=branch, name=name, cash_account=account
            )
    except IntegrityError:
        return Register.objects.filter(company=company, branch=branch).order_by("pk").first()


def _language(company) -> str:
    language = (company.default_language or "uz")[:2]
    return language if language in ("uz", "ru", "en") else "uz"


def _create_quietly(model, **fields) -> None:
    try:
        with transaction.atomic():
            model.objects.create(**fields)
    except IntegrityError:
        pass
