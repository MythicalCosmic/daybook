"""Loan schedule arithmetic (v12, `apps.finance.loan_math`) against examples worked out by hand."""

from datetime import date
from decimal import Decimal as D

import pytest

from apps.finance import loan_math as m

JAN = date(2026, 1, 15)


def test_annuity_matches_the_formula_worked_by_hand():
    # 12 000 000 so‘m at 24 % a year over 12 months: i = 0.02,
    # A = 12 000 000 x 0.02 / (1 - 1.02^-12) = 1 134 715.16 -> 1 134 715 so‘m.
    exact = 12_000_000 * 0.02 / (1 - 1.02**-12)
    assert round(exact, 2) == 1_134_715.16
    rows = m.schedule(principal=D(12_000_000), annual_rate=D(24), months=12, first_due=JAN)
    assert len(rows) == 12
    # First month: interest 2 % of 12 000 000 = 240 000, principal = A - interest.
    assert rows[0].interest == D(240_000)
    assert rows[0].payment == D(1_134_715)
    assert rows[0].principal == D(894_715)
    # Second month: 2 % of 11 105 285 = 222 105.70 -> 222 106, principal 912 609.
    assert rows[1].interest == D(222_106)
    assert rows[1].principal == D(912_609)
    # Every payment but the last is the same; the last closes the loan exactly.
    payments = {row.payment for row in rows[:-1]}
    assert len(payments) == 1
    assert sum(row.principal for row in rows) == D(12_000_000)
    assert m.balances(rows, D(12_000_000))[-1] == 0
    # Due on the 15th of each month.
    assert [row.due_on.month for row in rows] == list(range(1, 13))
    assert {row.due_on.day for row in rows} == {15}


def test_equal_principal_worked_by_hand():
    # 12 000 000 over 12 months at 24 %: 1 000 000 principal each month, interest 2 % of what
    # is left: 240 000, 220 000, ..., 20 000; in all 0.02 x 1 000 000 x (12 + 11 + ... + 1).
    rows = m.schedule(
        principal=D(12_000_000),
        annual_rate=D(24),
        months=12,
        first_due=JAN,
        method=m.EQUAL_PRINCIPAL,
    )
    assert [row.principal for row in rows] == [D(1_000_000)] * 12
    assert [row.interest for row in rows] == [D(240_000 - 20_000 * k) for k in range(12)]
    assert m.totals(rows)["interest"] == D(1_560_000)
    assert m.totals(rows)["payments"] == D(13_560_000)


def test_rounding_to_the_som_never_loses_one():
    # 10 000 000 in three interest-free parts: 3 333 333 + 3 333 333 + 3 333 334.
    rows = m.schedule(principal=D(10_000_000), annual_rate=D(0), months=3, first_due=JAN)
    assert [row.principal for row in rows] == [D(3_333_333), D(3_333_333), D(3_333_334)]
    assert all(row.interest == 0 for row in rows)
    # Every part is whole so‘m, and an awkward amount still adds up exactly.
    rows = m.schedule(
        principal=D(7_777_777), annual_rate=D("19.5"), months=7, first_due=JAN, method=m.ANNUITY
    )
    assert sum(row.principal for row in rows) == D(7_777_777)
    assert all(row.principal == row.principal.quantize(D(1)) for row in rows)
    assert all(row.interest == row.interest.quantize(D(1)) for row in rows)


def test_dollars_round_to_the_cent():
    rows = m.schedule(
        principal=D(1000), annual_rate=D(12), months=3, first_due=JAN, currency="USD", grace=1
    )
    # A grace month pays interest only (1 % of 1 000 = 10.00); the rest is an annuity.
    assert rows[0].principal == 0 and rows[0].interest == D("10.00")
    assert sum(row.principal for row in rows) == D(1000)
    assert rows[1].interest == D("10.00")


def test_interest_free_grace_month_is_no_payment():
    rows = m.schedule(principal=D(900), annual_rate=D(0), months=3, first_due=JAN, grace=1)
    assert len(rows) == 2
    assert [row.principal for row in rows] == [D(450), D(450)]


def test_interest_by_actual_days():
    # 36 500 000 at 10 %: 10 000 so‘m a day. From 1 January to the first payment on 15 January
    # is 14 days: 140 000; to 15 February 31 days on what is left.
    rows = m.schedule(
        principal=D(36_500_000),
        annual_rate=D(10),
        months=2,
        first_due=JAN,
        method=m.EQUAL_PRINCIPAL,
        basis=m.ACTUAL,
        start=date(2026, 1, 1),
    )
    assert rows[0].interest == D(140_000)
    assert rows[1].interest == D(155_000)  # 18 250 000 x 10 % x 31 / 365


def test_month_ends_hold_the_day():
    days = m.due_days(date(2026, 1, 31), 4)
    assert days == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]


def test_early_repayment_lowers_the_payments():
    rows = m.recalculate(
        balance=D(6_000_000),
        annual_rate=D(24),
        method=m.EQUAL_PRINCIPAL,
        basis=m.MONTHLY,
        next_due=date(2026, 8, 15),
        remaining=6,
        since=date(2026, 7, 20),
    )
    assert [row.principal for row in rows] == [D(1_000_000)] * 6
    assert rows[0].interest == D(120_000)


def test_early_repayment_shortens_the_term():
    # 6 000 000 left; keep 2 000 000 of principal a month: three payments instead of six.
    rows = m.recalculate(
        balance=D(6_000_000),
        annual_rate=D(24),
        method=m.EQUAL_PRINCIPAL,
        basis=m.MONTHLY,
        next_due=date(2026, 8, 15),
        remaining=6,
        since=date(2026, 7, 20),
        mode=m.REDUCE_TERM,
        payment=D(2_000_000),
    )
    assert [row.principal for row in rows] == [D(2_000_000)] * 3
    # An annuity keeps its payment and ends sooner too.
    rows = m.recalculate(
        balance=D(3_000_000),
        annual_rate=D(24),
        method=m.ANNUITY,
        basis=m.MONTHLY,
        next_due=date(2026, 8, 15),
        remaining=10,
        since=date(2026, 7, 20),
        mode=m.REDUCE_TERM,
        payment=D(1_134_715),
    )
    assert len(rows) == 3
    assert sum(row.principal for row in rows) == D(3_000_000)


def test_typed_schedule_is_checked():
    rows = [
        m.Row(date(2026, 2, 1), D(500), D(10)),
        m.Row(date(2026, 3, 1), D(500), D(5)),
    ]
    assert m.check_rows(rows, D(1000)) == rows
    with pytest.raises(m.ScheduleError):
        m.check_rows(rows, D(999))
    with pytest.raises(m.ScheduleError):
        m.check_rows(list(reversed(rows)), D(1000))
    with pytest.raises(m.ScheduleError):
        m.check_rows([m.Row(date(2026, 2, 1), D(0), D(0))], D(0))


@pytest.mark.parametrize(
    "terms",
    [
        {"principal": D(0)},
        {"months": 0},
        {"grace": 12},
        {"annual_rate": D(101)},
    ],
)
def test_terms_that_make_no_schedule(terms):
    base = {"principal": D(1000), "annual_rate": D(10), "months": 12, "first_due": JAN}
    with pytest.raises(m.ScheduleError):
        m.schedule(**{**base, **terms})
