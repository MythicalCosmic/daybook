"""Demo sale lines (docs/PLAN-OWNER.md §14.7, §14.3), run from `demo.finish` once every demo has
seeded, so the stock demo's catalogue is there when it ran.

Demo Dorixona's sale lines come from its cash-register program through one import profile (a
file with a pharmacy column): 35 days of receipts whose totals match the tills' totals of each
pharmacy and day to the so‘m, so the day check reads 100 %. The weeks before yesterday arrive as
weekly files written in bulk; yesterday's file is read through the real import path the next
morning, with two prescription medicines sold above the legal price at Yunusobod (one
notification) and three item codes the catalogue doesn't know (the match list). The program's
cashier codes are linked to the pharmacists who ran the tills; one temporary code isn't.

The lines use the stock demo's medicines when it made them and a handful of this demo's own
(made once, by barcode, so the two demos never collide); prescription lines are priced at their
legal cap or below, except the two breaches. With the W2.a stock stub lines carry no batch and
no cost; with J1's stock the real path deducts them by FEFO.
"""

from __future__ import annotations

import io
import random
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from zoneinfo import ZoneInfo

from django.core.files.base import ContentFile
from django.utils import timezone

from apps.core.demo_time import moment
from apps.inventory import queries as stock_queries
from apps.inventory.models import Product
from apps.sales import lines
from apps.sales.models import (
    CashShift,
    DailySales,
    PosCashier,
    Sale,
    SaleLine,
    SalesImport,
    SalesImportProfile,
    SalesSettings,
)

DAYS = 35
PROFILE = "Kassa dasturi"
HEADERS = [
    "Chek",
    "Sana va vaqt",
    "Dorixona",
    "Kassa",
    "Kassir",
    "Shtrix kod",
    "Nomi",
    "Soni",
    "Birlik",
    "Narx",
    "Summa",
    "To‘lov",
    "Seriya",
    "Retsept",
]
COLUMNS = {
    "receipt": "Chek",
    "sold_at": "Sana va vaqt",
    "branch": "Dorixona",
    "register": "Kassa",
    "cashier": "Kassir",
    "code": "Shtrix kod",
    "name": "Nomi",
    "quantity": "Soni",
    "unit": "Birlik",
    "price": "Narx",
    "total": "Summa",
    "payment": "To‘lov",
    "series": "Seriya",
    "rx_number": "Retsept",
}
# This demo's own medicines (barcode, name, INN, kind, form, parts per pack, Rx, reference price,
# price a pack). Invented barcodes in Uzbekistan's 478 range.
OWN = [
    (
        "4780000101017",
        "Paratsetamol 500 mg tabletka №20",
        "paracetamol",
        "medicine",
        "tablet",
        2,
        False,
        None,
        4500,
    ),
    (
        "4780000101024",
        "Ibuprofen 200 mg tabletka №50",
        "ibuprofen",
        "medicine",
        "tablet",
        5,
        False,
        None,
        12000,
    ),
    (
        "4780000101031",
        "Amoksitsillin 500 mg kapsula №16",
        "amoxicillin",
        "medicine",
        "capsule",
        2,
        True,
        32000,
        31500,
    ),
    (
        "4780000101048",
        "Azitromitsin 500 mg tabletka №3",
        "azithromycin",
        "medicine",
        "tablet",
        1,
        True,
        38500,
        37900,
    ),
    (
        "4780000101055",
        "Metformin 850 mg tabletka №60",
        "metformin",
        "medicine",
        "tablet",
        6,
        True,
        27000,
        26400,
    ),
    (
        "4780000101062",
        "Amlodipin 5 mg tabletka №30",
        "amlodipine",
        "medicine",
        "tablet",
        3,
        True,
        18500,
        18000,
    ),
    (
        "4780000101079",
        "Pantoprazol 40 mg tabletka №28",
        "pantoprazole",
        "medicine",
        "tablet",
        2,
        True,
        46000,
        45000,
    ),
    (
        "4780000101086",
        "Siprofloksatsin 500 mg tabletka №10",
        "ciprofloxacin",
        "medicine",
        "tablet",
        1,
        True,
        21000,
        20500,
    ),
    (
        "4780000101093",
        "Askorbin kislotasi 500 mg tabletka №30",
        "ascorbic acid",
        "supplement",
        "tablet",
        1,
        False,
        None,
        9800,
    ),
    (
        "4780000101109",
        "Xlorgeksidin 0,05 % 100 ml eritma",
        "chlorhexidine",
        "medicine",
        "solution",
        1,
        False,
        None,
        6500,
    ),
    ("4780000101116", "Tibbiy niqob №50", "", "device", "", 1, False, None, 25000),
    (
        "4780000101123",
        "Vitamin D3 1000 XB tabletka №60",
        "colecalciferol",
        "supplement",
        "tablet",
        1,
        False,
        None,
        68000,
    ),
]
# Codes the catalogue doesn't know: yesterday's match list.
UNKNOWN = [
    ("4780000199011", "Loratadin 10 mg tabletka №10", 7900),
    ("4780000199028", "Omeprazol 20 mg kapsula №30", 14500),
    ("4780000199035", "Bint steril 7 m × 14 sm", 5200),
]
# Prescription medicines sold above their cap yesterday at Yunusobod: (barcode, price a pack).
BREACHES = [("4780000101031", Decimal("34500")), ("4780000101048", Decimal("41000"))]
PAYMENTS = [
    ("Naqd", 0.40),
    ("Uzcard", 0.20),
    ("Humo", 0.15),
    ("Click", 0.12),
    ("Payme", 0.09),
    ("Uzum", 0.04),
]
AVERAGE = (48_000, 62_000)  # a receipt, so‘m
LINES = ([1, 2, 3], [0.5, 0.3, 0.2])  # lines a receipt (1.7 on average)


