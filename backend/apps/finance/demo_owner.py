"""Demo Dorixona's owner's money (v11), built by `demo.finish` once every app has booked its rows
and before the books close: two partners (the owner 60 %, an outside investor 40 %, since the
start of the year), last quarter's dividend prepared and paid from the bank in the month after
it, one more draw this month beside the ledger's monthly one, two planned purchases (one soon,
one later), and the bank loan's instalment plan (the 5th of each month, as the ledger pays it),
so the safe amount has its reasons. Every name is invented.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from apps.core.demo_time import moment
from apps.finance import owner_draw, partners, queries, services
from apps.finance.models import Debt, MoneyAccount

D = Decimal
INVESTOR = "Farhod Ergashev"
LOAN_PAYMENT = D("6700000")
PAY_DAY = 5


def build(company, people, now) -> None:
    owner = people["owner"]
    today = queries.local_today(company, now)
    bank = MoneyAccount.objects.filter(company=company, kind=MoneyAccount.Kind.BANK).order_by(
        "order", "pk"
    )
    bank = bank.filter(currency=company.base_currency).first()
    if bank is None:
        return
    zone = ZoneInfo(company.timezone)

    def at(day: date, hour: int = 10) -> datetime:
        return datetime.combine(day, time(hour, 15), tzinfo=zone)

    year_start = today.replace(month=1, day=1)
    with moment(at(year_start)):
        partners.set_partners(
            company,
            by=owner,
            effective_on=year_start,
            rows=[
                {"membership": owner, "name": "", "share": "60"},
                {"membership": None, "name": INVESTOR, "share": "40"},
            ],
        )
    _last_quarters_dividend(company, owner, bank, today, at)
    _loan_plan(company, owner)
    draw_day = today - timedelta(days=3)
    if draw_day.month == today.month and _room(bank, draw_day, today) >= D("3500000"):
        with moment(at(draw_day, 18)):
            owner_draw.take(
                company,
                by=owner,
                account=bank,
                amount=D("3500000"),
                occurred_on=draw_day,
                description="Oilaviy xarajatlar uchun",
                confirmed=True,
            )
    with moment(at(today - timedelta(days=6), 11)):
        owner_draw.plan_purchase(
            company,
            by=owner,
            title="Yunusobod uchun ikkinchi farmatsevtik muzlatgich",
            amount=D("14500000"),
            due_on=today + timedelta(days=18),
        )
        owner_draw.plan_purchase(
            company,
            by=owner,
            title="Sergeli dorixonasi uchun kassa apparati",
            amount=D("4600000"),
            due_on=today + timedelta(days=45),
        )


def _last_quarters_dividend(company, owner, bank, today: date, at) -> None:
    """Last quarter's round, paid on the 20th of the month after it (when the books show it)."""
    first = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
    end = first - timedelta(days=1)
    start = date(end.year, 3 * ((end.month - 1) // 3) + 1, 1)
    paid_on = first.replace(day=20)
    if paid_on >= today:
        return
    profit = queries.totals(company, start, end, branch_ids=None)["profit"]
    amount = owner_draw.round_down(min(max(profit, D(0)) * D("0.5"), D("40000000")), "UZS")
    if amount <= 0:
        amount = D("20000000")
    # Never more than the bank held on any day since: the books stay above zero every day.
    amount = min(amount, owner_draw.round_down(_room(bank, paid_on, today) * D("0.8"), "UZS"))
    if amount <= 0:
        return
    with moment(at(first + timedelta(days=12))):
        dividend = partners.create_dividend(
            company,
            by=owner,
            period_start=start,
            period_end=end,
            amount=amount,
            note="Chorak yakuni bo‘yicha",
        )
    with moment(at(paid_on, 12)):
        partners.pay_dividend(dividend, by=owner, account=bank, paid_on=paid_on)


def _room(account: MoneyAccount, start: date, today: date) -> Decimal:
    """The lowest end-of-day balance from `start` to today: what a row dated `start` may take."""
    lowest = queries.balance(account)
    day = start
    while day < today:
        lowest = min(lowest, queries.balance(account, day))
        day += timedelta(days=1)
    return lowest


def _loan_plan(company, owner) -> None:
    """The ledger pays the bank loan 6.7 mln on the 5th: the same as its instalment plan."""
    loan = (
        Debt.objects.filter(
            company=company,
            kind=Debt.Kind.LOAN,
            direction=Debt.Direction.PAYABLE,
            status=Debt.Status.OPEN,
        )
        .order_by("pk")
        .first()
    )
    if loan is None or loan.installments.exists():
        return
    first = loan.issued_on.replace(day=PAY_DAY)
    if first <= loan.issued_on:
        first = owner_draw._add_months(first, 1)
    rows, left, step = [], loan.amount, 0
    while left > 0:
        part = min(LOAN_PAYMENT, left)
        rows.append((owner_draw._add_months(first, step), part))
        left -= part
        step += 1
    services.set_installments(loan, by=owner, rows=rows)
