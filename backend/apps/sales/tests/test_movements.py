"""Cash leaving or entering a till: payouts, handovers (money moves only on confirmation), the
safe, the bank; voids; single receipts."""

from decimal import Decimal

import pytest

from apps.core.exceptions import DomainError
from apps.finance import services as finance
from apps.finance.models import LIVE_STATUSES, MoneyAccount, Transaction
from apps.inbox.models import Notification
from apps.sales import cash, services
from apps.sales.models import CashMovement, Sale, SalesSettings
from apps.sales.services import PaymentLine
from apps.sales.tests.factories import jpeg


@pytest.fixture
def shift(shop):
    return services.open_shift(by=shop.cashier, register=shop.register, opening_float="500000")


def till(shop) -> Decimal:
    account = MoneyAccount.objects.get(pk=shop.register.cash_account_id)
    return account.balance


def test_a_payout_is_an_expense_on_the_till_even_below_zero(shop, shift):
    movement = services.record_movement(
        by=shop.cashier,
        register=shop.register,
        kind=CashMovement.Kind.PAYOUT,
        amount="800000",
        reason="Bread from Non uyi",
        category="goods",
        photo=jpeg(),
    )
    assert movement.shift_id == shift.pk and movement.status == "done"
    row = movement.transaction
    assert (row.kind, row.amount, row.category.system_code) == (
        "expense",
        Decimal("-800000.00"),
        "goods",
    )
    assert row.source_type == "sales.cashmovement" and row.occurred_on == shift.business_day
    # 500 000 float - 800 000: sales book at close, so the till may dip below zero meanwhile.
    assert till(shop) == Decimal("-300000.00")
    assert movement.photo.name.startswith("sales/movements/")
    assert cash.expected_cash(shift) == Decimal("-300000.00")


def test_a_payout_needs_a_reason_and_an_expense_category(shop, shift):
    with pytest.raises(DomainError):
        services.record_movement(
            by=shop.cashier, register=shop.register, kind="payout", amount="1000"
        )
    with pytest.raises(DomainError):
        services.record_movement(
            by=shop.cashier,
            register=shop.register,
            kind="payout",
            amount="1000",
            reason="x",
            category="sales",
        )


