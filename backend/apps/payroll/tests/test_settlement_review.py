"""Money defects an independent review of the final settlement found (2026-11-07), each pinned
by a test (docs/PLAN-OWNER.md §3.17)."""

from datetime import date
from decimal import Decimal as D

import pytest

from apps.payroll import services
from apps.payroll.models import PayrollRun, PayslipLine
from apps.payroll.tests.conftest import local
from apps.payroll.tests.test_settlement import HIRED, leave

pytestmark = pytest.mark.django_db
Kind = PayslipLine.Kind
DONE = (PayrollRun.Status.FINALIZED, PayrollRun.Status.PAID)


@pytest.fixture
def team(monkeypatch, staff, freeze):
    """Ali 5 200 000 a month and Sara 4 680 000, both since 1 October 2025 (fixed employment
    dates: a test puts someone's last day in `staff.ends`); the clock at 10:00 on 15 October."""
    staff.ends = {}

    def employment_dates(company, member_ids):
        return {pk: (HIRED, staff.ends.get(pk)) for pk in member_ids}

    monkeypatch.setattr("apps.hr.queries.employment_dates", employment_dates)
    freeze(local(date(2026, 10, 15), 10))
    services.set_pay(staff.ali, by=None, effective_from=HIRED, amount="5200000")
    services.set_pay(staff.sara, by=None, effective_from=HIRED, amount="4680000")
    return staff


def finalized_october_then_ali_leaves(shop, staff, freeze):
    """October finalized on the 26th with Ali's payslip; Ali's last day is the 28th and his
    final run (after the regular one) is prepared on the 29th."""
    freeze(local(date(2026, 10, 26), 10))
    regular = services.create_run(shop, by=staff.accountant, period="2026-10")
    services.finalize_run(regular, by=staff.owner)
    freeze(local(date(2026, 10, 29), 10))
    leave(staff.ali)
    staff.ends[staff.ali.pk] = date(2026, 10, 28)
    final = services.create_final_run(
        staff.ali, by=staff.accountant, last_day=date(2026, 10, 28), leave_days="2"
    )
    assert final.after_regular
    return regular, final


def test_a_bonus_is_paid_once_when_october_is_reopened_around_the_final_run(shop, team, freeze):
    """October paid Ali's bonus; reopened, the bonus is open again, so the final payslip (after
    the regular one) takes it when it is finalized first. Finalized again, October must not
    pay it a second time."""
    staff = team
    freeze(local(date(2026, 10, 20), 10))
    bonus = services.propose(
        staff.ali,
        by=staff.accountant,
        kind="bonus",
        amount="300000",
        reason="Inventory count",
        period="2026-10",
        approve=True,
    )
    regular, final = finalized_october_then_ali_leaves(shop, staff, freeze)
    assert not final.payslips.get().lines.filter(adjustment=bonus).exists()

    services.reopen_run(regular, by=staff.owner, reason="Sara's overtime")
    services.finalize_run(final, by=staff.owner)
    services.finalize_run(regular, by=staff.owner)

    paid = PayslipLine.objects.filter(adjustment=bonus, payslip__run__status__in=DONE)
    assert sum(line.amount for line in paid) == D("300000.00")
