"""The operational scan sends each alert once, at the right moment, and reads attendance's
check-ins only when that module registered its branch facts; the evening post goes out once."""

from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

import pytest

from apps.companies.models import Branch
from apps.console import registry
from apps.inbox.models import Notification
from apps.sales import scan, services
from apps.sales.models import SalesSettings
from apps.sales.tests.factories import open_and_close
from apps.timeoff.models import Holiday

TASHKENT = ZoneInfo("Asia/Tashkent")


@pytest.fixture
def hours(shop):
    Branch.objects.filter(pk__in=[shop.branch.pk, shop.other_branch.pk]).update(
        opens_at=time(9, 0), closes_at=time(21, 0), open_weekdays=[0, 1, 2, 3, 4, 5, 6]
    )
    shop.branch.refresh_from_db()
    shop.other_branch.refresh_from_db()
    return shop


def moment(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=TASHKENT)


def alerts(kind: str):
    return Notification.objects.filter(kind=kind)


def test_branch_not_opened_once_and_only_in_its_window(hours):
    shop = hours
    scan.scan_company(shop.company, moment(21, 9, 5))  # within the grace
    assert not alerts("sales.branch_not_opened").exists()
    scan.scan_company(shop.company, moment(21, 9, 15))
    scan.scan_company(shop.company, moment(21, 9, 20))
    sent = alerts("sales.branch_not_opened")
    # Two branches, each to the owner and the manager, once.
    assert sent.count() == 4
    assert set(sent.values_list("recipient_id", flat=True)) == {shop.owner.pk, shop.manager.pk}
    assert sent.first().severity == "critical"
    scan.scan_company(shop.company, moment(21, 13, 0))  # past the window: nothing new
    assert alerts("sales.branch_not_opened").count() == 4


def test_an_opened_branch_a_holiday_and_a_day_off_stay_quiet(hours):
    shop = hours

    def sent_for(branch, day):
        return alerts("sales.branch_not_opened").filter(
            dedupe_key=f"sales.not_opened:{branch.pk}:2026-10-{day:02d}"
        )

    # Wednesday: Chilonzor opened on time, Yunusobod didn't.
    services.open_shift(
        by=shop.cashier, register=shop.register, opening_float="0", now=moment(21, 8, 55)
    )
    scan.scan_company(shop.company, moment(21, 9, 30))
    assert not sent_for(shop.branch, 21).exists()
    assert sent_for(shop.other_branch, 21).exists()
    # Sunday: Yunusobod doesn't open on Sundays.
    Branch.objects.filter(pk=shop.other_branch.pk).update(open_weekdays=[0, 1, 2, 3, 4, 5])
    scan.scan_company(shop.company, moment(25, 9, 30))
    assert not sent_for(shop.other_branch, 25).exists()
    # A holiday: nobody is expected.
    Holiday.objects.create(company=shop.company, date=moment(22, 0).date(), name="Mustaqillik")
    scan.scan_company(shop.company, moment(22, 9, 30))
    assert not sent_for(shop.branch, 22).exists() and not sent_for(shop.other_branch, 22).exists()


def test_attendance_check_ins_count_only_when_attendance_registered_facts(
    hours, isolated_registries
):
    shop = hours
    shop.company.features = [*shop.company.features, "attendance"]
    shop.company.save(update_fields=["features"])
    with mock.patch.object(registry.BRANCH_FACTS, "get", return_value=None):
        scan.scan_company(shop.company, moment(21, 9, 15))
    assert alerts("sales.branch_not_opened").filter(target_id=shop.branch.pk).exists()
    Notification.objects.all().delete()

    def facts(company, day, now, branch_ids):
        return {
            branch_id: {
                "rostered": 2,
                "checked_in": 1,
                "first_check_in": "2026-10-21T08:51:00+05:00",
            }
            for branch_id in branch_ids
            if branch_id == shop.branch.pk
        }

    registry.BRANCH_FACTS.add(registry.BranchFactsProvider("attendance", None, None, None, facts))
    scan.scan_company(shop.company, moment(21, 9, 15))
    assert not alerts("sales.branch_not_opened").filter(target_id=shop.branch.pk).exists()
    assert alerts("sales.branch_not_opened").filter(target_id=shop.other_branch.pk).exists()


