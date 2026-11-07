"""Demo nasiya and invoices (docs/PLAN-OWNER.md §14.3, §14.7).

Demo Dorixona: three regulars who take nasiya (one with a limit, one paid part of it back by
card) and one clinic, their receivables of the last weeks (one overdue), and one credit sale on
a till open now, so the close shows its Nasiya line. Demo Distribyutor (when its sales module is
on): invoices to invented pharmacies and clinics: a draft, an issued one partly paid, one
overdue, one paid and one voided. Invented names only.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from apps.core.demo_time import moment
from apps.finance import services as finance
from apps.finance.models import Counterparty, MoneyAccount
from apps.finance.sources import Source
from apps.inventory.models import Product
from apps.sales import services
from apps.sales.models import CashShift, CreditEntry, PaymentMethod

REGULARS = [
    # name, phone, kind, credit limit
    ("Saida Rahimova", "+998901112233", "person", Decimal("500000")),
    ("Botir aka Yusupov", "+998935554411", "person", None),
    ("Malika Hasanova", "+998977001122", "person", None),
    ("Shifobaxsh oilaviy poliklinikasi", "+998712005060", "clinic", Decimal("5000000")),
]
# (customer index, days ago, amount, note)
CREDIT = [
    (0, 24, "185000", "Bosim dorilari, oylikdan keyin"),
    (0, 6, "64000", ""),
    (1, 41, "120000", "Antibiotik kursi"),
    (2, 3, "48500", ""),
    (3, 18, "1450000", "Muolaja xonasi uchun"),
    (3, 9, "860000", "Bog‘lov materiallari"),
]
CUSTOMERS_SMALL = [
    ("Oydin dorixonasi", "+998712301010", "pharmacy"),
    ("Sog‘lom Hayot klinikasi", "+998712302020", "clinic"),
    ("Navro‘z Farm MCHJ", "+998712303030", "company"),
]
ITEMS_SMALL = [
    # barcode, name, parts per pack, Rx, reference, price a pack
    ("4780000201014", "Paratsetamol 500 mg tabletka №20", 2, False, None, Decimal("3900")),
    (
        "4780000201021",
        "Amoksitsillin 500 mg kapsula №16",
        2,
        True,
        Decimal("32000"),
        Decimal("27500"),
    ),
    (
        "4780000201038",
        "Natriy xlorid 0,9 % 200 ml eritma",
        1,
        True,
        Decimal("9500"),
        Decimal("8200"),
    ),
]


def _open_day(company, day):
    """`day`, or the first day after the finance demo's closed period: a demo row dated in
    closed books would be refused (the period lock moves with the seed day)."""
    from apps.finance import conf as finance_conf

    locked = finance_conf.get_settings(company).locked_until
    return locked + timedelta(days=1) if locked is not None and day <= locked else day


def seed_credit(company, people, now: datetime) -> None:
    """Demo Dorixona's nasiya: written as of their days (as a manager records them from a
    customer's card), and one credit sale on a till open now through the till's own path."""
    zone = ZoneInfo(company.timezone)
    manager = people["manager"]
    branch = manager.home_branch or company.branches.order_by("pk").first()
    customers = []
    for name, phone, kind, limit in REGULARS:
        party = Counterparty.objects.filter(company=company, phone=phone).first()
        if party is None:
            party = services.create_customer(
                company, by=people["owner"], name=name, phone=phone, kind=kind, credit_limit=limit
            )
        customers.append(party)
    terms = services.get_settings(company).credit_days
    for index, days_ago, amount, note in CREDIT:
        day = _open_day(company, now.astimezone(zone).date() - timedelta(days=days_ago))
        at = datetime.combine(day, time(17, 20), tzinfo=zone)
        if CreditEntry.objects.filter(
            company=company, customer=customers[index], business_day=day
        ).exists():
            continue
        with moment(at):
            entry = CreditEntry.objects.create(
                company=company,
                kind=CreditEntry.Kind.SALE,
                customer=customers[index],
                branch=branch,
                amount=Decimal(amount),
                business_day=day,
                note=note,
                created_by=manager,
            )
            entry.debt = finance.open_debt(
                company,
                by=manager,
                direction="receivable",
                kind="trade",
                amount=entry.amount,
                currency=company.base_currency,
                issued_on=day,
                counterparty=entry.customer,
                due_on=day + timedelta(days=terms),
                category="sales",
                branch=branch,
                description=note or "Nasiya",
                responsible=manager,
                source=Source("sales.creditentry", entry.pk),
            )
            entry.save(update_fields=["debt"])
    # Saida paid part of hers back by card last week.
    card = (
        PaymentMethod.objects.filter(company=company, kind=PaymentMethod.Kind.CARD)
        .order_by("order")
        .first()
    )
    saida = customers[0]
    if (
        card is not None
        and not CreditEntry.objects.filter(company=company, customer=saida, kind="payment").exists()
    ):
        day = _open_day(company, now.astimezone(zone).date() - timedelta(days=5))
        account = card.account or finance.account_for_branch(
            branch, kind="clearing", currency=company.base_currency
        )
        with moment(datetime.combine(day, time(11, 5), tzinfo=zone)):
            entry = CreditEntry.objects.create(
                company=company,
                kind=CreditEntry.Kind.PAYMENT,
                customer=saida,
                branch=branch,
                method=card,
                amount=Decimal("100000"),
                business_day=day,
                created_by=manager,
            )
            debt = services.open_receivables(saida, currency=company.base_currency).first()
            if debt is not None:
                finance.pay_debt(
                    debt,
                    by=manager,
                    amount=entry.amount,
                    paid_on=day,
                    account=account,
                    source=Source("sales.creditentry", entry.pk, f"d{debt.pk}"),
                )
    # A credit sale on a till open now, through the till's own path.
    shift = (
        CashShift.objects.filter(company=company, status=CashShift.Status.OPEN)
        .select_related("cashier")
        .order_by("opened_at")
        .first()
    )
    if shift is not None and not CreditEntry.objects.filter(shift=shift).exists():
        with moment(now - timedelta(minutes=40)):
            services.record_credit(
                by=shift.cashier, kind="sale", customer=customers[2], amount="36500", note=""
            )


def seed_invoices(company, people, now: datetime) -> None:
    """Demo Distribyutor's invoices, from its warehouse."""
    zone = ZoneInfo(company.timezone)
    owner = people["owner"]
    branch = company.branches.filter(is_active=True).order_by("pk").first()
    products = []
    for barcode, name, parts, rx, reference, price in ITEMS_SMALL:
        product, _created = Product.objects.get_or_create(
            company=company,
            barcode=barcode,
            defaults={
                "name": name,
                "units_per_pack": parts,
                "rx_required": rx,
                "reference_price": reference,
                "sale_price": price,
            },
        )
        products.append(product)
    customers = []
    for name, phone, kind in CUSTOMERS_SMALL:
        party = Counterparty.objects.filter(
            company=company, phone=phone
        ).first() or services.create_customer(company, by=owner, name=name, phone=phone, kind=kind)
        customers.append(party)
    if company.invoices.exists():
        return
    bank = (
        MoneyAccount.objects.filter(company=company, kind=MoneyAccount.Kind.BANK, is_active=True)
        .filter(currency=company.base_currency)
        .order_by("pk")
        .first()
    )
    plans = [
        # customer, days ago, lines (product index, packs, price), what happens
        (0, 32, [(0, 200, "3900"), (1, 40, "27500")], "overdue"),
        (1, 5, [(1, 60, "27500"), (2, 120, "8200")], "partly"),
        (2, 20, [(0, 100, "3800")], "paid"),
        (0, 4, [(2, 50, "8200")], "void"),
        (1, 0, [(1, 20, "27500")], "draft"),
    ]
    for customer, days_ago, items, story in plans:
        day = _open_day(company, now.astimezone(zone).date() - timedelta(days=days_ago))
        at = datetime.combine(day, time(10, 30), tzinfo=zone)
        with moment(at):
            invoice = services.create_invoice(
                company,
                by=owner,
                counterparty=customers[customer],
                lines=[
                    {"product_id": products[index].pk, "quantity": packs, "price": price}
                    for index, packs, price in items
                ],
                branch=branch,
                currency=company.base_currency,
            )
            if story == "draft":
                continue
            invoice = services.issue_invoice(invoice, by=owner, issued_on=day)
            if story == "void":
                services.void_invoice(invoice, by=owner, reason="Buyurtma bekor qilindi")
                continue
        if story in ("partly", "paid") and bank is not None:
            paid_on = day + timedelta(days=3 if story == "partly" else 7)
            amount = (
                invoice.total if story == "paid" else (invoice.total / 2).quantize(Decimal("1"))
            )
            with moment(datetime.combine(paid_on, time(15, 0), tzinfo=zone)):
                services.record_invoice_payment(
                    invoice, by=owner, account=bank, amount=amount, paid_on=paid_on
                )
