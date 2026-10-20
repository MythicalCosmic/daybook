"""Demo data of sales and cash: six weeks of believable tills in Chilonzor and Yunusobod.

Everything goes through `apps.sales.services` (so the ledger, the audit log and the daily totals
are exactly what real use would leave), with the clock set to each moment as it happens, so
times in lists, timelines and the audit log read naturally. The last two days stay unverified
(they wait in Needs you), today's tills are open, one handover still waits for the owner and one
was declined last week; a couple of shortages, one disputed shift and one AI mismatch give the
screens something to show.
"""

import io
import random
from contextlib import contextmanager, suppress
from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from unittest import mock

from django.utils import timezone

from apps.companies.models import Feature
from apps.core.exceptions import DomainError
from apps.finance import defaults as finance_defaults
from apps.finance import services as finance
from apps.finance.models import Category, MoneyAccount
from apps.sales import defaults, rollup, services
from apps.sales.days import local
from apps.sales.models import CashShift, PaymentMethod, Register, SalesSettings
from apps.sales.services import PaymentLine

DAYS = 42
FONT = (
    Path(__file__).resolve().parent.parent
    / "core"
    / "pdf_assets"
    / "fonts"
    / "NotoSans-Regular.ttf"
)
BOLD = FONT.with_name("NotoSans-Bold.ttf")

# Share of a day's sales per payment method (system codes), roughly a Tashkent mini-market.
MIX = {
    "cash": 0.44,
    "uzcard": 0.19,
    "humo": 0.14,
    "click": 0.08,
    "payme": 0.07,
    "visa": 0.03,
    "uzum": 0.03,
    "transfer": 0.01,
    "credit": 0.01,
}
FEES = {
    "uzcard": "0.60",
    "humo": "0.50",
    "visa": "2.00",
    "click": "1.00",
    "payme": "1.00",
    "uzum": "1.00",
}
PAYOUTS = [
    ("Non uyi: non va somsa", "goods", 180_000, 420_000),
    ("Hydrolife suv, 20 l × 6", "goods", 90_000, 150_000),
    ("Taksi: tovar olib kelish", "transport", 35_000, 80_000),
    ("Kanselyariya va chek lentasi", "other_expense", 40_000, 95_000),
    ("Elektr ustasi: rozetka", "repairs", 120_000, 250_000),
    ("Tozalash vositalari", "other_expense", 60_000, 140_000),
    ("Yuk tashuvchi (Damas)", "transport", 70_000, 150_000),
]


@contextmanager
def at(moment: datetime):
    """Run with the clock at `moment`, so auto timestamps (rows, audit, notifications) read
    as if it happened then."""
    with mock.patch("django.utils.timezone.now", return_value=moment):
        yield


def seed(company, people, now) -> None:
    """Add demo rows to `company`. `people` maps owner, manager, worker, madina, jasur
    and nigora to their memberships."""
    if not company.has_feature(Feature.SALES):
        return
    rng = random.Random(911)
    now = now or timezone.now()
    finance_defaults.ensure(company)
    defaults.ensure(company)
    _configure(company)
    branches = list(company.branches.filter(is_active=True).order_by("order", "pk"))
    owner, manager = people["owner"], people["manager"]
    first = branches[0]
    second = branches[1] if len(branches) > 1 else None
    tills = {
        first.pk: Register.objects.filter(branch=first).order_by("pk").first(),
    }
    Register.objects.filter(pk=tills[first.pk].pk).update(fiscal_serial="UZ-FM 210045")
    if second is not None:
        tills[second.pk] = Register.objects.filter(branch=second).order_by("pk").first()
        Register.objects.filter(pk=tills[second.pk].pk).update(fiscal_serial="UZ-FM 210388")
    with suppress(DomainError):
        services.create_register(
            company, by=owner, branch=first, name="Kassa 2", fiscal_serial="UZ-FM 211907"
        )
    bank = _bank(company, owner)
    methods = {m.system_code: m for m in PaymentMethod.objects.filter(company=company)}

    local_now = local(company, now)
    today = local_now.date()
    plan = []  # (day, branch, cashier, base net)
    for back in range(DAYS, 0, -1):
        day = today - timedelta(days=back)
        weekend = day.weekday() >= 5
        plan.append(
            (
                day,
                first,
                people["madina"] if day.weekday() != 6 else manager,
                15_200_000 if not weekend else 19_800_000,
            )
        )
        if second is not None:
            cashier = people["jasur"] if day.toordinal() % 2 else people["nigora"]
            plan.append((day, second, cashier, 10_400_000 if not weekend else 13_900_000))

    shifts: list[CashShift] = []
    for day, branch, cashier, base in plan:
        back = (today - day).days
        shift = _history_shift(
            company,
            rng,
            day=day,
            branch=branch,
            register=tills[branch.pk],
            cashier=cashier,
            base=base,
            methods=methods,
            owner=owner,
            manager=manager,
            bank=bank,
            with_photos=back <= 10,
            story=_story(back, branch == first, cashier, people),
        )
        shifts.append(shift)
        if day.weekday() == 0:
            _bank_run(company, rng, day, branch, owner, bank)
        if back > 2:
            verifier = manager if branch == first and cashier != manager else owner
            story = _story(back, branch == first, cashier, people)
            moment = _moment(company, day + timedelta(days=1), time(9, 40 + rng.randint(0, 15)))
            with at(moment):
                if story == "dispute":
                    services.dispute_shift(
                        shift, by=owner, reason="Z-hisobot surati xira, kassani qayta sanang"
                    )
                elif story == "recount":
                    services.verify_shift(
                        shift,
                        by=verifier,
                        recount_cash=str(shift.counted_cash - 10_000),
                        note="Qayta sanaldi",
                    )
                else:
                    services.verify_shift(shift, by=verifier)

    _ai_mismatch(shifts, company)
    _today(company, rng, now, first, second, tills, people, methods)
    _extras(company, rng, now, first, second, people, methods)
    _targets(company, today, first, second, people)
    rollup.rebuild_range(company, today - timedelta(days=DAYS + 1), today)


