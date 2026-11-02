"""A run's payslip table adds up. Each row's parts, signed like the lines (base pay, extra pay,
bonuses, fines, advances, taxes, expenses paid back), are exactly its net for every kind of line
a payslip can have, so the run page can show them as they come."""

from datetime import date
from decimal import Decimal

import pytest

from apps.finance import services as finance
from apps.payroll import services
from apps.payroll.models import Advance, PayslipLine
from apps.payroll.tests.conftest import OCTOBER, local
from apps.payroll.tests.test_golden import absent, record
from apps.timeoff.queries import LeaveDay, LeaveSummary

pytestmark = pytest.mark.django_db

D = Decimal
Kind = PayslipLine.Kind
PARTS = ("base_pay", "extras", "bonuses", "fines", "advances", "taxes_withheld", "reimbursements")


def table(owner, company, run) -> dict[str, dict]:
    """The run's payslip rows through the owner API, by first name."""
    response = owner.get(
        f"/api/v1/owner/companies/{company.pk}/payroll/runs/{run.pk}/payslips/?page_size=200"
    )
    assert response.status_code == 200, response.data
    return {row["member"]["name"].split()[0]: row for row in response.data["results"]}


def adds_up(row) -> bool:
    return sum((D(row[name]) for name in PARTS), D(0)) == D(row["net"])


def summed(payslip, *kinds) -> Decimal:
    return sum((line.amount for line in payslip.lines.all() if line.kind in kinds), D(0))


def test_every_kind_of_line_is_in_exactly_one_part():
    named = [kind for kinds in PayslipLine.ROW_PARTS.values() for kind in kinds]
    assert len(named) == len(set(named))
    assert set(named) | {Kind.MANUAL} == set(Kind.values)
    # A line added by hand goes by its sign.
    assert PayslipLine.row_part(Kind.MANUAL, D("50000")) == "extras"
    assert PayslipLine.row_part(Kind.MANUAL, D("-30000")) == "fines"


@pytest.fixture
def month(freeze, monkeypatch, shop, staff, cash):
    """October with every sort of line. Ali, monthly 4 500 000 (173 076,92 a day): a holiday
    shift, overtime, two night shifts, a day absent, a bonus, a fine, an advance repaid. Sara,
    daily: two days of paid leave and expenses paid back. Vali, hourly, with overtime. Net
    rounded to 1 000."""
    freeze(local(date(2026, 11, 3), 10))
    monkeypatch.setattr(
        "apps.hr.queries.employment_dates",
        lambda company, ids: {pk: (date(2025, 6, 1), None) for pk in ids},
    )
    leave = {
        staff.sara.pk: tuple(
            LeaveDay(date(2026, 10, day), 1, "annual", True, 100) for day in (12, 13)
        )
    }
    monkeypatch.setattr(
        "apps.timeoff.queries.leave_summary",
        lambda company, start, end, *, member_ids=None: {
            pk: LeaveSummary(pk, tuple(day for day in days if start <= day.day <= end))
            for pk, days in leave.items()
            if member_ids is None or pk in set(member_ids)
        },
    )
    effective = date(2026, 1, 1)
    services.set_pay(staff.ali, by=None, effective_from=effective, amount=D("4500000"))
    services.set_pay(
        staff.sara, by=None, effective_from=effective, amount=D("200000"), pay_type="daily"
    )
    services.set_pay(
        staff.vali, by=None, effective_from=effective, amount=D("25000"), pay_type="hourly"
    )
    ali, sara, vali = staff.ali, staff.sara, staff.vali
    record(ali, date(2026, 10, 1))  # the holiday of 1 October
    record(ali, date(2026, 10, 12), (9, 0), (22, 0), overtime=240)
    for day in (5, 6):
        record(ali, date(2026, 10, day), (22, 0), (6, 0))
    absent(ali, date(2026, 10, 14))
    for kind, amount in (("bonus", "300000"), ("fine", "50000")):
        services.propose(
            ali,
            by=staff.owner,
            kind=kind,
            amount=amount,
            reason="October",
            period=OCTOBER,
            approve=True,
        )
    advance = services.create_advance(
        ali, by=staff.owner, amount="1000000", installments=2, first_period="2026-11"
    )
    Advance.objects.filter(pk=advance.pk).update(first_period=OCTOBER)
    advance.refresh_from_db()
    services.pay_advance(advance, by=staff.owner, account=cash, paid_on=date(2026, 10, 20))
    for day in (5, 6, 7):
        record(sara, date(2026, 10, day))
    finance.open_debt(
        shop,
        by=staff.owner,
        direction="payable",
        kind="reimbursement",
        amount=D("150000"),
        currency="UZS",
        issued_on=date(2026, 10, 10),
        membership=sara,
        category="other_expense",
        description="Printer paper",
    )
    record(vali, date(2026, 10, 5), (9, 0), (19, 0), worked=600, overtime=120)
    return staff


def test_each_row_adds_up_to_its_net(shop, month, owner_api):
    staff = month
    run = services.create_run(shop, by=staff.owner, period="2026-10")
    ali = run.payslips.get(membership=staff.ali)
    services.set_manual_lines(
        ali,
        by=staff.owner,
        lines=[
            {"label": "Taxi to the warehouse", "amount": "50000"},
            {"label": "Shortage", "amount": "-30000"},
        ],
    )
    rows = table(owner_api(staff.owner), shop, run)
    assert set(rows) == {"Ali", "Sara", "Vali"}
    assert all(adds_up(row) for row in rows.values()), rows

    ali.refresh_from_db()
    row = rows["Ali"]
    extra = summed(ali, Kind.HOLIDAY_WORK, Kind.OVERTIME, Kind.NIGHT_WORK, Kind.ROUNDING)
    assert summed(ali, Kind.HOLIDAY_WORK) > 0 and summed(ali, Kind.NIGHT_WORK) > 0
    assert summed(ali, Kind.PRORATION) < 0 and summed(ali, Kind.ROUNDING) != 0
    assert D(row["extras"]) == extra + D("50000")
    assert row["bonuses"] == "300000.00"
    assert row["fines"] == "-80000.00"  # the fine and the shortage added by hand
    assert row["advances"] == "-500000.00"
    assert row["base_pay"] == f"{summed(ali, Kind.BASE, Kind.PRORATION):.2f}"

    sara = run.payslips.get(membership=staff.sara)
    assert summed(sara, Kind.LEAVE_COMPENSATION) == D("400000.00")
    assert rows["Sara"]["reimbursements"] == "150000.00"
    assert D(rows["Sara"]["extras"]) == D("400000.00") + summed(sara, Kind.ROUNDING)
    assert D(rows["Vali"]["extras"]) > 0  # his overtime
    # The net is whole thousands; what rounding took or gave is inside extras.
    assert all(D(row["net"]) % 1000 == 0 for row in rows.values())


def test_with_taxes_withheld(shop, month, owner_api):
    staff = month
    services.update_settings(shop, by=staff.owner, taxes_enabled=True, amounts_are_net=False)
    run = services.create_run(shop, by=staff.owner, period="2026-10")
    rows = table(owner_api(staff.owner), shop, run)
    assert all(adds_up(row) for row in rows.values()), rows
    ali = run.payslips.get(membership=staff.ali)
    assert rows["Ali"]["taxes_withheld"] == f"{summed(ali, Kind.INCOME_TAX, Kind.INPS):.2f}"
    assert D(rows["Ali"]["taxes_withheld"]) < 0
