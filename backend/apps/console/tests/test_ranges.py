"""Date ranges for analytics, in the company's own calendar."""

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from apps.console.ranges import MAX_DAYS, Range, RangeError, parse_range

TASHKENT = SimpleNamespace(timezone="Asia/Tashkent")
# 20 Oct 2026 21:30 UTC is already Wednesday 21 Oct in Tashkent (UTC+5).
LATE_EVENING = datetime(2026, 10, 20, 21, 30, tzinfo=UTC)
NOON = datetime(2026, 10, 20, 7, 0, tzinfo=UTC)  # Tuesday 20 Oct, 12:00 in Tashkent


def parse(**params) -> Range:
    return parse_range(params, TASHKENT, NOON)


def test_today_is_the_companys_today():
    assert parse_range({"preset": "today"}, TASHKENT, LATE_EVENING).start == date(2026, 10, 21)


def test_the_default_is_this_month_to_date():
    assert parse() == Range(date(2026, 10, 1), date(2026, 10, 20))


@pytest.mark.parametrize(
    ("preset", "start", "end"),
    [
        ("today", date(2026, 10, 20), date(2026, 10, 20)),
        ("yesterday", date(2026, 10, 19), date(2026, 10, 19)),
        ("week", date(2026, 10, 19), date(2026, 10, 20)),
        ("last_week", date(2026, 10, 12), date(2026, 10, 18)),
        ("month", date(2026, 10, 1), date(2026, 10, 20)),
        ("last_month", date(2026, 9, 1), date(2026, 9, 30)),
        ("last_30", date(2026, 9, 21), date(2026, 10, 20)),
        ("quarter", date(2026, 10, 1), date(2026, 10, 20)),
        ("year", date(2026, 1, 1), date(2026, 10, 20)),
    ],
)
def test_presets(preset, start, end):
    span = parse(preset=preset)

    assert (span.start, span.end) == (start, end)


@pytest.mark.parametrize(
    ("preset", "compare_start", "compare_end"),
    [
        ("today", date(2026, 10, 19), date(2026, 10, 19)),
        ("week", date(2026, 10, 12), date(2026, 10, 13)),  # Mon-Tue of last week
        ("last_week", date(2026, 10, 5), date(2026, 10, 11)),
        ("month", date(2026, 9, 1), date(2026, 9, 20)),  # the plan's example
        ("last_month", date(2026, 8, 1), date(2026, 8, 31)),  # the whole month before
        ("last_30", date(2026, 8, 22), date(2026, 9, 20)),
        ("quarter", date(2026, 7, 1), date(2026, 7, 20)),
        ("year", date(2025, 1, 1), date(2025, 10, 20)),
    ],
)
def test_compare_with_the_previous_period(preset, compare_start, compare_end):
    span = parse(preset=preset, compare="prev")

    assert (span.compare_start, span.compare_end) == (compare_start, compare_end)


def test_compare_with_last_year():
    span = parse(preset="month", compare="year")

    assert (span.compare_start, span.compare_end) == (date(2025, 10, 1), date(2025, 10, 20))


def test_month_ends_are_clipped():
    span = parse(**{"from": "2026-03-01", "to": "2026-03-31", "compare": "year"})
    assert span.compare_end == date(2025, 3, 31)

    leap = parse(**{"from": "2028-02-29", "to": "2028-02-29", "compare": "year"})
    assert leap.compare_start == date(2027, 2, 28)


def test_a_custom_range_compares_with_the_days_just_before():
    span = parse(**{"from": "2026-10-10", "to": "2026-10-14", "compare": "prev"})

    assert span == Range(
        date(2026, 10, 10), date(2026, 10, 14), date(2026, 10, 5), date(2026, 10, 9)
    )
    assert span.days == 5


def test_to_defaults_to_today():
    assert parse(**{"from": "2026-10-15"}).end == date(2026, 10, 20)


def test_as_dict_is_the_analytics_shape():
    span = parse(preset="month", compare="prev")

    assert span.as_dict() == {
        "range": {"from": "2026-10-01", "to": "2026-10-20"},
        "compare": {"from": "2026-09-01", "to": "2026-09-20"},
    }
    assert parse().as_dict()["compare"] is None


@pytest.mark.parametrize(
    "params",
    [
        {"preset": "fortnight"},
        {"compare": "decade"},
        {"from": "20.10.2026"},
        {"to": "2026-10-20"},
        {"from": "2026-10-20", "to": "2026-10-01"},
        {"preset": "month", "from": "2026-10-01"},
        {"from": "2020-01-01", "to": "2026-01-01"},
    ],
)
def test_bad_parameters_raise(params):
    with pytest.raises(RangeError):
        parse(**params)


def test_three_years_is_the_limit():
    assert MAX_DAYS == 366 * 3


def test_a_month_end_compares_with_the_end_of_the_shifted_month():
    span = parse(**{"from": "2026-09-01", "to": "2026-09-30", "compare": "year"})
    assert span.compare_end == date(2025, 9, 30)

    span = parse(**{"from": "2024-02-01", "to": "2024-02-29", "compare": "year"})
    assert (span.compare_start, span.compare_end) == (date(2023, 2, 1), date(2023, 2, 28))
