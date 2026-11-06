"""Demo Dorixona's money planning (Package I, docs/PLAN-OWNER.md §14.8 "Demo"): the VAT
regime and its tax calendar, recurring rent, utilities and internet, this and last month's
budgets (one near its limit, one over it), expense claims in each state, a manufacturer's
marketing bonus and a destruction service. Built by `demo.Ledger.build` once the ledger's two
months are booked; every name is invented.

Distributor payables come from the ledger's daily deliveries on credit (their due dates fill
the Payables screen and Upcoming); J1's goods receipts don't exist yet, so nothing is booked
twice.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.files.base import ContentFile
from django.utils import timezone, translation
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
                )
                .exclude(system_code__in=claims.CLAIM_EXCLUDED)
                .select_related("parent")
                if spent.get(category.pk, D(0)) > 0 and category.parent_id is not None
            ),
            key=lambda category: -spent[category.pk],
        )
        # Everyday spending first: a fixed cost such as rent "over budget" is no story.
        fixed = {
            category.pk
            for category in busy
            if category.parent is not None and category.parent.system_code in FIXED_COSTS
        }
        busy = [c for c in busy if c.pk not in fixed] + [c for c in busy if c.pk in fixed]
        rows = [(category, amount) for category, amount in calm]
        taken = {category.pk for category, _amount in rows}
        shares = iter(("0.88", "1.12"))
        for category in busy:
            if category.pk in taken:
                continue
            share = next(shares, None)
            if share is None:
                break
            rows.append((category, _tidy(spent[category.pk] / D(share))))
        budgets.set_budgets(company, by=owner, month=start, rows=rows)


FIXED_COSTS = ("rent", "salaries", "taxes", "payroll_taxes")


def _tidy(amount: Decimal) -> Decimal:
    """A budget as people write one: 105 000 000, 4 300 000, 850 000."""
    step = D("1000000") if amount >= D("20000000") else D("100000")
    if amount < D("1000000"):
        step = D("10000")
    return max((amount / step).quantize(D(1)) * step, step)


def _claims(ledger) -> None:
    """Jasur's fuel waiting for approval, Madina's printer paper approved (payroll pays it
    back), the head's taxi from the cash he holds (below the threshold: booked at once) and
    Nigora's night taxi rejected. Each is sent within its person's hours on the day after the
    spending and decided the next morning (`demo_time.moment`), so the times read naturally."""
    from apps.core import demo_time
    from apps.finance.demo import _receipt_picture  # demo imports this module

    company, today = ledger.company, ledger.today
    people = ledger.people
    zone = ZoneInfo(company.timezone)
    transport = Category.objects.get(company=company, system_code="transport")
    other = Category.objects.get(company=company, system_code="other_expense")
    fuel = ledger.cat["fuel"]

    def at(key: str, day, hour: int, minute: int = 0):
        moment = datetime.combine(day, time(hour, minute), tzinfo=zone)
        return min(ledger.story.at_work(key, day, moment), timezone.now())

    def submit(key: str, ago: int, hour: int, **fields):
        spent = today - timedelta(days=ago)
        sent = min(spent + timedelta(days=1), today)
        with demo_time.moment(at(key, sent, hour, 20)):
            return claims.submit_claim(company, by=people[key], spent_on=spent, **fields)

    def decide(claim, ago: int, **fields):
        day = today - timedelta(days=ago)
        with demo_time.moment(at("owner", day, 10, 5)):
            claims.decide_claim(claim, by=ledger.owner, **fields)

    submit(
        "jasur",
        1,
        11,
        amount=D("260000"),
        category=fuel,
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
    paper = submit(
        "madina",
        4,
        9,
        amount=D("240000"),
        category=other,
        paid_from=Claim.PaidFrom.OWN_MONEY,
        description="Printer uchun qog‘oz va kartrij",
        via=Claim.Via.MINIAPP,
    )
    decide(paper, 2, approve=True)
    held = sum((account.balance for account in claims.held_accounts(ledger.manager)), D(0))
    if held >= D("150000"):
        submit(
            "manager",
            2,
            12,
            amount=D("150000"),
            category=transport,
            paid_from=Claim.PaidFrom.HELD_CASH,
            description="Taksi: distribyutordan shoshilinch dori olib kelish",
            via=Claim.Via.MINIAPP,
        )
    night = submit(
        "nigora",
        3,
        21,
        amount=D("320000"),
        category=transport,
        paid_from=Claim.PaidFrom.OWN_MONEY,
        description="Tungi smenadan keyin taksi",
        via=Claim.Via.BOT,
    )
    decide(
        night,
        1,
        approve=False,
        reason="Tungi smena taksisi ish haqiga kiritilgan, alohida qaytarilmaydi.",
    )
