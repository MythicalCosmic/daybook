"""The depreciation engine, checked against sums worked out by hand (NSBU No. 5 methods)."""

from datetime import date
from decimal import Decimal as D

from apps.assets.engine import Change, Facts, schedule, tax_schedule


def total(rows):
    return sum((row.amount for row in rows), D(0))


def amounts(rows):
    return [row.amount for row in rows]


def test_straight_line_from_the_month_after_it_is_put_into_service():
    rows = schedule(
        Facts(cost=D(12_000_000), life_months=60, method="straight_line", start=date(2026, 3, 15))
    )
    assert len(rows) == 60
    assert rows[0].month == date(2026, 4, 1)
    assert rows[-1].month == date(2031, 3, 1)
    assert set(amounts(rows)) == {D("200000.00")}
    assert rows[-1].closing == 0 and "final" in rows[-1].notes


def test_rounding_lands_on_the_last_month():
    rows = schedule(
        Facts(cost=D(10_000_000), life_months=36, method="straight_line", start=date(2026, 1, 10))
    )
    assert len(rows) == 36
    assert total(rows) == D("10000000.00")
    assert all(abs(row.amount - D("277777.78")) <= D("0.01") for row in rows)


def test_daily_rule_prorates_the_first_and_last_months():
    rows = schedule(
        Facts(
            cost=D(12_000_000),
            life_months=12,
            method="straight_line",
            start=date(2026, 1, 16),
            rule="daily",
        )
    )
    assert rows[0].month == date(2026, 1, 1)
    assert rows[0].amount == D("516129.03")  # 16 of January's 31 days
    assert rows[1].amount == D("1000000.00")
    assert rows[-1].month == date(2027, 1, 1)
    assert rows[-1].amount == D("483870.97")  # the other 15 days
    assert total(rows) == D("12000000.00")


def test_double_declining_balance_switches_to_straight_line_and_stops_at_the_residual_value():
    rows = schedule(
        Facts(
            cost=D(10_000_000),
            salvage=D(1_000_000),
            life_months=60,
            method="declining",
            start=date(2026, 1, 5),
        )
    )
    assert amounts(rows)[:3] == [D("333333.33"), D("322222.22"), D("311481.48")]
    assert len(rows) == 60
    # Never rising (a tiyin of rounding aside, once it runs straight line).
    pairs = zip(amounts(rows), amounts(rows)[1:], strict=False)
    assert all(earlier + D("0.01") >= later for earlier, later in pairs)
    assert rows[-1].closing == D("1000000.00")
    assert total(rows) == D("9000000.00")


def test_sum_of_the_years_digits_gives_each_year_its_share():
    rows = schedule(
        Facts(cost=D(1_500_000), life_months=60, method="sum_of_years", start=date(2025, 12, 5))
    )
    years = [total(rows[index * 12 : (index + 1) * 12]) for index in range(5)]
    assert years == [D(500_000), D(400_000), D(300_000), D(200_000), D(100_000)]


def test_sum_of_the_years_with_a_partial_last_year_still_adds_up():
    rows = schedule(
        Facts(cost=D(1_000_000), life_months=30, method="sum_of_years", start=date(2025, 12, 5))
    )
    assert len(rows) == 30
    assert total(rows) == D("1000000.00")
    assert rows[-1].closing == 0


def test_units_of_output_follow_the_units_recorded():
    rows = schedule(
        Facts(
            cost=D(6_000_000),
            life_months=None,
            method="units",
            start=date(2026, 3, 1),
            total_units=D(100_000),
            changes=(
                Change("usage", date(2026, 4, 10), units=D(2000)),
                Change("usage", date(2026, 5, 3), units=D(3000)),
            ),
        )
    )
    assert amounts(rows) == [D("120000.00"), D("180000.00")]


def test_an_improvement_depreciates_over_the_life_that_is_left():
    rows = schedule(
        Facts(
            cost=D(12_000_000),
            life_months=60,
            method="straight_line",
            start=date(2026, 3, 15),
            changes=(Change("addition", date(2026, 10, 15), amount=D(1_200_000)),),
        )
    )
    october, november = rows[6], rows[7]
    assert october.month == date(2026, 10, 1) and october.amount == D("200000.00")
    assert october.closing == D("11800000.00")  # 12 000 000 - 7 x 200 000 + 1 200 000
    assert november.amount == D("222641.51")  # 11 800 000 over the 53 months left
    assert total(rows) == D("13200000.00")
    assert len(rows) == 60