def _configure(company) -> None:
    from apps.sales.conf import get_settings

    get_settings(company)
    SalesSettings.objects.filter(company=company).update(
        cash_tolerance=Decimal("5000"),
        big_payout_alert=Decimal("2000000"),
        handover_confirm_hours=2,
    )
    for code, fee in FEES.items():
        PaymentMethod.objects.filter(company=company, system_code=code).update(
            fee_percent=Decimal(fee)
        )


def _bank(company, owner) -> MoneyAccount:
    found = MoneyAccount.objects.filter(
        company=company, kind=MoneyAccount.Kind.BANK, is_active=True
    ).first()
    if found is not None:
        return found
    return finance.create_account(
        company, by=owner, kind=MoneyAccount.Kind.BANK, name="Kapitalbank, hisob raqam"
    )


def _moment(company, day, clock: time) -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.combine(day, clock, tzinfo=ZoneInfo(company.timezone))


def _story(back: int, chilonzor: bool, cashier, people) -> str:
    """Fixed events on fixed days back, so the demo always tells the same story."""
    if not chilonzor and back == 1:
        return "pending"
    if not chilonzor and back == 9:
        return "dispute"
    if chilonzor and back == 16:
        return "recount"
    if not chilonzor and back in (4, 13, 22):
        return "short"
    if chilonzor and back in (11, 27):
        return "small_short"
    if not chilonzor and back == 19:
        return "surplus"
    if not chilonzor and back == 6:
        return "declined"
    return "normal"


def _round(value: float, step: int = 1000) -> Decimal:
    return (Decimal(value) / step).quantize(Decimal(1), rounding=ROUND_HALF_UP) * step


def _lines(rng, methods, net_target: int) -> tuple[list[PaymentLine], Decimal]:
    lines, cash_net = [], Decimal(0)
    for code, share in MIX.items():
        method = methods.get(code)
        if method is None:
            continue
        sales = _round(net_target * share * rng.uniform(0.85, 1.15))
        if sales <= 0:
            continue
        refunds = _round(rng.choice([0, 0, 0, 0, 25_000, 48_000])) if code == "cash" else Decimal(0)
        lines.append(PaymentLine(method, sales, refunds, 0))
        if code == "cash":
            cash_net = sales - refunds
    return lines, cash_net


