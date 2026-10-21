"""Demo data of sales and cash (docs/PLAN-OWNER.md §14.3, apps/core/demo_plan.py): two months
of Demo Dorixona's tills, the last three weeks in full.

Chilonzor's till runs one session a day: the pharmacist who opens at 08:00 opens it and the one
who closes at 22:00 closes it. Yunusobod is open around the clock, so its till has a day session
(08:00 to 20:00) and a night session (20:00 to 08:00), each run by the pharmacist on that shift.
Chilonzor sells about 6 mln so‘m a day, Yunusobod about 12 mln (a fifth of it at night), with an
average receipt of about 55 000 so‘m: 40 % cash, 35 % Uzcard and Humo, 25 % Click, Payme and
Uzum. Medicines sold aren't taken back, so there are no refunds.

Everything goes through `apps.sales.services` (so the ledger, the audit log and the daily totals
are exactly what real use would leave), with the clock set to each moment as it happens
(`demo_time.moment`), so times in lists, timelines, alerts and the audit log read naturally. The
last two days stay unverified (they wait in Needs you), the tills of the shifts under way are
open, the evening takings go to the owner (on Mondays to the bank's cash collector), one handover
still waits for the owner and one was declined; a couple of shortages, one disputed shift and
one mismatch found by the assistant give the screens something to show.

The weeks before come in as imported shifts (`CashShift.Source.IMPORT`, as when a pharmacy
loads its earlier Z-reports): one per session from the same roster, with exactly the day's sales
the ledger's demo booked for that pharmacy (its cash, and its cards and QR payments split over
the methods) and the evenings' cash taken to the safe linked to the ledger's transfers, so the
sales pages compare a month with the one before and every figure matches the books. They are
written in bulk, with no ledger rows of their own (the ledger already holds those days): the
real path costs half a second a shift.
"""

import io
import random
from collections import defaultdict
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from unittest import mock

from django.db.models import DateTimeField, ExpressionWrapper, F, OuterRef, Subquery

from apps.companies.models import Feature
from apps.core import demo_plan
from apps.core.demo_time import moment
from apps.finance import defaults as finance_defaults
from apps.finance import queries as finance_queries
from apps.finance import services as finance
from apps.finance.demo import DEMO_SOURCE
from apps.finance.models import Category, MoneyAccount, Transaction, Transfer
from apps.members.models import AccessRole, Membership
from apps.members.permissions import Perm
from apps.sales import alerts, defaults, rollup, services
from apps.sales.models import (
    CashMovement,
    CashShift,
    PaymentMethod,
    Register,
    SalesSettings,
    ShiftPayment,
)
from apps.sales.services import PaymentLine

DAYS = demo_plan.SALES_DAYS
FONT = (
    Path(__file__).resolve().parent.parent
    / "core"
    / "pdf_assets"
    / "fonts"
    / "NotoSans-Regular.ttf"
)
BOLD = FONT.with_name("NotoSans-Bold.ttf")

# Share of a session's sales per payment method (system codes).
MIX = {"cash": 0.40, "uzcard": 0.20, "humo": 0.15, "click": 0.12, "payme": 0.09, "uzum": 0.04}
FEES = {"uzcard": "0.60", "humo": "0.50", "click": "1.00", "payme": "1.00", "uzum": "1.00"}
# Expected sales of a session (so‘m): Chilonzor's day, Yunusobod's day and night.
SESSION_SALES = {("C", False): 6_000_000, ("Y", False): 9_600_000, ("Y", True): 2_400_000}
NIGHT_SHARE = 0.2  # of a Yunusobod day's sales, in the imported weeks
AVERAGE_RECEIPT = (48_000, 62_000)
PAYOUTS = [
    ("Ichimlik suvi, 19 l × 2", "other_expense", 40_000, 60_000),
    ("Taksi: distribyutordan shoshilinch dori olib kelish", "transport", 35_000, 70_000),
    ("Kanselyariya va chek lentasi", "other_expense", 40_000, 95_000),
    ("Elektr ustasi: rozetka", "repairs", 120_000, 220_000),
    ("Dezinfeksiya vositalari", "other_expense", 60_000, 140_000),
]
FIRST_FLOAT = {"10000": 10, "5000": 10, "2000": 10, "1000": 30}  # 200 000 so‘m in change
KEEP = Decimal(300_000)  # the change a till keeps for the next session
ROUTINE_ALERTS = (
    "shift_closed",
    "shift_verified",
    "float_difference",
    "handover_sent",
    "handover_answered",
    "big_payout",
)