def seed_lines(company, people, now: datetime) -> None:
    pairs = _tills(company, now)
    if not pairs:
        return
    SalesSettings.objects.filter(company=company).update(
        sales_lines=SalesSettings.Lines.IMPORT, sales_lines_confirmed_at=now - timedelta(days=40)
    )
    rng = random.Random(914)
    catalogue = _catalogue(company)
    owner = people["owner"]
    profile, _created = SalesImportProfile.objects.get_or_create(
        company=company,
        name=PROFILE,
        defaults={
            "file_kind": SalesImportProfile.FileKind.CSV,
            "delimiter": ";",
            "columns": COLUMNS,
            "date_format": "%d.%m.%Y %H:%M",
            "default_unit": SalesImportProfile.Unit.PACK,
            "branch": None,
            "created_by": people["manager"],
        },
    )
    cashiers = _cashiers(company, pairs)
    zone = ZoneInfo(company.timezone)
    yesterday = max(day for _branch, day in pairs)
    weeks: dict[date, list] = defaultdict(list)
    for branch, day in pairs:
        if day != yesterday:
            weeks[day - timedelta(days=day.weekday())].append((branch, day))
    for monday, week in sorted(weeks.items()):
        _bulk_week(company, profile, week, monday, catalogue, cashiers, rng, zone, owner)
    _yesterday(
        company,
        profile,
        [p for p in pairs if p[1] == yesterday],
        catalogue,
        cashiers,
        rng,
        zone,
        people,
        now,
    )


def _tills(company, now: datetime) -> list:
    """(branch, business day) of the last 35 days with the tills' totals, yesterday last."""
    from apps.sales.days import business_day

    today = business_day(company, now)
    rows = (
        DailySales.objects.filter(
            company=company, day__gte=today - timedelta(days=DAYS), day__lt=today, net__gt=0
        )
        .select_related("branch")
        .order_by("day", "branch__order")
    )
    return [(row.branch, row.day) for row in rows]


def _catalogue(company) -> list[dict]:
    """What the lines sell: this demo's medicines and the stock demo's (when it made them), each
    priced at its legal cap or below."""
    own = []
    for barcode, name, inn, kind, form, parts, rx, reference, price in OWN:
        product, _created = Product.objects.get_or_create(
            company=company,
            barcode=barcode,
            defaults={
                "name": name,
                "inn": inn,
                "kind": kind,
                "dosage_form": form,
                "units_per_pack": parts,
                "part_label": "blister" if parts > 1 else "",
                "rx_required": rx,
                "reference_price": Decimal(reference) if reference else None,
                "sale_price": Decimal(price),
            },
        )
        own.append(product.pk)
    others = list(
        Product.objects.for_company(company)
        .filter(is_active=True, sale_price__gt=0)
        .exclude(barcode="")
        .exclude(pk__in=own)
        .order_by("pk")[:80]
    )
    found = []
    for product in [*Product.objects.filter(pk__in=own).order_by("pk"), *others]:
        price = product.sale_price
        cap = stock_queries.price_cap(product)
        if cap is not None and price > cap:
            price = cap
        found.append({"product": product, "price": price, "cap": cap})
    return found