def _history_shift(
    company,
    rng,
    *,
    day,
    branch,
    register,
    cashier,
    base,
    methods,
    owner,
    manager,
    bank,
    with_photos,
    story,
):
    opens = branch.opens_at or time(9, 0)
    closes = branch.closes_at or time(21, 0)
    opened = _moment(company, day, time(opens.hour - 1, 50 + rng.randint(0, 9)))
    if story == "short" and rng.random() < 0.5:
        opened += timedelta(minutes=35)  # a late opening for the scorecard
    count, amount = _opening(register)
    with at(opened):
        shift = services.open_shift(
            by=cashier,
            register=register,
            opening_count=count,
            opening_float=str(amount),
            now=opened,
        )
    net_target = int(base * rng.uniform(0.82, 1.18))
    lines, cash_net = _lines(rng, methods, net_target)

    moves = Decimal(0)
    for _ in range(rng.choice([1, 1, 2, 2, 3])):
        reason, code, low, high = rng.choice(PAYOUTS)
        amount = _round(rng.uniform(low, high))
        moment = opened + timedelta(hours=rng.uniform(1.5, 9))
        with at(moment):
            services.record_movement(
                by=cashier,
                register=register,
                kind="payout",
                amount=amount,
                reason=reason,
                category=_category(company, code),
                photo=_receipt_photo(reason, amount) if with_photos else None,
                now=moment,
            )
        moves -= amount
    # Some days a midday drop into the safe; Fridays some change back from it; every evening
    # everything above tomorrow's float goes to the owner.
    if day.toordinal() % 3 == 0:
        drop = Decimal(2_000_000)
        with at(opened + timedelta(hours=6, minutes=10)):
            services.record_movement(
                by=cashier, register=register, kind="to_safe", amount=drop, reason="Seyfga"
            )
        moves -= drop
    if day.weekday() == 4 and _safe_balance(branch) >= 200_000:
        with at(opened + timedelta(hours=7)):
            services.record_movement(
                by=manager, register=register, kind="from_safe", amount=200_000, reason="Mayda pul"
            )
        moves += 200_000
    if day.weekday() == 5 and cash_net > 4_000_000:
        # Saturday cash collection straight from the till.
        with at(opened + timedelta(hours=8)):
            services.record_movement(
                by=manager,
                register=register,
                kind="to_bank",
                amount=3_000_000,
                to_account=bank,
                reason="Inkassatsiya",
            )
        moves -= 3_000_000
    closed_at = _moment(company, day, time(closes.hour, rng.randint(5, 35)))
    before_handover = shift.opening_float + cash_net + moves
    handover_amount = ((before_handover - 200_000) // 100_000) * 100_000
    receiver = owner if cashier != owner else manager
    if handover_amount > 0:
        with at(closed_at - timedelta(minutes=12)):
            handover = services.record_movement(
                by=cashier,
                register=register,
                kind="handover",
                amount=handover_amount,
                receiver=receiver,
                reason="Kunlik tushum",
            )
        with at(closed_at + timedelta(minutes=rng.randint(20, 90))):
            if story == "declined":
                services.decline_handover(handover, by=receiver, reason="Pul menga yetib kelmadi")
            elif story != "pending":  # yesterday's last handover still waits for the owner
                services.confirm_handover(handover, by=receiver)
        moves -= handover_amount
    expected = shift.opening_float + cash_net + moves
    difference = {
        "short": Decimal(-rng.choice([15_000, 25_000, 45_000])),
        "small_short": Decimal(-2_000),
        "surplus": Decimal(12_000),
        "dispute": Decimal(-120_000),
        "recount": Decimal(0),
    }.get(story, Decimal(0) if rng.random() < 0.85 else Decimal(-rng.choice([1_000, 3_000])))
    counted = expected + difference
    net = sum((line.sales - line.refunds for line in lines), Decimal(0))
    receipts = max(int(net / Decimal(rng.randint(78_000, 96_000))), 1)
    takes_cards = any(line.method.kind in ("card", "qr") for line in lines)
    with at(closed_at):
        shift = services.close_shift(
            shift,
            by=cashier,
            payments=lines,
            counted_cash=str(counted),
            closing_count=_count(counted),
            receipts=receipts,
            z_number=f"{412 + shift.number:04d}",
            fiscal_cash_total=str(cash_net),
            fiscal_card_total=str(net - cash_net),
            z_photo=_z_report(company, branch, register, shift, lines, receipts)
            if with_photos
            else _blank(),
            terminal_photo=(_terminal(lines) if with_photos else _blank()) if takes_cards else None,
            note="",
            now=closed_at,
        )
    return shift


FIRST_FLOAT = {"10000": 10, "5000": 10, "2000": 10, "1000": 30}  # 200 000 so'm in change


def _opening(register) -> tuple[dict, Decimal]:
    """The float a cashier counts: what the till holds (its first time, 200 000 in change)."""
    from apps.sales import cash

    held = cash.till_physical(register)
    if held <= 0:
        return dict(FIRST_FLOAT), Decimal(200_000)
    return _count(held), held


def _safe_balance(branch) -> Decimal:
    safe = MoneyAccount.objects.filter(branch=branch, kind=MoneyAccount.Kind.SAFE).first()
    return safe.balance if safe else Decimal(0)


def _bank_run(company, rng, day, branch, owner, bank) -> None:
    """Monday mornings the cash collected in the safe and with the owner goes to the bank."""
    moment = _moment(company, day, time(11, 15))
    safe = MoneyAccount.objects.filter(branch=branch, kind=MoneyAccount.Kind.SAFE).first()
    with at(moment):
        if safe is not None and safe.balance > 1_000_000:
            finance.transfer(
                company,
                by=owner,
                from_account=safe,
                to_account=bank,
                amount_out=safe.balance - 1_000_000,
                occurred_on=day,
                description="Inkassatsiya",
            )
        held = finance.account_for_holder(company, owner)
        held.refresh_from_db()
        if held.balance > 3_000_000:
            finance.transfer(
                company,
                by=owner,
                from_account=held,
                to_account=bank,
                amount_out=held.balance - 2_000_000,
                occurred_on=day,
                description="Kunlik tushum bankka",
            )


def _count(amount: Decimal) -> dict:
    """A plausible banknote breakdown of `amount` (multiples of 1 000 so'm)."""
    left = int(amount)
    count = {}
    for note in (200_000, 100_000, 50_000, 20_000, 10_000, 5_000, 2_000, 1_000):
        pieces, left = divmod(left, note)
        if pieces:
            count[str(note)] = pieces
    return count if left == 0 else {}


def _category(company, code: str) -> Category:
    return Category.objects.get(company=company, system_code=code)


def _ai_mismatch(shifts, company) -> None:
    recent = [shift for shift in shifts if shift.status == CashShift.Status.CLOSED]
    target = recent[-1] if recent else None
    for shift in shifts[-6:]:
        if shift.status == CashShift.Status.CLOSED and shift.branch.code == "YNS":
            target = shift
    if target is None:
        return
    card = sum((p.sales for p in target.payments.exclude(method__kind="cash")), Decimal(0))
    services.record_ai_reading(
        target,
        reading={
            "z_number": target.z_number,
            "cash_total": str(target.fiscal_cash_total),
            "card_total": str(card - 150_000),
            "confidence": "0.91",
            "notes": "Terminal cheki bo‘yicha karta jami 150 000 so‘m kamroq.",
        },
        mismatch=True,
    )


def _today(company, rng, now, first, second, tills, people, methods) -> None:
    """Today's open tills, during shop hours only (a demo seeded at night shows closed shops):
    Madina in Chilonzor with one payout, Jasur in Yunusobod."""
    at_local = local(company, now)
    if not 8 <= at_local.hour < 23:
        return
    earliest = at_local.replace(hour=8, minute=40, second=0, microsecond=0)
    opened = min(max(now - timedelta(hours=2, minutes=14), earliest), now - timedelta(minutes=10))
    with at(opened):
        count, amount = _opening(tills[first.pk])
        services.open_shift(
            by=people["madina"],
            register=tills[first.pk],
            opening_count=count,
            opening_float=str(amount),
            now=opened,
        )
    with at(max(opened + timedelta(minutes=5), now - timedelta(minutes=48))):
        services.record_movement(
            by=people["madina"],
            register=tills[first.pk],
            kind="payout",
            amount=120_000,
            reason="Non uyi: non va somsa",
            category=_category(company, "goods"),
            photo=_receipt_photo("Non uyi", 120_000),
        )
    if second is not None:
        opened = now - timedelta(hours=1, minutes=31)
        with at(opened):
            count, amount = _opening(tills[second.pk])
            services.open_shift(
                by=people["jasur"],
                register=tills[second.pk],
                opening_count=count,
                opening_float=str(amount),
                now=opened,
            )


def _extras(company, rng, now, first, second, people, methods) -> None:
    """A few receipts entered in the dashboard (wholesale orders), so the entries page has
    something real."""
    entries = [
        (3, first, [("transfer", 4_850_000)], "Ulgurji: «Oqtepa Lavash» Chilonzor filiali"),
        (8, first, [("cash", 1_250_000)], "Korporativ buyurtma: ofis uchun suv va choy"),
        (
            12,
            second or first,
            [("click", 640_000), ("cash", 210_000)],
            "Tug‘ilgan kun uchun oldindan buyurtma",
        ),
        (17, first, [("transfer", 2_300_000)], "Ulgurji: «Safia» kafe"),
        (25, second or first, [("payme", 380_000)], "Yetkazib berish buyurtmasi"),
    ]
    for back, branch, pays, note in entries:
        day = local(company, now).date() - timedelta(days=back)
        moment = _moment(company, day, time(rng.randint(11, 17), rng.randint(0, 59)))
        with at(moment):
            services.record_sale(
                by=people["manager"],
                payments=[(methods[code], amount) for code, amount in pays],
                branch=branch,
                source="dashboard",
                note=note,
                sold_at=moment,
                number=f"BUY-{1040 + back}",
            )


def _targets(company, today, first, second, people) -> None:
    month = today.replace(day=1)
    owner = people["owner"]
    services.set_target(company, by=owner, month=month, amount=Decimal("780000000"))
    services.set_target(company, by=owner, month=month, amount=Decimal("450000000"), branch=first)
    if second is not None:
        services.set_target(
            company, by=owner, month=month, amount=Decimal("320000000"), branch=second
        )
    services.set_target(
        company, by=owner, month=month, amount=Decimal("380000000"), membership=people["madina"]
    )
    previous = (month - timedelta(days=1)).replace(day=1)
    services.set_target(company, by=owner, month=previous, amount=Decimal("740000000"))


# Pictures ------------------------------------------------------------------------------------


def _font(size: int, bold: bool = False):
    from PIL import ImageFont

    try:
        return ImageFont.truetype(str(BOLD if bold else FONT), size)
    except OSError:
        return ImageFont.load_default()


def _paper(lines: list[tuple[str, str, bool]], *, width: int = 520, title: str = "") -> bytes:
    """A receipt-like picture: thermal paper, centred title, label/amount rows."""
    from PIL import Image, ImageDraw

    row = 30
    height = 120 + row * len(lines) + 60
    image = Image.new("RGB", (width, height), (252, 250, 245))
    draw = ImageDraw.Draw(image)
    y = 30
    if title:
        box = draw.textbbox((0, 0), title, font=_font(26, True))
        draw.text(
            ((width - (box[2] - box[0])) / 2, y), title, fill=(30, 30, 30), font=_font(26, True)
        )
        y += 50
    for label, value, strong in lines:
        font = _font(19, strong)
        if label == "---":
            draw.line((24, y + 12, width - 24, y + 12), fill=(160, 160, 160), width=1)
        else:
            draw.text((28, y), label, fill=(40, 40, 40), font=font)
            if value:
                box = draw.textbbox((0, 0), value, font=font)
                draw.text((width - 28 - (box[2] - box[0]), y), value, fill=(20, 20, 20), font=font)
        y += row
    for x in range(0, width, 14):  # torn edge
        draw.polygon([(x, height), (x + 7, height - 8), (x + 14, height)], fill=(235, 232, 225))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=88)
    return out.getvalue()