@dataclass
class Session:
    code: str  # branch code
    day: object
    night: bool
    opener: Membership
    closer: Membership
    opens: datetime
    closes: datetime


def seed(company, people, now) -> None:
    """Add demo rows to `company`. `people` maps owner, manager, worker, madina, jasur
    and nigora to their memberships."""
    if not company.has_feature(Feature.SALES):
        return
    story = demo_plan.Plan(company, people, now)
    rng = random.Random(911)
    finance_defaults.ensure(company)
    defaults.ensure(company)
    _configure(company)
    owner = people["owner"]
    tills = {}
    for code, serial in (("C", "UZ-FM 210045"), ("Y", "UZ-FM 210388")):
        branch = story.branches[code]
        register = Register.objects.filter(branch=branch).order_by("pk").first()
        if register is None:
            register = services.create_register(company, by=owner, branch=branch, name="Kassa 1")
        Register.objects.filter(pk=register.pk).update(fiscal_serial=serial)
        register.fiscal_serial = serial
        tills[code] = register
    bank = _bank(company, owner)
    methods = {m.system_code: m for m in PaymentMethod.objects.filter(company=company)}
    sessions = _sessions(story, now, range(DAYS, -1, -1))
    _cashiers(
        company,
        {s.opener.pk: s.opener for s in sessions} | {s.closer.pk: s.closer for s in sessions},
    )
    # Imported first, so their numbers come before the ones the tills give out now.
    first_day = _imported(company, story, now, tills, methods)

    # The last day session that closed keeps its handover waiting for the owner.
    closed = [s for s in sessions if s.closes <= now - timedelta(minutes=5)]
    pending = max((s for s in closed if not s.night), key=lambda s: s.closes, default=None)
    shifts = []
    for session in closed:
        back = (story.today - session.day).days
        story_kind = "pending" if session is pending else _story(back, session)
        with _quiet_alerts(back):
            shift = _history_shift(
                company,
                rng,
                session=session,
                register=tills[session.code],
                methods=methods,
                owner=owner,
                bank=bank,
                with_photos=back <= 5,
                kind=story_kind,
            )
        shifts.append((session, shift, story_kind))
        if session.day.weekday() == 0 and not session.night:
            _bank_run(company, story, session, owner, bank)
    for session, shift, story_kind in shifts:
        back = (story.today - session.day).days
        if back <= 2:
            continue  # waits in Needs you
        verifier = _verifier(story, session)
        at = story.at(session.day + timedelta(days=1), time(9, 40 + rng.randint(0, 15)))
        with moment(at), _quiet_alerts(back):
            if story_kind == "dispute":
                services.dispute_shift(
                    shift, by=owner, reason="Z-hisobot surati xira, kassani qayta sanang"
                )
            elif story_kind == "recount":
                services.verify_shift(
                    shift,
                    by=verifier,
                    recount_cash=str(shift.counted_cash - 10_000),
                    note="Qayta sanaldi",
                )
            else:
                services.verify_shift(shift, by=verifier)

    _ai_mismatch([shift for _session, shift, _kind in shifts])
    _open_now(company, story, sessions, now, tills, methods)
    _extras(company, story, rng, now, methods)
    _targets(company, story, people)
    first_day = min(first_day, story.today - timedelta(days=DAYS + 1))
    rollup.rebuild_range(company, first_day, story.today)


@contextmanager
def _quiet_alerts(back: int):
    """The routine alerts of shifts older than three days (closed, checked, cash handed over)
    stay unsent: they'd sit read in the inbox, and they're a third of the demo's build time.
    Disputes, declined handovers and the assistant's mismatch still alert."""
    if back <= 3:
        yield
        return
    with ExitStack() as stack:
        for name in ROUTINE_ALERTS:
            stack.enter_context(mock.patch.object(alerts, name, _no_alert))
        yield


