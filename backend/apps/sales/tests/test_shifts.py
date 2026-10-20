"""Shifts end to end through the services: numbering, business days, the close bookings of
§3.8, corrections that void and rebook, verification and force-close."""

import threading
from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.db import IntegrityError, connection
from django.db.models import Sum

from apps.core.exceptions import DomainError
from apps.finance.models import LIVE_STATUSES, MoneyAccount, Transaction
from apps.sales import cash, services
from apps.sales.days import business_day
from apps.sales.models import CashShift, PaymentMethod, Register
from apps.sales.services import PaymentLine
from apps.sales.tests.factories import jpeg, make_shop, open_and_close

TASHKENT = ZoneInfo("Asia/Tashkent")


def live_rows(shift):
    return Transaction.objects.filter(
        source_type="sales.cashshift", source_id=shift.pk, status__in=LIVE_STATUSES
    )


def keyed(shift) -> dict[str, Transaction]:
    return {row.source_key: row for row in live_rows(shift)}


# Defaults ---------------------------------------------------------------------------------


def test_defaults_make_methods_a_till_and_a_safe_per_branch(shop):
    codes = set(
        PaymentMethod.objects.filter(company=shop.company).values_list("system_code", flat=True)
    )
    assert {
        "cash",
        "uzcard",
        "humo",
        "visa",
        "click",
        "payme",
        "uzum",
        "transfer",
        "credit",
        "installment",
    } == codes
    assert Register.objects.filter(company=shop.company).count() == 2
    till = shop.register.cash_account
    assert till.kind == MoneyAccount.Kind.CASH and till.branch_id == shop.branch.pk
    assert till.allow_negative  # sales book at close, payouts at once
    safes = MoneyAccount.objects.filter(company=shop.company, kind=MoneyAccount.Kind.SAFE)
    assert set(safes.values_list("branch_id", flat=True)) == {shop.branch.pk, shop.other_branch.pk}
    # Cards and wallets land in the terminal's clearing account, never in a till.
    assert shop.method("uzcard").account.kind == MoneyAccount.Kind.CLEARING
    assert shop.method("cash").account is None


def test_defaults_are_idempotent_and_skip_companies_without_sales(shop, company):
    from apps.sales import defaults

    defaults.ensure(shop.company)
    defaults.ensure(shop.company)
    assert PaymentMethod.objects.filter(company=shop.company).count() == 10
    assert Register.objects.filter(company=shop.company).count() == 2
    defaults.ensure(company)  # sales off
    assert not PaymentMethod.objects.filter(company=company).exists()


# Opening ----------------------------------------------------------------------------------


def test_opening_counts_the_float_and_numbers_shifts(shop):
    shift = services.open_shift(
        by=shop.cashier, register=shop.register, opening_count={"50000": 4, "10000": 5}
    )
    assert shift.opening_float == Decimal("250000.00")
    assert shift.opening_count == {"50000": 4, "10000": 5}
    assert shift.number == 1 and shift.code == "CHL-1"
    assert shift.status == CashShift.Status.OPEN
    # A till's very first float is its opening balance in the ledger.
    assert keyed(shift)["float"].kind == "opening"
    shift.register.cash_account.refresh_from_db()
    assert shift.register.cash_account.balance == Decimal("250000.00")
    other = services.open_shift(by=shop.colleague, register=shop.other_register, opening_float="0")
    assert other.number == 2 and other.code == "YNS-2"


def test_a_count_and_a_total_must_agree(shop):
    with pytest.raises(DomainError):
        services.open_shift(
            by=shop.cashier, register=shop.register, opening_count={"50000": 2}, opening_float="1"
        )


def test_one_open_shift_per_till_and_per_cashier(shop):
    services.open_shift(by=shop.cashier, register=shop.register, opening_float="0")
    with pytest.raises(DomainError):
        services.open_shift(by=shop.colleague, register=shop.register, opening_float="0")
    with pytest.raises(DomainError):
        services.open_shift(by=shop.cashier, register=shop.other_register, opening_float="0")


@pytest.mark.django_db(transaction=True)
def test_the_database_refuses_a_second_open_shift(db):
    shop = make_shop()
    first = services.open_shift(by=shop.cashier, register=shop.register, opening_float="0")
    with pytest.raises(IntegrityError):
        CashShift.objects.create(
            company=shop.company,
            number=99,
            branch=shop.branch,
            register=shop.register,
            cashier=shop.colleague,
            business_day=first.business_day,
            opened_at=first.opened_at,
        )
    with pytest.raises(IntegrityError):
        CashShift.objects.create(
            company=shop.company,
            number=100,
            branch=shop.other_branch,
            register=shop.other_register,
            cashier=shop.cashier,
            business_day=first.business_day,
            opened_at=first.opened_at,
        )


