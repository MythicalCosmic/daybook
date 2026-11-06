"""Money defects an independent review of the final settlement found (2026-11-07), each pinned
by a test (docs/PLAN-OWNER.md §3.17)."""

from datetime import date
from decimal import Decimal as D

import pytest

from apps.finance import services as finance
from apps.finance.models import CompanyRate, Debt
from apps.inbox.models import Notification
from apps.members.models import AccessRole
from apps.members.permissions import Perm
from apps.payroll import finance_bridge, providers, queries, services, settlement
from apps.payroll.models import Advance, PayrollRun, PayslipLine
from apps.payroll.tests.conftest import OCTOBER, local
from apps.payroll.tests.test_settlement import HIRED, LAST_DAY, give_advance, history, leave

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


def test_a_later_month_that_paid_a_leaver_is_flagged(shop, team, freeze):
    """HR writes down on 5 November that Ali's last day was Monday 28 September, after
    September and October were finalized with his whole months. The final run (September's,
    after the regular one) says what September paid after the 28th, and that October paid him
    a whole month he didn't work."""
    staff = team
    freeze(local(date(2026, 9, 30), 18))
    september = services.create_run(shop, by=staff.accountant, period="2026-09")
    services.finalize_run(september, by=staff.owner)
    freeze(local(date(2026, 10, 31), 18))
    october = services.create_run(shop, by=staff.accountant, period="2026-10")
    services.finalize_run(october, by=staff.owner)
    assert october.payslips.get(membership=staff.ali).base_pay == D("5200000.00")
    freeze(local(date(2026, 11, 5), 10))
    leave(staff.ali)
    staff.ends[staff.ali.pk] = date(2026, 9, 28)

    final = services.create_final_run(staff.ali, by=staff.accountant, last_day=date(2026, 9, 28))

    assert final.after_regular
    paid_after = {
        w["month"]: w["amount"] for w in final.warnings if w["code"] == "paid_after_last_day"
    }
    # Tuesday 29 and Wednesday 30 September at 200 000; all of October.
    assert paid_after == {"2026-09-01": "400000.00", "2026-10-01": "5200000.00"}


def test_a_dollar_salary_is_converted_on_the_last_day_it_is_booked_on(shop, team, freeze):
    """Vali earns $1 000 a month and leaves on Wednesday 14 October; his final payslip is
    booked on that day, so it takes that day's dollar rate, not the month end's."""
    staff = team
    services.set_pay(staff.vali, by=None, effective_from=HIRED, amount="1000", currency="USD")
    CompanyRate.objects.create(company=shop, currency="USD", date=date(2026, 10, 14), rate=12000)
    CompanyRate.objects.create(company=shop, currency="USD", date=date(2026, 10, 31), rate=12500)
    freeze(local(date(2026, 11, 2), 10))
    leave(staff.vali)
    staff.ends[staff.vali.pk] = date(2026, 10, 14)

    run = services.create_final_run(staff.vali, by=staff.accountant, last_day=date(2026, 10, 14))

    assert run.usd_rate == D("12000")
    # 11 of 26 days of 12 000 000 so‘m.
    assert run.payslips.get().base_pay == D("5076923.08")


def test_the_spreadsheet_of_a_final_run_shows_the_unused_leave_paid_out(shop, team, cash):
    """The §3.17 settlement exported for the accountant: 2 200 000 + 990 000 of unused leave
    - 500 000 of advance = 2 690 000, every amount in a column of its own."""
    staff = team
    history(shop, staff.ali)
    give_advance(staff, cash, staff.ali, "500000")
    leave(staff.ali)
    run = services.create_final_run(
        staff.ali, by=staff.accountant, last_day=LAST_DAY, leave_days="5.5"
    )

    (row,) = providers.run_rows(staff.accountant, {"run": run.pk})

    assert row["leave_payout"] == D("990000.00")
    parts = ("base_pay", "extra", "bonuses", "leave_payout", "fines", "taxes", "advances")
    assert sum(row[part] for part in parts) + row["reimbursements"] == row["net"]
    assert row["net"] == D("2690000.00")
    assert "leave_payout" in [column[0] for column in providers.RUN_COLUMNS]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Product decision for the lead: `queries.run_summary` (the §11.4 contract behind the "
        "payroll overview's month series, the brief, company facts and Ask AI) sums only the "
        "month's regular run, so a leaver settled by a final run drops out of the month's "
        "payroll figures. Suggested: add the payslips of the month's non-cancelled final runs "
        "to run_summary (and to the overview's by-position and by-branch tables)."
    ),
)
def test_the_months_payroll_figures_count_a_leavers_final_payslip(shop, team):
    staff = team
    leave(staff.ali)
    services.create_final_run(staff.ali, by=staff.accountant, last_day=LAST_DAY)
    services.create_run(shop, by=staff.accountant, period="2026-10")

    summary = queries.run_summary(shop, OCTOBER)

    # Sara's 4 680 000 in the monthly run and Ali's 2 200 000 (11 of 26 days) in his final one.
    assert summary["people"] == 2
    assert summary["net"] == D("6880000.00")


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Product decision for the lead: the warning `paid_after_last_day` says to add a line "
        "by hand to take the overpayment back, but a final payslip whose hand-made deduction "
        "is more than its pay is refused at finalize ('more than the pay: lower a line added "
        "by hand'). Either book the rest as a receivable from the person (like an advance "
        "left) or reword the warning: take back at most what the payslip pays, record the "
        "rest as a debt in Finance."
    ),
)
def test_what_october_paid_after_the_last_day_can_be_taken_back(shop, team, freeze):
    """October paid Ali 600 000 for the 29th to the 31st; his final payslip pays 2 unused
    leave days (5 200 000 / 31 x 2 = 335 483.87). Taking the 600 000 back as the warning
    says leaves him owing 264 516.13, a receivable in Finance."""
    staff = team
    _regular, final = finalized_october_then_ali_leaves(shop, staff, freeze)
    warning = next(w for w in final.warnings if w["code"] == "paid_after_last_day")
    assert warning["amount"] == "600000.00"
    payslip = final.payslips.get()
    services.set_manual_lines(
        payslip,
        by=staff.accountant,
        lines=[{"label": "Paid after the last day", "amount": "-600000"}],
    )

    services.finalize_run(final, by=staff.owner)

    payslip.refresh_from_db()
    assert payslip.net == D("-264516.13")
    owed = Debt.objects.filter(
        membership=staff.ali, direction=Debt.Direction.RECEIVABLE, status=Debt.Status.OPEN
    )
    assert sum(debt.amount - debt.paid for debt in owed) == D("264516.13")