def _no_alert(*args, **kwargs):
    return None


def _sessions(story, now, backs) -> list[Session]:
    """The till sessions of the days `backs` days ago, from the roster: who opens and who closes
    each one."""
    sessions = []
    for back in backs:
        day = story.today - timedelta(days=back)
        for code, night in (("C", False), ("Y", False), ("Y", True)):
            if code == "Y" and story.branches["Y"] == story.branches["C"]:
                continue
            opener, closer = story.till(code, day, night=night)
            if opener is None:
                continue
            # A till changes hands at 08:00 and 20:00: one session closes before the next opens.
            opens = opener.starts + timedelta(minutes=2 if code == "Y" else -8)
            closes = closer.ends + timedelta(minutes=-6 if code == "Y" else 6)
            if opens > now:
                continue
            sessions.append(
                Session(
                    code,
                    day,
                    night,
                    story.member(opener.key),
                    story.member(closer.key),
                    opens,
                    closes,
                )
            )
    return sessions


def _imported(company, story, now, tills, methods) -> date:
    """The imported weeks before the tills' detailed ones (see the module's docstring), built
    from the ledger demo's daily sales. Returns the first day with sales (the detailed weeks'
    first day when there is nothing to import: the ledger's demo didn't run)."""
    first_detailed = story.today - timedelta(days=DAYS)
    daily: dict[tuple[int, date], dict[str, Decimal]] = defaultdict(dict)
    rows = Transaction.objects.filter(
        company=company,
        source_type=DEMO_SOURCE,
        source_key__startswith="s:",
        status=Transaction.Status.POSTED,
    ).values_list("source_id", "source_key", "amount")
    for branch_id, key, amount in rows:
        _sales, stamp, channel = key.split(":")
        day = datetime.strptime(stamp, "%y%m%d").date()
        if day < first_detailed:
            daily[(branch_id, day)][channel] = amount
    if not daily:
        return first_detailed
    first_day = min(day for _branch, day in daily)
    backs = range((story.today - first_day).days, DAYS, -1)
    by_day = defaultdict(list)
    for session in _sessions(story, now, backs):
        by_day[(session.code, session.day)].append(session)

    rng = random.Random(912)
    card_mix = {code: share for code, share in MIX.items() if code != "cash"}
    specs = []  # (session, register, opening float, cash, {card method: sales}, transfer)
    for code, register in tills.items():
        if code == "Y" and story.branches["Y"] == story.branches["C"]:
            continue
        branch, till = story.branches[code], register.cash_account
        safe = MoneyAccount.objects.filter(
            company=company, branch=branch, kind=MoneyAccount.Kind.SAFE, currency=till.currency
        ).first()
        to_safe = {
            transfer.occurred_on: transfer
            for transfer in Transfer.objects.filter(
                company=company,
                status=Transfer.Status.POSTED,
                from_account=till,
                to_account=safe,
                occurred_on__range=(first_day, first_detailed),
            )
        }
        held = finance_queries.balance(till, first_day - timedelta(days=1))
        for back in backs:
            day = story.today - timedelta(days=back)
            totals, sessions = daily.get((branch.pk, day)), by_day.get((code, day))
            if not totals or not sessions:
                continue
            shares = [1.0] if len(sessions) == 1 else [1 - NIGHT_SHARE, NIGHT_SHARE]
            cash_parts = _split(totals.get("cash", Decimal(0)), shares)
            card_parts = _split(totals.get("card", Decimal(0)), shares)
            for index, session in enumerate(sessions):
                # The day's cash goes to the safe at the end of its last session.
                moved = to_safe.get(day) if index == len(sessions) - 1 else None
                cards = _split(card_parts[index], list(card_mix.values()))
                specs.append(
                    (
                        session,
                        register,
                        held,
                        cash_parts[index],
                        dict(zip(card_mix, cards, strict=True)),
                        moved,
                    )
                )
                held += cash_parts[index] - (moved.amount_out if moved else 0)

    number = SalesSettings.objects.get(company=company).next_shift_number
    shifts, payments, movements = [], [], []
    for session, register, opening, cash, cards, moved in sorted(specs, key=lambda s: s[0].opens):
        counted = opening + cash - (moved.amount_out if moved else 0)
        card = sum(cards.values(), Decimal(0))
        verified = story.at(session.day + timedelta(days=1), time(9, 40 + rng.randint(0, 15)))
        shift = CashShift(
            company=company,
            number=number,
            branch=story.branches[session.code],
            register=register,
            cashier=session.opener,
            business_day=session.day,
            status=CashShift.Status.VERIFIED,
            source=CashShift.Source.IMPORT,
            opened_at=session.opens + timedelta(minutes=rng.randint(0, 5)),
            opening_float=opening,
            opening_count=_count(opening),
            expected_float=opening,
            closed_at=session.closes - timedelta(minutes=rng.randint(0, 4)),
            closed_by=session.closer,
            counted_cash=counted,
            closing_count=_count(counted),
            expected_cash=counted,
            difference=Decimal(0),
            fiscal_cash_total=cash,
            fiscal_card_total=card,
            z_number=f"{412 + number:04d}",
            receipts=max(int((cash + card) / rng.randint(*AVERAGE_RECEIPT)), 1),
            verified_by=_verifier(story, session),
            verified_at=min(verified, now),
        )
        shifts.append(shift)
        for code, amount in (("cash", cash), *cards.items()):
            if amount > 0 and code in methods:
                payments.append(ShiftPayment(shift=shift, method=methods[code], sales=amount))
        if moved is not None:
            movements.append(
                CashMovement(
                    company=company,
                    branch=shift.branch,
                    register=register,
                    shift=shift,
                    kind=CashMovement.Kind.TO_SAFE,
                    amount=moved.amount_out,
                    currency=register.cash_account.currency,
                    transfer=moved,
                    reason="Kunlik tushum seyfga",
                    created_by=session.closer,
                    confirmed_by=session.closer,
                )
            )
        number += 1
    CashShift.objects.bulk_create(shifts)
    for row in (*payments, *movements):
        row.shift_id = row.shift.pk
    ShiftPayment.objects.bulk_create(payments)
    CashMovement.objects.bulk_create(movements)
    SalesSettings.objects.filter(company=company).update(next_shift_number=number)
    # Written when they happened, not now.
    ids = [shift.pk for shift in shifts]
    CashShift.objects.filter(pk__in=ids).update(
        created_at=F("opened_at"), updated_at=F("verified_at")
    )
    before_closing = ExpressionWrapper(
        Subquery(CashShift.objects.filter(pk=OuterRef("shift_id")).values("closed_at")[:1])
        - timedelta(minutes=12),
        output_field=DateTimeField(),
    )
    CashMovement.objects.filter(shift_id__in=ids).update(
        created_at=before_closing, updated_at=before_closing, confirmed_at=before_closing
    )
    return first_day


