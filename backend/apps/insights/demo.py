"""Demo data of insights: the story Demo Dorixona's owner reads in the cockpit (Egasi paneli).

The insights are not invented: the demo adds a few real rows through the finance services, then
runs the detection rules over everything the demos booked, so every number an insight shows is
the cockpit's own.

- Fuel: the courier's car carried fittings to the new Sergeli pharmacy this week, two big fuel
  bills at Chilonzor, several times a usual week (an expense spike).
- A prepayment to a distributor for the Sergeli pharmacy's opening stock, due on the 23rd,
  takes the cash under the owner's buffer of 150 mln that day, 40 mln short (the cash low).
- A bigger expense claim waits for approval beside the demos' requests (decisions waiting).
- Yunusobod's margin this month falls by itself in the sales and finance demos, and two
  customers and a distributor are late in theirs (the overdue insights).

`seed` adds the rows that are booked on past days; `finish` runs once every demo has booked its
own (the prepayment is sized on the cash they leave) and stores the insights.
"""

from datetime import date, time, timedelta
from decimal import Decimal

from apps.core import demo_plan, demo_time
from apps.core.exceptions import DomainError

BUFFER = Decimal("150000000")
SHORT = Decimal("40000000")
MILLION = Decimal(1_000_000)
FUEL = (
    (4, Decimal("1350000"), "Yoqilg‘i: Sergeli dorixonasiga jihoz tashish"),
    (2, Decimal("1200000"), "Yoqilg‘i: Yunusobod – Sergeli qatnovlari"),
)
DISTRIBUTOR = "Chinorbek Pharma Logistika"
PREPAYMENT = "Sergeli dorixonasi: boshlang‘ich zaxira, oldindan to‘lov"
CLAIM = (Decimal("1850000"), "Muzlatkich termometrlari va kalibrlash, Chilonzor")


def seed(company, people, now) -> None:
    """Demo Dorixona: the owner's buffer (Finance's one setting, "Mening pulim"), the fuel of
    the week and a claim waiting."""
    from apps.finance import conf as finance_conf

    if not company.has_feature("finance"):
        return
    money = finance_conf.get_settings(company)
    money.cash_buffer = BUFFER
    money.save(update_fields=["cash_buffer"])
    story = demo_plan.Plan(company, people, now)
    _fuel(company, people, story)
    _claim(company, people, story)


def finish(company, people, now) -> None:
    """Once every demo has booked its rows: the prepayment, then the insights."""
    from apps.insights import engine

    if company.has_feature("finance"):
        _prepayment(company, people, demo_plan.Plan(company, people, now))
    engine.run(company, now, notify=False)
    _seen(company, people, now)


def _account(company, amount: Decimal):
    """The business card when it holds enough, else the account with the most money."""
    from apps.finance.models import MoneyAccount

    accounts = list(
        MoneyAccount.objects.filter(
            company=company,
            is_active=True,
            currency=company.base_currency,
            kind__in=(MoneyAccount.Kind.CARD, MoneyAccount.Kind.BANK, MoneyAccount.Kind.CASH),
        ).order_by("-balance", "pk")
    )
    for account in accounts:
        if account.kind == MoneyAccount.Kind.CARD and account.balance >= amount:
            return account
    return accounts[0] if accounts and accounts[0].balance >= amount else None


def _fuel_category(company):
    from apps.finance.models import Category

    found = Category.objects.filter(
        company=company, kind=Category.Kind.EXPENSE, parent__system_code="transport"
    ).first()
    return found or Category.objects.filter(company=company, system_code="transport").first()


def _fuel(company, people, story) -> None:
    """Paid with the business card for the Sergeli opening: on no pharmacy's books."""
    from apps.finance import services

    category = _fuel_category(company)
    account = _account(company, sum((amount for _days, amount, _text in FUEL), Decimal(0)))
    if category is None or account is None:
        return
    for days, amount, text in FUEL:
        day = story.day(-days)
        at = story.at_work("manager", day, story.at(day, time(17, 30)))
        with demo_time.moment(at):
            services.record_transaction(
                company,
                by=people["owner"],
                kind="expense",
                amount=amount,
                occurred_on=day,
                account=account,
                category=category,
                description=text,
            )