def test_ten_paid_days_read_10_on_the_payslip_and_in_the_wizard(shop, team, freeze):
    """Tuesday 13 October as the last day: 10 paid days of 26. `Decimal.normalize()` wrote
    them "1E+1" on the PDF and in the wizard's step."""
    from apps.payroll import payslip_pdf

    staff = team
    freeze(local(date(2026, 10, 13), 10))
    step = settlement.offboard_step(staff.ali)
    assert "Pay for 10 of 26 working days: 2 000 000" in " ".join(step.lines).replace("\xa0", " ")

    leave(staff.ali)
    run = services.create_final_run(staff.ali, by=staff.accountant, last_day=date(2026, 10, 13))
    facts = payslip_pdf.context(run.payslips.get())["facts"]
    assert "Working days: 26" in facts and "Paid days: 10" in facts


# What the review checked and found sound, pinned so it stays that way ----------------------


def test_an_advance_above_the_pay_is_offset_against_expenses_paid_back(shop, team, cash):
    """Last day Monday 5 October: 600 000 of pay and 400 000 of expenses to pay back against
    an advance of 800 000. The advance is settled in full (600 000 from the salary, 200 000
    from the expenses) and the cash desk pays out exactly the net, 200 000."""
    staff = team
    advance = give_advance(staff, cash, staff.ali, "800000")
    claim = finance.open_debt(
        shop,
        by=staff.owner,
        direction="payable",
        kind="reimbursement",
        amount=D("400000"),
        currency="UZS",
        issued_on=date(2026, 10, 2),
        membership=staff.ali,
        category="other_expense",
        description="Gloves",
    )
    leave(staff.ali)
    run = services.create_final_run(staff.ali, by=staff.accountant, last_day=date(2026, 10, 5))
    payslip = run.payslips.get()
    assert payslip.net == D("200000.00")

    services.finalize_run(run, by=staff.owner)
    advance.refresh_from_db()
    claim.refresh_from_db()
    payslip.refresh_from_db()
    assert advance.status == Advance.Status.REPAID
    assert advance.debt.status == Debt.Status.PAID
    assert (payslip.salary_debt.amount, payslip.salary_debt.paid) == (D("600000"), D("600000"))
    assert claim.paid == D("200000") and claim.status == Debt.Status.OPEN

    services.reopen_run(run, by=staff.owner)
    advance.refresh_from_db()
    claim.refresh_from_db()
    assert advance.debt.paid == 0 and claim.paid == 0 and not claim.is_locked
    assert finance_bridge.booked_total(run) == 0

    services.finalize_run(run, by=staff.owner)
    cash.refresh_from_db()
    before = cash.balance
    services.mark_paid(run, by=staff.accountant, payslip_ids=[payslip.pk], account=cash)
    cash.refresh_from_db()
    claim.refresh_from_db()
    assert before - cash.balance == D("200000")
    assert claim.status == Debt.Status.PAID


def test_a_final_run_stays_inside_the_branches_of_whoever_reads_it(
    shop, team, owner_api, django_capture_on_commit_callbacks
):
    """Lola manages pay at Chilonzor only: she sees and changes Ali's final run, never Sara's
    (Yunusobod), and only Ali's reaches her inbox."""
    staff = team
    role = AccessRole.objects.create(
        company=shop,
        name="Chilonzor payroll",
        permissions=[Perm.DASHBOARD_ACCESS, Perm.PAYROLL_VIEW, Perm.PAYROLL_MANAGE],
    )
    lola = staff.lead
    lola.role = role
    lola.save(update_fields=["role"])
    leave(staff.ali)
    leave(staff.sara)
    with django_capture_on_commit_callbacks(execute=True):
        ali = services.create_final_run(staff.ali, by=staff.owner, last_day=LAST_DAY)
        sara = services.create_final_run(staff.sara, by=staff.owner, last_day=LAST_DAY)
    told = Notification.objects.filter(kind="payroll.final_run", recipient=lola)
    assert [n.target_id for n in told] == [ali.pk]

    client = owner_api(lola)
    base = f"/api/v1/owner/companies/{shop.pk}/payroll/"
    listed = client.get(base + "runs/?kind=final").json()["results"]
    assert [row["id"] for row in listed] == [ali.pk]
    assert client.get(base + f"runs/{sara.pk}/").status_code == 404
    assert client.get(base + f"runs/{sara.pk}/payslips/").status_code == 404
    payout = {"leave_days": "3"}
    assert client.post(base + f"runs/{sara.pk}/leave-payout/", payout).status_code == 404
    assert client.post(base + "runs/final/", {"member": staff.sara.pk}).status_code == 404
    assert client.post(base + f"runs/{ali.pk}/leave-payout/", payout).status_code == 200