def _split(amount: Decimal, shares: list[float]) -> list[Decimal]:
    """`amount` in parts as `shares` (rounded to 1 000 so‘m; the last part takes the rest)."""
    total = sum(shares)
    parts = [_round(float(amount) * share / total) for share in shares[:-1]]
    parts.append(amount - sum(parts, Decimal(0)))
    return parts


def _configure(company) -> None:
    from apps.sales.conf import get_settings

    get_settings(company)
    SalesSettings.objects.filter(company=company).update(
        cash_tolerance=Decimal("5000"),
        big_payout_alert=Decimal("500000"),
        handover_confirm_hours=2,
    )
    for code, fee in FEES.items():
        PaymentMethod.objects.filter(company=company, system_code=code).update(
            fee_percent=Decimal(fee)
        )


def _cashiers(company, runners: dict) -> None:
    """Whoever runs a till in the story may open Kassa in the mini app: in the demo they hold the
    pharmacist role; anyone without the till permission (another module's tests) gets the
    Cashier role, which only adds it."""
    role = AccessRole.objects.filter(company=company, name="Cashier").first()
    if role is None:
        return
    for member in runners.values():
        if member.has_perm(Perm.SALES_OPERATE) or (member.role and member.role.is_owner):
            continue
        Membership.objects.filter(pk=member.pk).update(role=role)
        member.role = role