@pytest.mark.django_db(transaction=True)
def test_numbers_stay_unique_when_two_shifts_open_at_once(db):
    shop = make_shop()
    barrier = threading.Barrier(2)
    numbers, errors = [], []

    def open_one(cashier, register):
        try:
            barrier.wait(timeout=5)
            numbers.append(
                services.open_shift(by=cashier, register=register, opening_float="0").number
            )
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)
        finally:
            connection.close()

    threads = [
        threading.Thread(target=open_one, args=(shop.cashier, shop.register)),
        threading.Thread(target=open_one, args=(shop.colleague, shop.other_register)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert sorted(numbers) == [1, 2]


def test_a_later_float_that_differs_books_the_difference(shop):
    first = open_and_close(shop, opening="200000", cash_sales="1000000", card_sales="0")
    # The till now holds what was counted: 1 200 000.
    assert cash.till_physical(first.register) == Decimal("1200000.00")
    second = services.open_shift(by=shop.cashier, register=shop.register, opening_float="1150000")
    assert second.expected_float == Decimal("1200000.00")
    row = keyed(second)["float"]
    assert (row.kind, row.amount, row.category.system_code) == (
        "expense",
        Decimal("-50000.00"),
        "cash_shortage",
    )
    shop.register.cash_account.refresh_from_db()
    assert shop.register.cash_account.balance == Decimal("1150000.00")


# Business day -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("clock", "ends_at", "expected_day"),
    [
        ((23, 59), time(4, 0), 20),
        ((0, 30), time(4, 0), 20),
        ((3, 59), time(4, 0), 20),
        ((4, 0), time(4, 0), 21),
        ((0, 30), time(0, 0), 21),
        ((5, 30), time(6, 0), 20),
    ],
)
def test_business_day_around_midnight(shop, clock, ends_at, expected_day):
    day = 21 if clock[0] < 12 else 20
    moment = datetime(2026, 10, day, *clock, tzinfo=TASHKENT)
    assert business_day(shop.company, moment, ends_at=ends_at).day == expected_day


def test_a_night_shift_books_on_the_evening_it_started(shop):
    opened = datetime(2026, 10, 20, 23, 30, tzinfo=TASHKENT)
    shift = services.open_shift(
        by=shop.cashier, register=shop.register, opening_float="0", now=opened
    )
    assert shift.business_day.isoformat() == "2026-10-20"
    closed = services.close_shift(
        shift,
        by=shop.cashier,
        payments=[PaymentLine(shop.method("cash"), Decimal("300000"))],
        counted_cash="300000",
        z_photo=jpeg(),
        now=datetime(2026, 10, 21, 2, 0, tzinfo=TASHKENT),
    )
    assert {row.occurred_on.isoformat() for row in live_rows(closed)} == {"2026-10-20"}


# Closing ----------------------------------------------------------------------------------


def test_close_books_exactly_the_rows_of_the_plan(shop):
    shop.method("uzcard").__class__.objects.filter(pk=shop.method("uzcard").pk).update(
        fee_percent=Decimal("1.00")
    )
    shift = services.open_shift(by=shop.cashier, register=shop.register, opening_float="200000")
    closed = services.close_shift(
        shift,
        by=shop.cashier,
        payments=[
            PaymentLine(shop.method("cash"), Decimal("1000000"), Decimal("50000"), 30),
            PaymentLine(shop.method("uzcard"), Decimal("600000"), Decimal("0"), 10),
            PaymentLine(shop.method("credit"), Decimal("250000"), Decimal("0"), 2),
        ],
        counted_cash="1135000",
        z_photo=jpeg(),
        terminal_photo=jpeg(),
    )
    cash_id, card_id = shop.method("cash").pk, shop.method("uzcard").pk
    rows = keyed(closed)
    assert set(rows) == {
        "float",
        f"m{cash_id}",
        f"r{cash_id}",
        f"m{card_id}",
        f"f{card_id}",
        "diff",
    }
    assert (rows[f"m{cash_id}"].amount, rows[f"m{cash_id}"].account_id) == (
        Decimal("1000000.00"),
        shop.register.cash_account_id,
    )
    assert rows[f"r{cash_id}"].is_contra and rows[f"r{cash_id}"].amount == Decimal("-50000.00")
    assert rows[f"r{cash_id}"].category.system_code == "refunds"
    assert rows[f"m{card_id}"].account_id == shop.method("uzcard").account_id
    assert rows[f"f{card_id}"].amount == Decimal("-6000.00")
    assert rows[f"f{card_id}"].category.system_code == "bank_fees"
    # Expected 200 000 + 1 000 000 - 50 000 = 1 150 000; counted 1 135 000.
    assert closed.expected_cash == Decimal("1150000.00")
    assert closed.difference == Decimal("-15000.00")
    assert rows["diff"].category.system_code == "cash_shortage"
    assert rows["diff"].amount == Decimal("-15000.00")
    assert rows["diff"].membership_id == shop.cashier.pk
    # Nasiya (credit) is booked per credit sale by package J, never as shift income.
    assert not any(key.endswith(str(shop.method("credit").pk)) for key in rows)
    # Every shift booking is on the shift's business day.
    assert {row.occurred_on for row in rows.values()} == {closed.business_day}
    # The till's ledger balance now equals the cash counted in it.
    shop.register.cash_account.refresh_from_db()
    assert shop.register.cash_account.balance == Decimal("1135000.00")


def test_close_needs_a_count_and_the_photos(shop):
    shift = services.open_shift(by=shop.cashier, register=shop.register, opening_float="0")
    card = [PaymentLine(shop.method("uzcard"), Decimal("100000"))]
    with pytest.raises(DomainError):
        services.close_shift(
            shift, by=shop.cashier, payments=card, z_photo=jpeg(), terminal_photo=jpeg()
        )
    with pytest.raises(DomainError):
        services.close_shift(
            shift, by=shop.cashier, payments=card, counted_cash="0", terminal_photo=jpeg()
        )
    with pytest.raises(DomainError):
        services.close_shift(
            shift, by=shop.cashier, payments=card, counted_cash="0", z_photo=jpeg()
        )
    closed = services.close_shift(
        shift,
        by=shop.cashier,
        payments=card,
        counted_cash="0",
        z_photo=jpeg(),
        terminal_photo=jpeg(),
    )
    assert closed.z_photo.name.endswith(".jpg") and closed.z_photo.name.startswith("sales/shifts/")
    with pytest.raises(DomainError):
        services.close_shift(
            closed, by=shop.cashier, payments=card, counted_cash="0", z_photo=jpeg()
        )


def test_a_correction_voids_and_rebooks_with_matching_sums(shop):
    closed = open_and_close(
        shop, opening="200000", cash_sales="1000000", card_sales="500000", counted="1190000"
    )
    before = keyed(closed)
    services.correct_shift(
        closed,
        by=shop.manager,
        payments=[
            PaymentLine(shop.method("cash"), Decimal("990000")),
            PaymentLine(shop.method("uzcard"), Decimal("500000")),
        ],
        reason="Typo in the cash total",
    )
    closed.refresh_from_db()
    after = keyed(closed)
    cash_id, card_id = shop.method("cash").pk, shop.method("uzcard").pk
    # Only what changed was voided and booked again; the card row stayed as it was.
    assert after[f"m{card_id}"].pk == before[f"m{card_id}"].pk
    assert after[f"m{cash_id}"].pk != before[f"m{cash_id}"].pk
    assert Transaction.objects.get(pk=before[f"m{cash_id}"].pk).status == "void"
    assert closed.expected_cash == Decimal("1190000.00") and closed.difference == Decimal("0.00")
    assert "diff" not in after
    total = live_rows(closed).exclude(source_key="float").aggregate(t=Sum("base_amount"))["t"]
    assert total == Decimal("1490000.00")
    shop.register.cash_account.refresh_from_db()
    assert shop.register.cash_account.balance == Decimal("1190000.00")


def test_verify_with_a_recount_moves_the_difference(shop):
    closed = open_and_close(shop, counted="1200000", card_sales="0")
    assert closed.difference == Decimal("0.00")
    with pytest.raises(DomainError):
        services.verify_shift(closed, by=shop.cashier)  # nobody checks their own shift
    verified = services.verify_shift(
        closed, by=shop.manager, recount_cash="1180000", note="Recounted"
    )
    assert verified.status == CashShift.Status.VERIFIED
    assert verified.difference == Decimal("-20000.00")
    assert keyed(verified)["diff"].amount == Decimal("-20000.00")
    with pytest.raises(DomainError):
        services.verify_shift(verified, by=shop.manager)


def test_dispute_then_verify(shop):
    closed = open_and_close(shop)
    disputed = services.dispute_shift(closed, by=shop.manager, reason="The Z photo is blurry")
    assert disputed.status == CashShift.Status.DISPUTED and disputed.note == "The Z photo is blurry"
    with pytest.raises(DomainError):
        services.dispute_shift(disputed, by=shop.manager, reason="again")
    assert services.verify_shift(disputed, by=shop.manager).status == CashShift.Status.VERIFIED


def test_force_close_without_a_count_books_no_difference(shop):
    shift = services.open_shift(by=shop.cashier, register=shop.register, opening_float="100000")
    closed = services.force_close(shift, by=shop.manager, reason="Cashier went home")
    assert closed.forced and closed.status == CashShift.Status.CLOSED
    assert closed.counted_cash is None and closed.difference is None
    assert "diff" not in keyed(closed)
    corrected = services.correct_shift(
        closed, by=shop.manager, payments=[], reason="Counted next morning", counted_cash="90000"
    )
    assert corrected.difference == Decimal("-10000.00")
    assert keyed(corrected)["diff"].amount == Decimal("-10000.00")


def test_record_ai_reading_is_the_only_writer(shop):
    closed = open_and_close(shop)
    services.record_ai_reading(
        closed, reading={"cash": "1000000.00", "card": "480000.00"}, mismatch=True
    )
    closed.refresh_from_db()
    assert closed.ai_mismatch and closed.ai_reading["card"] == "480000.00"
    # No other code path writes ai_reading.
    import pathlib
    import re

    root = pathlib.Path(services.__file__).resolve().parent
    assigns = re.compile(r"\.ai_reading\s*=[^=]|\bai_reading=")
    writers = sorted(
        f"{path.parent.name}/{path.name}"
        for path in root.parent.glob("*/*.py")
        if assigns.search(path.read_text())
    )
    assert writers == ["sales/services.py"]