def test_a_handover_moves_money_only_when_the_receiver_confirms(
    shop, shift, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        movement = services.record_movement(
            by=shop.cashier,
            register=shop.register,
            kind="handover",
            amount="300000",
            receiver=shop.manager,
        )
    assert movement.status == "pending" and movement.transfer_id is None
    assert till(shop) == Decimal("500000.00")  # nothing moved yet
    assert cash.expected_cash(shift) == Decimal("200000.00")  # but it left the till
    # The receiver got a notification with the two buttons (Telegram only: it lives in Needs you).
    note = Notification.objects.get(kind="sales.handover", recipient=shop.manager)
    assert [a["key"] for a in note.actions] == ["received", "not_received"]
    with pytest.raises(DomainError):
        services.confirm_handover(movement, by=shop.owner)  # only the receiver
    confirmed = services.confirm_handover(movement, by=shop.manager)
    assert confirmed.status == "done" and confirmed.transfer_id is not None
    holder = finance.account_for_holder(shop.company, shop.manager)
    assert till(shop) == Decimal("200000.00")
    holder.refresh_from_db()
    assert holder.balance == Decimal("300000.00")
    note.refresh_from_db()
    assert note.acted_at is not None  # the buttons are settled
    with pytest.raises(DomainError):
        services.confirm_handover(movement, by=shop.manager)


def test_a_declined_handover_tells_the_owners(shop, shift, django_capture_on_commit_callbacks):
    movement = services.record_movement(
        by=shop.cashier,
        register=shop.register,
        kind="handover",
        amount="300000",
        receiver=shop.manager,
    )
    with django_capture_on_commit_callbacks(execute=True):
        services.decline_handover(movement, by=shop.manager, reason="Never got it")
    movement.refresh_from_db()
    assert movement.status == "declined" and movement.transfer_id is None
    alert = Notification.objects.get(kind="sales.handover_declined", recipient=shop.owner)
    assert alert.severity == "critical"
    assert not Notification.objects.filter(
        kind="sales.handover_declined", recipient=shop.manager
    ).exists()


def test_safe_and_bank_movements_are_transfers(shop, shift):
    to_safe = services.record_movement(
        by=shop.cashier, register=shop.register, kind="to_safe", amount="400000"
    )
    safe = finance.account_for_branch(shop.branch)
    safe.refresh_from_db()
    assert safe.balance == Decimal("400000.00")
    services.record_movement(
        by=shop.cashier, register=shop.register, kind="from_safe", amount="100000"
    )
    safe.refresh_from_db()
    assert safe.balance == Decimal("300000.00")
    bank = finance.create_account(shop.company, by=shop.owner, kind="bank", name="Kapitalbank")
    services.record_movement(
        by=shop.manager, register=shop.register, kind="to_bank", amount="150000", to_account=bank
    )
    bank.refresh_from_db()
    assert bank.balance == Decimal("150000.00")
    assert to_safe.transfer.source_type == "sales.cashmovement"
    assert cash.expected_cash(shift) == Decimal("500000.00") - 400000 + 100000 - 150000
    with pytest.raises(DomainError):
        services.record_movement(
            by=shop.manager,
            register=shop.register,
            kind="to_bank",
            amount="1",
            to_account=shop.register.cash_account,
        )


def test_voiding_a_movement_on_a_closed_shift_moves_the_difference(shop, shift):
    payout = services.record_movement(
        by=shop.cashier,
        register=shop.register,
        kind="payout",
        amount="100000",
        reason="Taxi",
        category="transport",
    )
    closed = services.close_shift(
        shift,
        by=shop.cashier,
        payments=[PaymentLine(shop.method("cash"), Decimal("1000000"))],
        counted_cash="1400000",
        z_photo=jpeg(),
    )
    assert closed.difference == Decimal("0.00")
    services.void_movement(payout, by=shop.manager, reason="Entered twice")
    closed.refresh_from_db()
    payout.refresh_from_db()
    assert payout.status == "void"
    assert Transaction.objects.get(pk=payout.transaction_id).status == "void"
    assert closed.expected_cash == Decimal("1500000.00") and closed.difference == Decimal(
        "-100000.00"
    )
    diff = Transaction.objects.get(
        source_type="sales.cashshift",
        source_id=closed.pk,
        source_key="diff",
        status__in=LIVE_STATUSES,
    )
    assert diff.amount == Decimal("-100000.00")
    assert till(shop) == Decimal("1400000.00")


def test_big_payouts_alert_the_managers(shop, shift, django_capture_on_commit_callbacks):
    SalesSettings.objects.filter(company=shop.company).update(big_payout_alert=Decimal("1000000"))
    with django_capture_on_commit_callbacks(execute=True):
        services.record_movement(
            by=shop.cashier,
            register=shop.register,
            kind="payout",
            amount="1500000",
            reason="Rent",
            category="rent",
        )
    assert Notification.objects.filter(kind="sales.big_payout", recipient=shop.manager).exists()
    assert not Notification.objects.filter(kind="sales.big_payout", recipient=shop.cashier).exists()


def test_handover_to_yourself_is_refused(shop, shift):
    with pytest.raises(DomainError):
        services.record_movement(
            by=shop.cashier,
            register=shop.register,
            kind="handover",
            amount="1",
            receiver=shop.cashier,
        )


# Single receipts ----------------------------------------------------------------------------


def test_receipts_in_a_shift_fill_its_totals_at_close(shop, shift):
    SalesSettings.objects.filter(company=shop.company).update(mode=SalesSettings.Mode.RECEIPTS)
    services.record_sale(by=shop.cashier, payments=[(shop.method("cash"), "45000")])
    services.record_sale(
        by=shop.cashier, payments=[(shop.method("cash"), "30000"), (shop.method("click"), "20000")]
    )
    refund = services.record_sale(
        by=shop.cashier, kind=Sale.Kind.REFUND, payments=[(shop.method("cash"), "5000")]
    )
    gone = services.record_sale(by=shop.cashier, payments=[(shop.method("cash"), "99000")])
    services.void_sale(gone, by=shop.manager, reason="Mistake")
    assert refund.shift_id == shift.pk
    assert cash.expected_cash(shift) == Decimal("570000.00")
    # Nothing books per receipt inside a shift: the shift's totals do at close.
    assert not Transaction.objects.filter(source_type="sales.sale").exists()
    closed = services.close_shift(
        shift, by=shop.cashier, counted_cash="570000", z_photo=jpeg(), terminal_photo=jpeg()
    )
    totals = {
        p.method.system_code: (p.sales, p.refunds) for p in closed.payments.select_related("method")
    }
    assert totals == {
        "cash": (Decimal("75000.00"), Decimal("5000.00")),
        "click": (Decimal("20000.00"), Decimal("0.00")),
    }
    assert closed.difference == Decimal("0.00")
    with pytest.raises(DomainError):
        services.void_sale(refund, by=shop.manager, reason="too late")


def test_a_dashboard_receipt_books_on_its_own(shop):
    sale = services.record_sale(
        by=shop.manager,
        payments=[(shop.method("cash"), "120000"), (shop.method("payme"), "80000")],
        branch=shop.branch,
        source=Sale.Source.DASHBOARD,
    )
    rows = Transaction.objects.filter(
        source_type="sales.sale", source_id=sale.pk, status__in=LIVE_STATUSES
    )
    assert sorted(rows.values_list("amount", flat=True)) == [
        Decimal("80000.00"),
        Decimal("120000.00"),
    ]
    assert sale.total == Decimal("200000.00") and sale.shift_id is None
    services.void_sale(sale, by=shop.manager, reason="Wrong branch")
    assert not Transaction.objects.filter(
        source_type="sales.sale", source_id=sale.pk, status__in=LIVE_STATUSES
    ).exists()


def test_an_app_receipt_needs_an_open_shift(shop):
    with pytest.raises(DomainError):
        services.record_sale(by=shop.cashier, payments=[(shop.method("cash"), "1000")])