def _bank(company, owner) -> MoneyAccount:
    found = MoneyAccount.objects.filter(
        company=company, kind=MoneyAccount.Kind.BANK, is_active=True
    ).first()
    if found is not None:
        return found
    return finance.create_account(
        company, by=owner, kind=MoneyAccount.Kind.BANK, name="Asosiy bank hisobi"
    )


def _verifier(story, session) -> Membership:
    """The pharmacy's head checks its shifts (the owner checks the head's own)."""
    head = story.member("manager") if session.code == "C" else story.member("farrux")
    if head is None or head.pk in (session.opener.pk, session.closer.pk):
        return story.member("owner")
    return head


def _story(back: int, session: Session) -> str:
    """Fixed events on fixed days back, so the demo always tells the same story."""
    yns, night = session.code == "Y", session.night
    if yns and not night and back == 9:
        return "dispute"
    if not yns and back == 16:
        return "recount"
    if yns and back in (4, 13, 22):
        return "short"
    if not yns and back in (11, 27):
        return "small_short"
    if yns and night and back == 19:
        return "surplus"
    if yns and not night and back == 6:
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
        sales = _round(net_target * share * rng.uniform(0.8, 1.2))
        if sales <= 0:
            continue
        lines.append(PaymentLine(method, sales, Decimal(0), 0))
        if code == "cash":
            cash_net = sales
    return lines, cash_net