def test_a_new_estimate_applies_from_the_first_month_not_posted():
    posted = {date(2026, month, 1): D("200000.00") for month in range(4, 10)}
    rows = schedule(
        Facts(
            cost=D(12_000_000),
            life_months=60,
            method="straight_line",
            start=date(2026, 3, 15),
            posted=posted,
            # Recorded in July, when July was already posted: it starts in October.
            changes=(Change("estimate", date(2026, 7, 20), life_months=84),),
        )
    )
    assert all(row.posted for row in rows[:6])
    assert rows[6].month == date(2026, 10, 1)
    # 10 800 000 left over 84 - 6 = 78 months.
    assert rows[6].amount == D("138461.54")
    assert len(rows) == 84
    assert total(rows) == D("12000000.00")


def test_posted_months_are_history_even_when_they_differ():
    posted = {date(2026, 4, 1): D("150000.00")}
    rows = schedule(
        Facts(
            cost=D(12_000_000),
            life_months=60,
            method="straight_line",
            start=date(2026, 3, 15),
            posted=posted,
        )
    )
    assert rows[0].amount == D("150000.00") and rows[0].posted
    # The rest spreads what is left: 11 850 000 over 59 months.
    assert rows[1].amount == D("200847.46")
    assert total(rows) == D("12000000.00")


def test_a_write_down_lowers_the_months_after_it():
    rows = schedule(
        Facts(
            cost=D(12_000_000),
            life_months=60,
            method="straight_line",
            start=date(2026, 3, 15),
            changes=(Change("impairment", date(2026, 4, 20), amount=D(5_900_000)),),
        )
    )
    assert rows[0].amount == D("200000.00")
    assert rows[0].closing == D("5900000.00")
    assert rows[1].amount == D("100000.00")  # 5 900 000 over 59 months
    assert rows[-1].closing == 0


def test_mothballing_pauses_depreciation_and_the_life_waits():
    rows = schedule(
        Facts(
            cost=D(12_000_000),
            life_months=60,
            method="straight_line",
            start=date(2026, 3, 15),
            changes=(Change("suspend", date(2026, 6, 20)), Change("resume", date(2026, 8, 2))),
        )
    )
    by_month = {row.month: row.amount for row in rows}
    assert by_month[date(2026, 6, 1)] == D("200000.00")
    assert by_month[date(2026, 7, 1)] == 0
    assert by_month[date(2026, 8, 1)] == 0
    assert by_month[date(2026, 9, 1)] == D("200000.00")
    assert rows[-1].month == date(2031, 5, 1)  # two months later than without the pause
    assert total(rows) == D("12000000.00")


def test_disposal_stops_after_its_month():
    rows = schedule(
        Facts(
            cost=D(12_000_000),
            life_months=60,
            method="straight_line",
            start=date(2026, 3, 15),
            disposed_on=date(2026, 9, 10),
        )
    )
    assert [row.month for row in rows][-1] == date(2026, 9, 1)
    assert len(rows) == 6
    assert rows[-1].closing == D("10800000.00")


def test_disposed_in_the_month_it_started_never_depreciates_on_the_next_month_rule():
    rows = schedule(
        Facts(
            cost=D(1_000_000),
            life_months=12,
            method="straight_line",
            start=date(2026, 3, 1),
            disposed_on=date(2026, 3, 20),
        )
    )
    assert rows == []


def test_old_books_open_the_schedule_with_their_sum():
    rows = schedule(
        Facts(
            cost=D(12_000_000),
            life_months=60,
            method="straight_line",
            start=date(2024, 1, 10),
            opening_accumulated=D(6_000_000),
            opening_month=date(2026, 11, 1),
        )
    )
    # February 2024 … October 2026 were in the old books: 33 months, 27 left.
    assert rows[0].month == date(2026, 11, 1)
    assert len(rows) == 27
    assert rows[0].amount == D("222222.22")
    assert total(rows) == D("6000000.00")


def test_not_depreciated_and_not_in_service_make_no_schedule():
    assert (
        schedule(Facts(cost=D(100), life_months=None, method="none", start=date(2026, 1, 1))) == []
    )
    assert schedule(Facts(cost=D(100), life_months=12, method="straight_line", start=None)) == []


def test_tax_book_is_straight_line_at_the_annual_rate():
    rows = tax_schedule(D(12_000_000), D(40), date(2026, 3, 15), until=date(2030, 1, 1))
    assert rows[0] == (date(2026, 4, 1), D("400000.00"))
    assert len(rows) == 30
    assert sum((amount for _day, amount in rows), D(0)) == D(12_000_000)
