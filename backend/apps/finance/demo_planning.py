"""Demo Dorixona's money planning (Package I, docs/PLAN-OWNER.md §14.8 "Demo"): the VAT
regime and its tax calendar, recurring rent, utilities and internet, this and last month's
budgets (one near its limit, one over it), expense claims in each state, a manufacturer's
marketing bonus and a destruction service. Built by `demo.Ledger.build` once the ledger's two
months are booked; every name is invented.

Distributor payables come from the ledger's daily deliveries on credit (their due dates fill
the Payables screen and Upcoming); J1's goods receipts don't exist yet, so nothing is booked
twice.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.files.base import ContentFile
from django.utils import translation
from django.utils.translation import gettext as _

from apps.finance import budgets, claims, recurring, services, tax_calendar
from apps.finance.models import Category, Claim, RecurringRule

D = Decimal
# The pharmacy categories in the demo's Uzbek (as the translations will name them).
PHARMACY_NAMES = {
    "Marketing bonuses": "Marketing bonuslari",
    "Insurance fund reimbursements": "Sug‘urta fondi to‘lovlari",
    "Licences and certificates": "Litsenziya va sertifikatlar",
    "Destruction services": "Utilizatsiya xizmatlari",
    "Instrument checks": "O‘lchov asboblarini tekshirish",
}
INCOME = {"Marketing bonuses", "Insurance fund reimbursements"}


def build(ledger) -> None:
    company = ledger.company
    owner = ledger.owner
    categories = _pharmacy_categories(company, owner)
    services.update_settings(company, by=owner, tax_regime="vat")
    _recurring(ledger)
    tax_calendar.apply(company, by=owner, key="vat")
    _extras(ledger, categories)
    _budgets(ledger)
    _claims(ledger)


def _pharmacy_categories(company, owner) -> dict[str, Category]:
    found = {}
    plain = Category.objects.filter(company=company, system_code="", parent=None)
    for english, uzbek in PHARMACY_NAMES.items():
        with translation.override(company.default_language):
            current = str(_(english))
        row = plain.filter(name__in={current, english, uzbek}).first()
        if row is None:
            kind = Category.Kind.INCOME if english in INCOME else Category.Kind.EXPENSE
            row = services.create_category(company, by=owner, name=uzbek, kind=kind)
        elif row.name != uzbek:
            row = services.update_category(row, by=owner, name=uzbek)
        found[english] = row
    return found


def _recurring(ledger) -> None:
    company, owner, today = ledger.company, ledger.owner, ledger.today
    start = today.replace(day=1) - timedelta(days=62)
    recurring.create_rule(
        company,
        by=owner,
        name=f"Ijara: {ledger.chl.name}",
        kind="expense",
        mode="bill",
        frequency="monthly",
        day=3,
        category=ledger.cat["rent_chl"],
        counterparty=ledger.party["landlord_chl"],
        account=ledger.bank,
        branch=ledger.chl,
        amount=D("9000000"),
        starts_on=start,
        remind_days_before=3,
        payer=owner,
    )
    recurring.create_rule(
        company,
        by=owner,
        name="Elektr energiyasi",
        kind="expense",
        mode="bill",
        frequency="monthly",
        day=10,
        category=ledger.cat["electricity"],
        counterparty=ledger.party["electric"],
        account=ledger.bank,
        amount=D("4200000"),
        amount_varies=True,
        starts_on=start,
        remind_days_before=2,
        payer=ledger.manager,
    )
    recurring.create_rule(
        company,
        by=owner,
        name="Internet, ikki dorixona",
        kind="expense",
        mode="auto",
        frequency="monthly",
        day=10,
        category=ledger.cat["internet"],
        counterparty=ledger.party["internet"],
        account=ledger.card,
        amount=D("420000"),
        starts_on=start,
    )
    recurring.create_rule(
        company,
        by=owner,
        name="Oylik dezinfeksiya",
        kind="expense",
        mode="bill",
        frequency="monthly",
        day=15,
        on_holiday=RecurringRule.OnHoliday.AFTER,
        category=ledger.cat["disinfection"],
        counterparty=ledger.party["sanitary"],
        account=ledger.bank,
        amount=D("900000"),
        starts_on=start,
    )


def _extras(ledger, categories) -> None:
    """A marketing bonus from a distributor and a destruction service, last week."""
    company, owner = ledger.company, ledger.owner
    day = ledger.today - timedelta(days=6)
    services.record_transaction(
        company,
        by=owner,
        kind="income",
        amount=D("1500000"),
        occurred_on=day,
        account=ledger.bank,
        category=categories["Marketing bonuses"],
        counterparty=ledger.party["oqtosh"],
        description="Vitrina uchun marketing bonusi, oktabr rejasi",
    )
    service = services.create_counterparty(
        company, by=owner, name="Eko Utilizatsiya Servis", kind="supplier"
    )
    services.record_transaction(
        company,
        by=owner,
        kind="expense",
        amount=D("650000"),
        occurred_on=day + timedelta(days=1),
        account=ledger.bank,
        category=categories["Destruction services"],
        counterparty=service,
        branch=ledger.yns,
        description="Muddati o‘tgan dorilarni yo‘q qilish, dalolatnoma bilan",
    )


def _budgets(ledger) -> None:
    """Last month's and this month's budgets: the two biggest everyday spends near and over
    their limits (alerts on Overview and in the bot), the rest with room to spare."""
    company, owner, today = ledger.company, ledger.owner, ledger.today
    month = today.replace(day=1)
    calm = [
        (ledger.cat["fuel"], D("1500000")),
        (ledger.cat["repairs"], D("1000000")),
        (ledger.cat["disinfection"], D("1200000")),
    ]
    for start in (budgets.previous_month(month), month):
        spent = budgets.actuals(company, start, branch_ids=None)
        busy = sorted(
            (
                category
                for category in Category.objects.filter(
                    company=company, kind=Category.Kind.EXPENSE, is_sensitive=False
                ).exclude(system_code__in=claims.CLAIM_EXCLUDED)
                if spent.get(category.pk, D(0)) > 0 and category.parent_id is not None
            ),
            key=lambda category: -spent[category.pk],
        )
        rows = [(category, amount) for category, amount in calm]
        taken = {category.pk for category, _amount in rows}
        shares = iter(("0.88", "1.12"))
        for category in busy:
            if category.pk in taken:
                continue
            share = next(shares, None)
            if share is None:
                break
            amount = (spent[category.pk] / D(share)).quantize(D("1000"))
            rows.append((category, max(amount, D("1000"))))
        budgets.set_budgets(company, by=owner, month=start, rows=rows)


def _claims(ledger) -> None:
    """Jasur's fuel waiting for approval, Madina's printer paper approved (payroll pays it
    back), the head's taxi from the cash he holds (below the threshold: booked at once) and
    Nigora's night taxi rejected."""
    company, today = ledger.company, ledger.today
    people = ledger.people
    transport = Category.objects.get(company=company, system_code="transport")
    other = Category.objects.get(company=company, system_code="other_expense")
    fuel = ledger.cat["fuel"]
    from apps.finance.demo import _receipt_picture  # demo imports this module

    claims.submit_claim(
        company,
        by=people["jasur"],
        amount=D("260000"),
        category=fuel,
        spent_on=today - timedelta(days=1),
        paid_from=Claim.PaidFrom.OWN_MONEY,
        description="Yetkazib berish uchun benzin, Chilonzor - Yunusobod",
        receipt_files=[
            ContentFile(
                _receipt_picture(
                    "YOQILG‘I SHOXOBCHASI",
                    today - timedelta(days=1),
                    [("AI-92, 20 l", "260 000")],
                    "260 000",
                ),
                name="receipt.jpg",
            )
        ],
        via=Claim.Via.BOT,
    )
    paper = claims.submit_claim(
        company,
        by=people["madina"],
        amount=D("240000"),
        category=other,
        spent_on=today - timedelta(days=4),
        paid_from=Claim.PaidFrom.OWN_MONEY,
        description="Printer uchun qog‘oz va kartrij",
        via=Claim.Via.MINIAPP,
    )
    claims.decide_claim(paper, by=ledger.owner, approve=True)
    held = sum((account.balance for account in claims.held_accounts(ledger.manager)), D(0))
    if held >= D("150000"):
        claims.submit_claim(
            company,
            by=ledger.manager,
            amount=D("150000"),
            category=transport,
            spent_on=today - timedelta(days=2),
            paid_from=Claim.PaidFrom.HELD_CASH,
            description="Taksi: distribyutordan shoshilinch dori olib kelish",
            via=Claim.Via.MINIAPP,
        )
    night = claims.submit_claim(
        company,
        by=people["nigora"],
        amount=D("320000"),
        category=transport,
        spent_on=today - timedelta(days=3),
        paid_from=Claim.PaidFrom.OWN_MONEY,
        description="Tungi smenadan keyin taksi",
        via=Claim.Via.BOT,
    )
    claims.decide_claim(
        night,
        by=ledger.owner,
        approve=False,
        reason="Tungi smena taksisi ish haqiga kiritilgan, alohida qaytarilmaydi.",
    )