def _history_shift(company, rng, *, session, register, methods, owner, bank, with_photos, kind):
    opened = session.opens + timedelta(minutes=rng.randint(0, 5))
    if kind == "small_short" and session.code == "C":
        opened += timedelta(minutes=35)  # a late opening for the scorecard (08:00 at Chilonzor)
    count, amount = _opening(register)
    with moment(opened):
        shift = services.open_shift(
            by=session.opener,
            register=register,
            opening_count=count,
            opening_float=str(amount),
            now=opened,
        )
    weekday = session.day.weekday()
    base = SESSION_SALES[(session.code, session.night)] * (1.08 if weekday == 0 else 1.0)
    net_target = int(base * rng.uniform(0.82, 1.18))
    lines, cash_net = _lines(rng, methods, net_target)
    hours = (session.closes - session.opens).total_seconds() / 3600

    moves = Decimal(0)
    if rng.random() < 0.35:
        reason, code, low, high = rng.choice(PAYOUTS)
        amount = _round(rng.uniform(low, high))
        at = opened + timedelta(hours=rng.uniform(1.5, hours - 1))
        with moment(at):
            services.record_movement(
                by=session.opener,
                register=register,
                kind="payout",
                amount=amount,
                reason=reason,
                category=_category(company, code),
                photo=_receipt_photo(reason, amount) if with_photos else None,
                now=at,
            )
        moves -= amount
    # Busy days a midday drop into the safe; every evening all but the next session's change
    # goes to the owner (on Mondays to the bank's cash collector).
    if not session.night and session.day.toordinal() % 3 == 0 and cash_net > 3_000_000:
        drop = Decimal(1_500_000)
        with moment(opened + timedelta(hours=6, minutes=10)):
            services.record_movement(
                by=session.opener, register=register, kind="to_safe", amount=drop, reason="Seyfga"
            )
        moves -= drop
    closed_at = session.closes - timedelta(minutes=rng.randint(0, 4))
    closer = session.closer
    before_handover = shift.opening_float + cash_net + moves
    handover_amount = ((before_handover - KEEP) // 100_000) * 100_000
    # Monday evenings the bank's cash collector takes the day's takings instead.
    collected = session.day.weekday() == 0 and kind not in ("pending", "declined")
    if not session.night and handover_amount > 0 and collected:
        with moment(closed_at - timedelta(minutes=15)):
            services.record_movement(
                by=closer,
                register=register,
                kind="to_bank",
                amount=handover_amount,
                to_account=bank,
                reason="Inkassatsiya",
            )
        moves -= handover_amount
    elif not session.night and handover_amount > 0:
        receiver = owner
        if kind == "declined":
            # The owner says the envelope never reached her; it was still in the till's drawer,
            # so the cashier voids that handover and sends the cash again before closing.
            with moment(closed_at - timedelta(minutes=55)):
                first = services.record_movement(
                    by=closer,
                    register=register,
                    kind="handover",
                    amount=handover_amount,
                    receiver=receiver,
                    reason="Kunlik tushum",
                )
            with moment(closed_at - timedelta(minutes=40)):
                services.decline_handover(first, by=receiver, reason="Pul menga yetib kelmadi")
            with moment(closed_at - timedelta(minutes=30)):
                services.void_movement(
                    first, by=closer, reason="Konvert kassa tortmasida qolgan ekan"
                )
        with moment(closed_at - timedelta(minutes=12)):
            handover = services.record_movement(
                by=closer,
                register=register,
                kind="handover",
                amount=handover_amount,
                receiver=receiver,
                reason="Kunlik tushum",
            )
        if kind != "pending":  # yesterday's last handover still waits for the owner
            with moment(closed_at + timedelta(minutes=rng.randint(20, 90))):
                services.confirm_handover(handover, by=receiver)
        moves -= handover_amount
    expected = shift.opening_float + cash_net + moves
    difference = {
        "short": Decimal(-rng.choice([15_000, 25_000, 45_000])),
        "small_short": Decimal(-2_000),
        "surplus": Decimal(12_000),
        "dispute": Decimal(-120_000),
        "recount": Decimal(0),
    }.get(kind, Decimal(0) if rng.random() < 0.85 else Decimal(-rng.choice([1_000, 3_000])))
    counted = expected + difference
    net = sum((line.sales for line in lines), Decimal(0))
    receipts = max(int(net / Decimal(rng.randint(*AVERAGE_RECEIPT))), 1)
    takes_cards = any(line.method.kind in ("card", "qr") for line in lines)
    with moment(closed_at):
        shift = services.close_shift(
            shift,
            by=closer,
            payments=lines,
            counted_cash=str(counted),
            closing_count=_count(counted),
            receipts=receipts,
            z_number=f"{412 + shift.number:04d}",
            fiscal_cash_total=str(cash_net),
            fiscal_card_total=str(net - cash_net),
            z_photo=_z_report(company, register, shift, lines, receipts)
            if with_photos
            else _blank(),
            terminal_photo=(_terminal(lines) if with_photos else _blank()) if takes_cards else None,
            note="",
            now=closed_at,
        )
    return shift


def _opening(register) -> tuple[dict, Decimal]:
    """The float a cashier counts: what the till holds (its first time, 200 000 in change)."""
    from apps.sales import cash

    held = cash.till_physical(register)
    if held <= 0:
        return dict(FIRST_FLOAT), Decimal(200_000)
    return _count(held), held


def _bank_run(company, story, session, owner, bank) -> None:
    """Monday mornings the cash in each safe and with the owner goes to the bank."""
    at = story.at(session.day, time(11, 15))
    with moment(at):
        for code in ("C", "Y"):
            safe = MoneyAccount.objects.filter(
                branch=story.branches[code], kind=MoneyAccount.Kind.SAFE
            ).first()
            if safe is not None and safe.balance > 1_000_000 and session.code == code:
                finance.transfer(
                    company,
                    by=owner,
                    from_account=safe,
                    to_account=bank,
                    amount_out=safe.balance - 1_000_000,
                    occurred_on=session.day,
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
                amount_out=held.balance - 1_000_000,
                occurred_on=session.day,
                description="Kunlik tushum bankka",
            )


def _count(amount: Decimal) -> dict:
    """A plausible banknote breakdown of `amount` (multiples of 1 000 so‘m)."""
    left = int(amount)
    count = {}
    for note in (200_000, 100_000, 50_000, 20_000, 10_000, 5_000, 2_000, 1_000):
        pieces, left = divmod(left, note)
        if pieces:
            count[str(note)] = pieces
    return count if left == 0 else {}


def _category(company, code: str) -> Category:
    return Category.objects.get(company=company, system_code=code)


def _ai_mismatch(shifts) -> None:
    closed = [shift for shift in shifts if shift.status == CashShift.Status.CLOSED]
    target = closed[-1] if closed else None
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


def _open_now(company, story, sessions, now, tills, methods) -> None:
    """The tills of the shifts under way: opened at the start of the shift, one payout so far
    at Chilonzor."""
    for session in sessions:
        if session.closes <= now - timedelta(minutes=5) or session.opens > now:
            continue
        register = tills[session.code]
        opened = min(session.opens + timedelta(minutes=2), now - timedelta(minutes=3))
        with moment(opened):
            count, amount = _opening(register)
            services.open_shift(
                by=session.opener,
                register=register,
                opening_count=count,
                opening_float=str(amount),
                now=opened,
            )
        if session.code == "C" and now - opened > timedelta(hours=2):
            paid = opened + timedelta(hours=1, minutes=20)
            with moment(paid):
                services.record_movement(
                    by=session.opener,
                    register=register,
                    kind="payout",
                    amount=48_000,
                    reason="Ichimlik suvi, 19 l × 2",
                    category=_category(company, "other_expense"),
                    photo=_receipt_photo("Ichimlik suvi", 48_000),
                    now=paid,
                )


def _extras(company, story, rng, now, methods) -> None:
    """A few orders entered in the dashboard (a clinic and a kindergarten paying by transfer),
    so the entries page has something real."""
    entries = [
        (
            3,
            "C",
            [("transfer", 2_850_000)],
            "Tonggi Shabnam klinikasi: bir martalik shpritslar va bint",
        ),
        (8, "C", [("transfer", 1_240_000)], "Bolalar bog‘chasi uchun birinchi yordam qutilari"),
        (12, "Y", [("click", 640_000), ("cash", 210_000)], "Telegram orqali oldindan buyurtma"),
        (17, "Y", [("transfer", 1_980_000)], "Tonggi Shabnam klinikasi: antiseptiklar"),
        (25, "C", [("payme", 380_000)], "Yetkazib berish buyurtmasi"),
    ]
    for back, code, pays, note in entries:
        # The pharmacy's head enters them in office hours, on a day they work.
        key = "manager" if code == "C" or story.member("farrux") is None else "farrux"
        day = story.today - timedelta(days=back)
        if not story.works(key, day):
            day = story.last_working_day(key, day) or day
        at = story.at(day, time(rng.randint(10, 16), rng.randint(0, 59)))
        with moment(at):
            services.record_sale(
                by=story.member(key),
                payments=[(methods[method], amount) for method, amount in pays],
                branch=story.branches[code],
                source="dashboard",
                note=note,
                sold_at=at,
                number=f"BUY-{1040 + back}",
            )


def _targets(company, story, people) -> None:
    month = story.today.replace(day=1)
    owner = people["owner"]
    services.set_target(company, by=owner, month=month, amount=Decimal("560000000"))
    services.set_target(
        company, by=owner, month=month, amount=Decimal("190000000"), branch=story.branches["C"]
    )
    if story.branches["Y"] != story.branches["C"]:
        services.set_target(
            company, by=owner, month=month, amount=Decimal("370000000"), branch=story.branches["Y"]
        )
    services.set_target(
        company, by=owner, month=month, amount=Decimal("100000000"), membership=people["worker"]
    )
    previous = (month - timedelta(days=1)).replace(day=1)
    services.set_target(company, by=owner, month=previous, amount=Decimal("540000000"))


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


def _z_report(company, register, shift, lines, receipts) -> bytes:
    rows = [
        (company.name.upper(), "", True),
        (f"{register.branch.name} · {register.name}", "", False),
        (f"FM: {register.fiscal_serial or 'UZ-FM 210045'}", "", False),
        ("---", "", False),
        (f"Z-HISOBOT № {412 + shift.number:04d}", "", True),
        (f"Sana: {shift.business_day:%d.%m.%Y}", "", False),
        ("---", "", False),
    ]
    for line in lines:
        rows.append((line.method.name, _sum(line.sales), False))
    total = sum((line.sales for line in lines), Decimal(0))
    rows += [
        ("---", "", False),
        ("Cheklar soni", str(receipts), False),
        ("JAMI", _sum(total), True),
        ("QQS 12%", _sum(total * Decimal("0.1071")), False),
    ]
    return _paper(rows, title="Z-HISOBOT")


def _terminal(lines) -> bytes:
    cards = [line for line in lines if line.method.kind in ("card", "qr")]
    total = sum((line.sales for line in cards), Decimal(0))
    rows = [
        ("UZCARD · HUMO · QR", "", True),
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