def _sum(value: Decimal) -> str:
    return f"{int(value):,}".replace(",", " ")


def _z_report(company, branch, register, shift, lines, receipts) -> bytes:
    rows = [
        (company.name.upper(), "", True),
        (f"{branch.name} · {register.name}", "", False),
        (f"FM: {register.fiscal_serial or 'UZ-FM 210045'}", "", False),
        ("---", "", False),
        (f"Z-HISOBOT № {412 + shift.number:04d}", "", True),
        (f"Sana: {shift.business_day:%d.%m.%Y}", "", False),
        ("---", "", False),
    ]
    for line in lines:
        rows.append((line.method.name, _sum(line.sales), False))
    total = sum((line.sales for line in lines), Decimal(0))
    refunds = sum((line.refunds for line in lines), Decimal(0))
    rows += [
        ("---", "", False),
        ("Qaytarishlar", _sum(refunds), False),
        ("Cheklar soni", str(receipts), False),
        ("JAMI", _sum(total - refunds), True),
        ("QQS 12%", _sum((total - refunds) * Decimal("0.1071")), False),
    ]
    return _paper(rows, title="Z-HISOBOT")


def _terminal(lines) -> bytes:
    cards = [line for line in lines if line.method.kind in ("card", "qr")]
    total = sum((line.sales for line in cards), Decimal(0))
    rows = [
        ("UZCARD · HUMO · VISA", "", True),
        ("Terminal ID: 90412233", "", False),
        ("---", "", False),
    ]
    rows += [(line.method.name, _sum(line.sales), False) for line in cards]
    rows += [
        ("---", "", False),
        ("YAKUNIY SVERKA", "", True),
        ("JAMI", _sum(total), True),
        ("Holati: MUVAFFAQIYATLI", "", False),
    ]
    return _paper(rows, width=440, title="SVERKA")


def _receipt_photo(reason: str, amount) -> bytes:
    rows = [
        (reason[:28], "", True),
        ("---", "", False),
        ("Summa", _sum(Decimal(amount)), True),
        ("Rahmat!", "", False),
    ]
    return _paper(rows, width=380, title="CHEK")


def _blank() -> bytes:
    """A small grey placeholder for older shifts (their photos don't matter in the demo)."""
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (64, 96), (236, 233, 226)).save(out, "JPEG", quality=70)
    return out.getvalue()