def _cashiers(company, pairs) -> dict:
    """The program's cashier code of whoever ran each pharmacy's till that day."""
    codes: dict[int, PosCashier] = {}
    by_day: dict[tuple, list] = defaultdict(list)
    shifts = (
        CashShift.objects.filter(company=company, business_day__in={day for _b, day in pairs})
        .exclude(status=CashShift.Status.OPEN)
        .select_related("cashier")
        .order_by("opened_at")
    )
    for shift in shifts:
        if shift.cashier_id not in codes:
            codes[shift.cashier_id], _created = PosCashier.objects.get_or_create(
                company=company,
                code=f"K{len(codes) + 1:02d}",
                defaults={"membership": shift.cashier},
            )
        by_day[(shift.branch_id, shift.business_day)].append(codes[shift.cashier_id])
    temp, _created = PosCashier.objects.get_or_create(company=company, code="Kassir 9")
    return {"by_day": by_day, "temp": temp}


def _receipts(rng, catalogue, net: Decimal, *, fixed: list | None = None) -> list[list[dict]]:
    """Receipts whose lines add up to `net` exactly: one to three lines each, a pack or a
    blister, the last line making up the difference with a medicine that has no cap."""
    plan: list[list[dict]] = [[line] for line in fixed or []]
    left = net - sum((line["total"] for line in fixed or []), Decimal(0))
    free = [item for item in catalogue if item["cap"] is None]
    while left > 0:
        size = rng.choices(*LINES)[0]
        receipt = []
        for _ in range(size):
            item = rng.choice(catalogue)
            product = item["product"]
            parts = int(product.units_per_pack or 1)
            if parts > 1 and rng.random() < 0.25:
                # A blister: the pack price over its parts, up to the next 100 so‘m (down when
                # that would put a prescription part above its own cap).
                unit, quantity = "part", 1
                price = (item["price"] / parts / 100).to_integral_value(ROUND_CEILING) * 100
                if item["cap"] is not None and price * parts > item["cap"]:
                    price = (item["cap"] / parts / 100).to_integral_value(ROUND_FLOOR) * 100
            else:
                unit, quantity, price = "pack", (2 if rng.random() < 0.12 else 1), item["price"]
            total = price * quantity
            if total >= left:
                break
            receipt.append(_line(product, unit, quantity, price, total))
            left -= total
        if (not receipt or left < Decimal(AVERAGE[0])) and left > 0:
            # The last receipt of the day makes up the difference to the so‘m.
            item = rng.choice(free)
            receipt.append(_line(item["product"], "pack", 1, left, left))
            left = Decimal(0)
        if receipt:
            plan.append(receipt)
    rng.shuffle(plan)
    return plan


def _line(product, unit, quantity, price, total, *, code=None, name=None) -> dict:
    return {
        "product": product,
        "code": code or product.barcode,
        "name": name or product.name,
        "unit": unit,
        "quantity": quantity,
        "price": Decimal(price),
        "total": Decimal(total),
    }


def _times(rng, branch, day: date, count: int, zone) -> list[datetime]:
    """When the receipts were sold: within Chilonzor's hours; around the clock at a 24-hour
    pharmacy, a fifth of them at night (until 04:00, still the same business day)."""
    found = []
    for _ in range(count):
        if branch.open_24h:
            minutes = (
                rng.randint(20 * 60, 28 * 60 - 1)
                if rng.random() < 0.2
                else rng.randint(8 * 60, 20 * 60 - 1)
            )
        else:
            opens = branch.opens_at or time(8, 0)
            closes = branch.closes_at or time(22, 0)
            minutes = rng.randint(
                opens.hour * 60 + opens.minute, closes.hour * 60 + closes.minute - 1
            )
        found.append(datetime.combine(day, time(0, 0), tzinfo=zone) + timedelta(minutes=minutes))
    return sorted(found)


def _payment(rng) -> str:
    return rng.choices([name for name, _share in PAYMENTS], [share for _n, share in PAYMENTS])[0]