def test_a_till_left_open_after_closing(hours):
    shop = hours
    shift = services.open_shift(
        by=shop.cashier, register=shop.register, opening_float="0", now=moment(21, 8, 55)
    )
    scan.scan_company(shop.company, moment(21, 21, 30))
    assert not alerts("sales.shift_not_closed").exists()
    scan.scan_company(shop.company, moment(21, 22, 5))
    scan.scan_company(shop.company, moment(21, 22, 10))
    assert alerts("sales.shift_not_closed").count() == 2  # owner and manager
    [mine] = alerts("sales.till_open")
    assert mine.recipient_id == shop.cashier.pk and mine.app_screen == "kassa"
    assert mine.target_id == shift.pk


def test_unconfirmed_handovers_and_cash_over_the_limit(hours):
    shop = hours
    services.open_shift(by=shop.cashier, register=shop.register, opening_float="0")
    movement = services.record_movement(
        by=shop.cashier,
        register=shop.register,
        kind="handover",
        amount="400000",
        receiver=shop.owner,
    )
    later = movement.created_at + timedelta(hours=3)
    scan.scan_company(shop.company, later)
    scan.scan_company(shop.company, later + timedelta(minutes=5))
    late = alerts("sales.handover_late")
    assert late.count() == 2 and shop.cashier.pk not in set(
        late.values_list("recipient_id", flat=True)
    )

    Branch.objects.filter(pk=shop.branch.pk).update(cash_limit=Decimal("50000"))
    services.record_movement(
        by=shop.cashier, register=shop.register, kind="to_safe", amount="1", reason="x"
    )
    from apps.finance import services as finance

    safe = finance.account_for_branch(shop.branch)
    finance.record_transaction(
        shop.company,
        by=shop.owner,
        kind="opening",
        amount="500000",
        occurred_on=moment(1, 12).date(),
        account=safe,
    )
    scan.scan_company(shop.company, moment(21, 21, 40))
    scan.scan_company(shop.company, moment(21, 21, 45))
    assert alerts("sales.cash_over_limit").count() == 2


def test_the_evening_post_goes_out_once_after_closing(hours):
    shop = hours
    closed = open_and_close(shop)
    day = closed.business_day
    late = datetime.combine(day, time(21, 40), tzinfo=TASHKENT)
    with mock.patch("apps.sales.scan.broadcast") as broadcast:
        assert scan.post_evening(shop.company, late - timedelta(hours=2)) == 0
        assert scan.post_evening(shop.company, late) == 1
        assert scan.post_evening(shop.company, late + timedelta(minutes=15)) == 0
    [(args, _kwargs)] = broadcast.call_args_list
    assert args[1] == "sales" and "1 500 000" in args[2]
    assert SalesSettings.objects.get(company=shop.company).evening_posted_on == day


def test_a_closed_shift_posts_to_the_cash_groups(shop, django_capture_on_commit_callbacks):
    with (
        mock.patch("apps.sales.alerts.broadcast") as broadcast,
        django_capture_on_commit_callbacks(execute=True),
    ):
        open_and_close(shop, counted="1180000")
    [(args, kwargs)] = broadcast.call_args_list
    assert args[1] == "cash" and kwargs["branch_id"] == shop.branch.pk
    assert "CHL-1" in args[2]
    # The difference was above tolerance: critical, to the managers (not the cashier).
    difference = alerts("sales.cash_difference")
    assert set(difference.values_list("recipient_id", flat=True)) == {
        shop.owner.pk,
        shop.manager.pk,
    }


def test_closing_queues_the_daily_rollup(shop, django_capture_on_commit_callbacks):
    from apps.sales.models import DailySales

    with django_capture_on_commit_callbacks(execute=True):
        shift = services.open_shift(by=shop.cashier, register=shop.register, opening_float="0")
    from apps.sales.services import PaymentLine
    from apps.sales.tests.factories import jpeg

    with django_capture_on_commit_callbacks(execute=True):
        services.close_shift(
            shift,
            by=shop.cashier,
            payments=[PaymentLine(shop.method("cash"), Decimal("700000"))],
            counted_cash="700000",
            z_photo=jpeg(),
        )
    row = DailySales.objects.get(branch=shop.branch, day=shift.business_day)
    assert row.net == Decimal("700000.00") and row.shifts == 1