def _claim(company, people, story) -> None:
    """Madina's thermometers for the fridges, waiting for the owner (above the limit)."""
    from apps.finance import claims
    from apps.finance.models import Category, Claim

    category = Category.objects.filter(
        company=company, kind=Category.Kind.EXPENSE, system_code="repairs"
    ).first()
    if category is None:
        return
    day = next(
        (
            story.day(-offset)
            for offset in (1, 2, 3, 4)
            if story.works("madina", story.day(-offset))
        ),
        story.day(-1),
    )
    at = story.at_work("madina", day, story.at(day, time(15, 10)))
    amount, text = CLAIM
    with demo_time.moment(at):
        try:
            claims.submit_claim(
                company,
                by=people["madina"],
                amount=amount,
                category=category,
                spent_on=day,
                paid_from=Claim.PaidFrom.OWN_MONEY,
                description=text,
                via=Claim.Via.MINIAPP,
            )
        except DomainError:
            return  # a module of the demo changed its rules: the story does without it


def target_day(today: date) -> date:
    """The 23rd ahead (this month's when it is at least two days off), within 29 days."""
    day = today.replace(day=23)
    if (day - today).days < 2:
        day = (today.replace(day=28) + timedelta(days=4)).replace(day=23)
    return min(day, today + timedelta(days=29))


def _prepayment(company, people, story) -> None:
    """A bill due on the 23rd, sized so that day ends 40 mln under the buffer."""
    from apps.finance import recurring, services
    from apps.finance.models import Category, Counterparty

    today = story.today
    day = target_day(today)
    balance = _balance_on(company, today, day)
    if balance is None:
        return
    amount = _rounded(balance - (BUFFER - SHORT))
    if amount < 10 * MILLION:
        return  # the demo's cash is already that low: nothing to add
    category = Category.objects.filter(company=company, system_code="goods").first()
    party = Counterparty.objects.filter(company=company, name=DISTRIBUTOR).first()
    if party is None:
        party = services.create_counterparty(
            company, by=people["owner"], name=DISTRIBUTOR, kind=Counterparty.Kind.SUPPLIER
        )
    if category is None:
        return
    with demo_time.moment(story.now - timedelta(days=3)):
        rule = recurring.create_rule(
            company,
            by=people["owner"],
            name=PREPAYMENT,
            kind=Category.Kind.EXPENSE,
            mode="bill",
            frequency="yearly",
            interval=1,
            day=day.day,
            category=category,
            counterparty=party,
            amount=amount,
            starts_on=day,
            ends_on=day,
            remind_days_before=5,
            payer=people["owner"],
        )
    # A planned category leaves the usual daily spending of the forecast: once more, exactly.
    after = _balance_on(company, today, day)
    if after is not None and after != BUFFER - SHORT:
        fixed = _rounded(amount + after - (BUFFER - SHORT))
        if fixed >= 10 * MILLION and fixed != amount:
            recurring.update_rule(rule, by=people["owner"], amount=fixed)


def _rounded(amount: Decimal) -> Decimal:
    return (amount / MILLION).quantize(Decimal(1)) * MILLION


def _balance_on(company, today: date, day: date) -> Decimal | None:
    from apps.finance import queries

    # The cockpit's 90-day forecast: shorter ones add the usual supplier payments earlier.
    forecast = queries.forecast(company, 90, branch_ids=None, today=today)
    return next(
        (
            Decimal(point["balance"])
            for point in forecast["points"]
            if point["date"] == day.isoformat()
        ),
        None,
    )


def _seen(company, people, now) -> None:
    """The owner already read about the late distributor bill yesterday evening."""
    from apps.insights import services
    from apps.insights.models import Insight

    insight = Insight.objects.filter(
        company=company, kind=Insight.Kind.OVERDUE_PAYABLES, status=Insight.Status.OPEN
    ).first()
    if insight is None:
        return
    with demo_time.moment(now - timedelta(hours=14)):
        services.acknowledge(insight, by=people["owner"])