def _bulk_week(company, profile, week, monday, catalogue, cashiers, rng, zone, owner) -> None:
    """One week's file, written in bulk (the real path costs a query a line)."""
    last = max(day for _b, day in week)
    imp = SalesImport.objects.create(
        company=company,
        profile=profile,
        status=SalesImport.Status.READY,
        created_by=owner,
        file=ContentFile(b"", name="demo.csv"),
    )
    sales, plans = [], []
    for branch, day in week:
        net = DailySales.objects.get(branch=branch, day=day).net
        plan = _receipts(rng, catalogue, net)
        moments = _times(rng, branch, day, len(plan), zone)
        people = cashiers["by_day"].get((branch.pk, day)) or [cashiers["temp"]]
        for number, (receipt, sold_at) in enumerate(zip(plan, moments, strict=True), start=1):
            pos = people[min(len(people) - 1, int(len(people) * (sold_at.hour >= 15)))]
            sales.append(
                Sale(
                    company=company,
                    branch=branch,
                    sold_at=sold_at,
                    business_day=day,
                    kind=Sale.Kind.SALE,
                    number=str(number),
                    total=sum((line["total"] for line in receipt), Decimal(0)),
                    source=Sale.Source.IMPORT,
                    external_id=lines.external_id(
                        profile.pk, lines.register_key(profile, branch.pk, "1"), day, str(number)
                    ),
                    sales_import=imp,
                    pos_cashier=pos,
                    cashier=pos.membership,
                    payment_label=_payment(rng),
                )
            )
            plans.append(receipt)
    Sale.objects.bulk_create(sales, batch_size=2000)
    rows = []
    for sale, receipt in zip(sales, plans, strict=True):
        for number, line in enumerate(receipt, start=1):
            rows.append(_row(sale, number, line))
    SaleLine.objects.bulk_create(rows, batch_size=4000)
    pairs = [(branch.pk, day) for branch, day in week]
    created = datetime.combine(last + timedelta(days=1), time(9, 10), tzinfo=zone)
    SalesImport.objects.filter(pk=imp.pk).update(
        rows=len(rows),
        lines=len(rows),
        receipts=len(sales),
        matched=len(rows),
        first_day=min(day for _b, day in week),
        last_day=last,
        day_check=lines.day_check(company, pairs),
        created_at=created,
        started_at=created,
        finished_at=created + timedelta(seconds=40),
    )


def _row(sale: Sale, number: int, line: dict) -> SaleLine:
    product = line["product"]
    parts = max(int(product.units_per_pack or 1), 1)
    quantity = Decimal(line["quantity"]) * (parts if line["unit"] == "pack" else 1)
    cap = stock_queries.price_cap(product) if product.rx_required else None
    return SaleLine(
        sale=sale,
        line_number=number,
        status=SaleLine.Status.MATCHED,
        product=product,
        code=line["code"],
        name=line["name"],
        unit=line["unit"],
        quantity=quantity,
        parts_per_pack=parts,
        price=line["price"],
        total=line["total"],
        cap=cap,
        over_cap=False,
    )


def _yesterday(company, profile, pairs, catalogue, cashiers, rng, zone, people, now) -> None:
    """Yesterday's file, read through the real import path at 08:40 this morning."""
    rows = []
    breaches_at = max(pairs, key=lambda pair: pair[0].open_24h)[0]
    products = {item["product"].barcode: item["product"] for item in catalogue}
    for branch, day in pairs:
        fixed = []
        if branch == breaches_at:
            for barcode, price in BREACHES:
                fixed.append(_line(products[barcode], "pack", 1, price, price))
        for code, name, price in UNKNOWN:
            if branch == breaches_at or code == UNKNOWN[0][0]:
                fixed.append(_line(None, "pack", 1, price, price, code=code, name=name))
        net = DailySales.objects.get(branch=branch, day=day).net
        plan = _receipts(rng, catalogue, net, fixed=fixed)
        moments = _times(rng, branch, day, len(plan), zone)
        people_ = cashiers["by_day"].get((branch.pk, day)) or [cashiers["temp"]]
        for number, (receipt, sold_at) in enumerate(zip(plan, moments, strict=True), start=1):
            pos = people_[min(len(people_) - 1, int(len(people_) * (sold_at.hour >= 15)))]
            if number % 37 == 0:
                pos = cashiers["temp"]
            payment = _payment(rng)
            for line in receipt:
                rx = ""
                product = line["product"]
                if product is not None and product.rx_required and rng.random() < 0.5:
                    rx = f"R-{rng.randint(10000, 99999)}"
                rows.append(
                    [
                        str(number),
                        timezone.localtime(sold_at, zone).strftime("%d.%m.%Y %H:%M"),
                        branch.name,
                        "1",
                        pos.code,
                        line["code"],
                        line["name"],
                        str(line["quantity"]),
                        "блистер" if line["unit"] == "part" else "уп",
                        str(line["price"]),
                        str(line["total"]),
                        payment,
                        "",
                        rx,
                    ]
                )
    buffer = io.StringIO()
    buffer.write(";".join(HEADERS) + "\n")
    for row in rows:
        buffer.write(";".join(value.replace(";", ",") for value in row) + "\n")
    data = buffer.getvalue().encode("utf-8")
    read_at = datetime.combine(now.astimezone(zone).date(), time(8, 40), tzinfo=zone)
    if read_at > now:
        read_at = now - timedelta(minutes=30)
    with moment(read_at):
        imp = SalesImport(company=company, profile=profile, created_by=people["manager"])
        imp.file.save("demo.csv", ContentFile(data), save=False)
        imp.save()
    with moment(read_at + timedelta(seconds=30)):
        lines.process(imp.pk)
