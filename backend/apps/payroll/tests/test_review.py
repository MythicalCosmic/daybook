"""Money defects an independent review of payroll found (2026-11-02), each pinned by a test:
rostered leavers and joiners, a salary paid in Finance and a reopen, tasks accepted in the
next month, daily earners' overtime, a rule's own void, rejected daily fines, the finalize
lock, self-dealing, dollar task rates and the full amount for a joiner."""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.attendance import services as attendance_services
from apps.attendance.models import AttendanceRecord, WorkShift
from apps.core.exceptions import DomainError
from apps.finance import services as finance
from apps.finance.models import Debt, MoneyAccount, Transaction
from apps.payroll import calculator, rules, services
from apps.payroll.models import Adjustment, AdjustmentRule, Compensation, PayslipLine
from apps.payroll.tests.conftest import OCTOBER, local
from apps.payroll.tests.test_golden import record
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db
Kind = PayslipLine.Kind
Rule = AdjustmentRule


@pytest.fixture
def dates(monkeypatch):
    """{member id: (first day, last day or None)}: fixed employment dates."""
    table = {}

    def employment_dates(company, member_ids):
        return {pk: table[pk] for pk in member_ids if pk in table}

    monkeypatch.setattr("apps.hr.queries.employment_dates", employment_dates)
    return table


def october_workdays():
    """Monday to Saturday of October 2026, without the holiday of the 1st."""
    first = date(2026, 10, 1)
    days = (first + timedelta(days=n) for n in range(31))
    return [day for day in days if day.weekday() < 6 and day != first]


def plan(member, days):
    for day in days:
        WorkShift.objects.create(
            company=member.company,
            membership=member,
            date=day,
            starts_at=local(day, 9),
            ends_at=local(day, 18),
            branch=member.home_branch,
            status=WorkShift.Status.PLANNED,
            published_at=local(date(2026, 9, 25), 10),
        )


def compute(member, period=OCTOBER, usd_rate=None):
    inputs, people = calculator.gather(member.company, period, usd_rate=usd_rate)
    person = next(p for p in people if p.member_id == member.pk)
    return calculator.compute(person, inputs)


def net(result):
    return sum((line.amount for line in result.lines), D(0))


# 1. Rostered leavers and joiners: S also counts the workdays outside the employment.


def test_a_rostered_leaver_is_paid_the_days_worked(shop, staff, freeze, dates):
    """§3.17's final-settlement golden: 5 200 000 a month, last day Wednesday 14 October,
    worked Monday to Saturday 2 to 14 October = 11 days: 2 200 000."""
    ali = staff.ali
    dates[ali.pk] = (date(2025, 6, 1), None)
    freeze(local(date(2026, 9, 28), 10))
    services.set_pay(ali, by=None, effective_from=date(2026, 1, 1), amount=D("5200000"))
    plan(ali, october_workdays())
    freeze(local(date(2026, 10, 14), 19))
    attendance_services.member_left(ali)  # cancels his shifts of 15 to 31 October
    dates[ali.pk] = (date(2025, 6, 1), date(2026, 10, 14))
    freeze(local(date(2026, 11, 3), 10))
    result = compute(ali)
    assert result.scheduled_days == 26 and result.paid_days == 11
    assert net(result) == D("2200000.00")


def test_a_rostered_joiner_is_paid_from_the_first_day(shop, staff, freeze, dates):
    """Golden "hired Thursday 15 October": 15 days of 200 000 = 3 000 000, also when the
    roster has shifts only from that day."""
    vali = staff.vali
    dates[vali.pk] = (date(2026, 10, 15), None)
    freeze(local(date(2026, 10, 14), 10))
    services.set_pay(vali, by=None, effective_from=date(2026, 10, 15), amount=D("5200000"))
    plan(vali, [day for day in october_workdays() if day >= date(2026, 10, 15)])
    freeze(local(date(2026, 11, 3), 10))
    result = compute(vali)
    assert result.scheduled_days == 26
    assert net(result) == D("3000000.00")


def test_a_rostered_joiners_overtime_rate_follows_the_whole_month(shop, staff, freeze, dates):
    vali = staff.vali
    dates[vali.pk] = (date(2026, 10, 15), None)
    freeze(local(date(2026, 10, 14), 10))
    services.set_pay(vali, by=None, effective_from=date(2026, 10, 15), amount=D("5200000"))
    plan(vali, [day for day in october_workdays() if day >= date(2026, 10, 15)])
    record(vali, date(2026, 10, 20), (9, 0), (22, 0), overtime=240)
    freeze(local(date(2026, 11, 3), 10))
    overtime = next(line for line in compute(vali).lines if line.kind == Kind.OVERTIME)
    assert overtime.rate == D("25000.00") and overtime.amount == D("200000.00")


# 2. A salary paid (in part) in Finance, Debts stops a reopen.


def test_reopen_is_refused_after_a_salary_payment_in_finance(shop, staff, cash, freeze, dates):
    dates[staff.ali.pk] = (date(2025, 6, 1), None)
    freeze(local(date(2026, 11, 3), 10))
    services.set_pay(staff.ali, by=None, effective_from=date(2026, 1, 1), amount=D("5200000"))
    run = services.finalize_run(
        services.create_run(shop, by=staff.owner, period="2026-10"), by=staff.owner
    )
    payslip = run.payslips.get(membership=staff.ali)
    payment = finance.pay_debt(
        payslip.salary_debt,
        by=staff.owner,
        amount=D("2000000"),
        paid_on=date(2026, 11, 3),
        account=cash,
    )
    balance = MoneyAccount.objects.get(pk=cash.pk).balance
    with pytest.raises(DomainError, match="Finance"):
        services.reopen_run(run, by=staff.owner)
    run.refresh_from_db()
    assert run.status == "finalized"
    assert MoneyAccount.objects.get(pk=cash.pk).balance == balance
    # Paying the rest through payroll pays only what is left: 5 200 000 in all.
    services.mark_paid(run, by=staff.owner, payslip_ids=[payslip.pk], account=cash)
    assert MoneyAccount.objects.get(pk=cash.pk).balance == balance - D("3200000")
    salary = Debt.objects.get(pk=payslip.salary_debt_id)
    assert (salary.paid, salary.status) == (D("5200000"), "paid")
    assert Transaction.objects.get(pk=payment.pk).status == "posted"


def test_reopen_works_with_only_payrolls_own_rows(shop, staff, cash, freeze, dates):
    dates[staff.ali.pk] = (date(2025, 6, 1), None)
    freeze(local(date(2026, 11, 3), 10))
    services.set_pay(staff.ali, by=None, effective_from=date(2026, 1, 1), amount=D("5200000"))
    run = services.finalize_run(
        services.create_run(shop, by=staff.owner, period="2026-10"), by=staff.owner
    )
    services.reopen_run(run, by=staff.owner)
    run.refresh_from_db()
    assert run.status == "draft"


# 3. Tasks count in the month they were accepted.


def test_a_reward_accepted_after_the_month_is_paid_with_the_next(shop, staff, freeze, dates):
    ali = staff.ali
    dates[ali.pk] = (date(2025, 6, 1), None)
    freeze(local(date(2026, 10, 20), 10))
    services.set_pay(ali, by=None, effective_from=date(2026, 1, 1), amount=D("5200000"))
    task = Task.objects.create(
        company=shop,
        kind=Task.Kind.ASSIGNED,
        title="Inventory count",
        assignee=ali,
        created_by=staff.manager,
        needs_confirmation=True,
        reward=D("100000"),
        status=Task.Status.REVIEW,
        completed_at=local(date(2026, 10, 31), 20),
    )
    freeze(local(date(2026, 11, 2), 10))
    run = services.finalize_run(
        services.create_run(shop, by=staff.owner, period="2026-10"), by=staff.owner
    )
    october = run.payslips.get(membership=ali)
    assert not october.lines.filter(kind=Kind.TASK_REWARD).exists()
    Task.objects.filter(pk=task.pk).update(
        status=Task.Status.DONE,
        confirmed_at=local(date(2026, 11, 3), 10),
        confirmed_by=staff.manager,
    )
    freeze(local(date(2026, 12, 2), 10))
    rewards = [line.amount for line in compute(ali, date(2026, 11, 1)).lines]
    assert D("100000.00") in rewards


def test_a_task_accepted_on_finishing_counts_by_when_it_was_done(shop, staff, freeze, dates):
    ali = staff.ali
    dates[ali.pk] = (date(2025, 6, 1), None)
    freeze(local(date(2026, 11, 3), 10))
    services.set_pay(ali, by=None, effective_from=date(2026, 1, 1), amount=D("5200000"))
    Task.objects.create(
        company=shop,
        kind=Task.Kind.ASSIGNED,
        title="Delivery",
        assignee=ali,
        created_by=staff.manager,
        reward=D("30000"),
        status=Task.Status.DONE,
        completed_at=local(date(2026, 10, 12), 15),
    )
    rewards = [line for line in compute(ali).lines if line.kind == Kind.TASK_REWARD]
    assert [line.amount for line in rewards] == [D("30000.00")]


# 4. Daily earners' overtime earns the whole multiplier.


def test_daily_earner_overtime_at_the_full_multiplier(shop, staff, freeze, dates):
    ali = staff.ali
    dates[ali.pk] = (date(2025, 6, 1), None)
    freeze(local(date(2026, 11, 3), 10))
    services.set_pay(
        ali, by=None, effective_from=date(2026, 1, 1), amount=D("200000"), pay_type="daily"
    )
    record(ali, date(2026, 10, 5), (9, 0), (22, 0), overtime=240)
    result = compute(ali)
    overtime = next(line for line in result.lines if line.kind == Kind.OVERTIME)
    # 200 000 / 8 = 25 000 an hour; 4 h at the overtime multiplier 2.
    assert overtime.amount == D("200000.00")
    assert next(line for line in result.lines if line.kind == Kind.BASE).amount == D("200000.00")


# 5 and 6. Rules: the rule's own void comes back; a rejected daily fine is never re-proposed.


@pytest.fixture
def sales(shop, monkeypatch):
    shop.features = [*shop.features, "sales"]
    shop.save(update_fields=["features"])
    table = {}

    def cashier_scorecard(company, start, end, *, branch_ids):
        return [{"member": {"id": pk, "name": "x"}, "net": v} for pk, v in table.items()]

    monkeypatch.setattr("apps.sales.queries.cashier_scorecard", cashier_scorecard)
    return table


def test_a_rules_own_void_comes_back_when_the_metric_earns_it(shop, staff, freeze, dates, sales):
    ali = staff.ali
    dates[ali.pk] = (date(2025, 6, 1), None)
    freeze(local(date(2026, 11, 3), 10))
    services.set_pay(ali, by=None, effective_from=date(2026, 1, 1), amount=D("5200000"))
    services.save_rule(
        shop,
        by=None,
        name="Sales 40M",
        kind="bonus",
        metric=Rule.Metric.SALES_NET,
        mode=Rule.Mode.ONCE,
        op=Rule.Op.GTE,
        threshold=D(40000000),
        amount=D(100000),
        is_active=True,
    )
    sales[ali.pk] = D("48000000")
    rules.evaluate_monthly(shop, OCTOBER)
    sales[ali.pk] = D("1000")
    rules.evaluate_monthly(shop, OCTOBER)
    assert Adjustment.objects.get(membership=ali).status == "void"
    sales[ali.pk] = D("48000000")
    assert rules.evaluate_monthly(shop, OCTOBER) == 1
    row = Adjustment.objects.get(membership=ali)
    assert (row.status, row.amount, row.decision_note) == ("proposed", D("100000.00"), "")
    # A person's void stays, whatever the metric does.
    services.void(row, by=staff.owner, reason="Not this month")
    sales[ali.pk] = D("1000")
    rules.evaluate_monthly(shop, OCTOBER)
    sales[ali.pk] = D("48000000")
    assert rules.evaluate_monthly(shop, OCTOBER) == 0
    assert Adjustment.objects.get(membership=ali).status == "void"


def test_a_daily_rule_never_reproposes_a_rejected_fine(shop, staff, freeze, dates):
    ali = staff.ali
    dates[ali.pk] = (date(2025, 6, 1), None)
    freeze(local(date(2026, 10, 6), 10))
    services.set_pay(ali, by=None, effective_from=date(2026, 1, 1), amount=D("5200000"))
    services.save_rule(
        shop,
        by=None,
        name="Late",
        kind="fine",
        metric=Rule.Metric.LATE_ARRIVALS,
        mode=Rule.Mode.PER_UNIT,
        amount=D(20000),
        evaluate=Rule.Evaluate.DAILY,
        is_active=True,
    )
    AttendanceRecord.objects.create(
        company=shop,
        membership=ali,
        date=date(2026, 10, 5),
        status="closed",
        is_late=True,
        late_minutes=15,
        worked_minutes=480,
    )
    assert rules.evaluate_daily(shop, date(2026, 10, 6)) == 1
    services.reject(Adjustment.objects.get(membership=ali), by=staff.owner, reason="Excused")
    assert rules.evaluate_daily(shop, date(2026, 10, 7)) == 0
    assert Adjustment.objects.filter(membership=ali).count() == 1


# 7. Checking a month locks its run, so a change and a finalize never cross.


def test_changes_lock_the_months_run(shop, staff, freeze, dates):
    dates[staff.ali.pk] = (date(2025, 6, 1), None)
    freeze(local(date(2026, 11, 3), 10))
    services.set_pay(staff.ali, by=None, effective_from=date(2026, 1, 1), amount=D("5200000"))
    services.create_run(shop, by=staff.owner, period="2026-10")
    row = services.propose(
        staff.ali, by=staff.manager, kind="bonus", amount=1, reason="x", period="2026-10"
    )
    with CaptureQueriesContext(connection) as approving:
        services.approve(row, by=staff.owner)
    with CaptureQueriesContext(connection) as evaluating:
        rules.evaluate_monthly(shop, OCTOBER)
    for queries in (approving, evaluating):
        locks = [q["sql"] for q in queries if "payroll_payrollrun" in q["sql"]]
        assert any("FOR UPDATE" in sql for sql in locks), locks


# 8. Nobody decides about their own pay.


def test_nobody_decides_their_own_bonus_or_fine(shop, staff, today):
    fine = services.propose(
        staff.accountant, by=staff.manager, kind="fine", amount=50000, reason="Late report"
    )
    with pytest.raises(DomainError, match="own"):
        services.reject(fine, by=staff.accountant, reason="no")
    with pytest.raises(DomainError, match="own"):
        services.void(fine, by=staff.accountant, reason="no")
    services.approve(fine, by=staff.owner)
    services.dispute(fine, by=staff.accountant, text="I sent it on time")
    with pytest.raises(DomainError, match="own"):
        services.answer_dispute(fine, by=staff.accountant, answer="Agreed", void_it=True)
    fine.refresh_from_db()
    assert fine.status == "approved"


def test_nobody_but_an_owner_sets_their_own_pay(shop, staff, today):
    with pytest.raises(DomainError, match="own pay"):
        services.set_pay(staff.accountant, by=staff.accountant, effective_from=OCTOBER, amount=1)
    row = services.set_pay(staff.accountant, by=staff.owner, effective_from=OCTOBER, amount=100)
    with pytest.raises(DomainError, match="own pay"):
        services.update_pay(row, by=staff.accountant, amount=D("999999999"))
    with pytest.raises(DomainError, match="own pay"):
        services.remove_pay(row, by=staff.accountant)
    assert Compensation.objects.get(pk=row.pk).amount == D("100.00")
    # The owner is the business: they may set their own salary.
    assert services.set_pay(staff.owner, by=staff.owner, effective_from=OCTOBER, amount=1)


# 9. A task rate in dollars is converted at the run's rate.


def test_a_dollar_task_rate_is_converted(shop, staff, freeze, dates):
    ali = staff.ali
    dates[ali.pk] = (date(2025, 6, 1), None)
    freeze(local(date(2026, 10, 20), 10))
    services.set_pay(
        ali, by=None, effective_from=date(2026, 1, 1), amount=D("5200000"), pays_task_rates=True
    )
    services.save_task_rate(shop, by=None, amount=D("5"), currency="USD")
    Task.objects.create(
        company=shop,
        kind=Task.Kind.ASSIGNED,
        title="Delivery",
        assignee=ali,
        created_by=staff.manager,
        status=Task.Status.DONE,
        completed_at=local(date(2026, 10, 12), 15),
    )
    freeze(local(date(2026, 11, 3), 10))
    pieces = [line for line in compute(ali, usd_rate=D("12650")).lines if line.kind == Kind.PIECE]
    assert [(line.rate, line.amount) for line in pieces] == [(D("63250.00"), D("63250.00"))]
    without_rate = compute(ali)
    assert not [line for line in without_rate.lines if line.kind == Kind.PIECE]
    assert {"code": "no_usd_rate", "currency": "USD"} in without_rate.warnings
    # A run takes the company's dollar rate for the month when only a task rate needs it.
    finance.set_company_rate(
        shop, by=staff.owner, currency="USD", day=date(2026, 10, 31), rate=D("12650")
    )
    run = services.create_run(shop, by=staff.owner, period="2026-10")
    assert run.usd_rate == D("12650")
    line = PayslipLine.objects.get(payslip__run=run, kind=Kind.PIECE)
    assert line.amount == D("63250.00")


# 10. "Full amount": a setup from the hire day covers the whole employment.


def test_full_amount_for_a_joiner_whose_setup_starts_on_the_hire_day(shop, staff, freeze, dates):
    vali = staff.vali
    dates[vali.pk] = (date(2026, 10, 15), None)
    freeze(local(date(2026, 11, 3), 10))
    services.set_pay(
        vali, by=None, effective_from=date(2026, 10, 15), amount=D("5200000"), proration="none"
    )
    assert net(compute(vali)) == D("5200000.00")


def test_full_amount_still_splits_a_change_within_the_month(shop, staff, freeze, dates):
    ali = staff.ali
    dates[ali.pk] = (date(2025, 6, 1), None)
    freeze(local(date(2026, 11, 3), 10))
    services.set_pay(
        ali, by=None, effective_from=date(2026, 1, 1), amount=D("3100000"), proration="none"
    )
    services.set_pay(
        ali, by=None, effective_from=date(2026, 10, 16), amount=D("6200000"), proration="none"
    )
    bases = [line.amount for line in compute(ali).lines if line.kind == Kind.BASE]
    # 15 of 31 days at 3 100 000, 16 at 6 200 000.
    assert bases == [D("1500000.00"), D("3200000.00")]


def test_tax_rows_reopen_and_finalize_once(shop, staff, freeze, dates):
    """With taxes on, finalize → reopen → finalize leaves the same live ledger."""
    dates[staff.ali.pk] = (date(2025, 6, 1), None)
    freeze(local(date(2026, 11, 3), 10))
    services.set_pay(staff.ali, by=None, effective_from=date(2026, 1, 1), amount=D("5200000"))
    services.update_settings(shop, by=staff.owner, taxes_enabled=True, amounts_are_net=False)
    run = services.finalize_run(
        services.create_run(shop, by=staff.owner, period="2026-10"), by=staff.owner
    )

    def snapshot():
        rows = sorted(
            (r.kind, r.amount, r.base_amount, r.category_id, r.source_type, r.source_key)
            for r in Transaction.objects.filter(company=shop, status__in=("posted", "pending"))
        )
        debts = sorted(
            (d.kind, d.direction, d.amount, d.paid, d.status)
            for d in Debt.objects.filter(company=shop).exclude(status="cancelled")
        )
        return rows, debts

    once = snapshot()
    services.reopen_run(run, by=staff.owner)
    run.refresh_from_db()
    services.finalize_run(run, by=staff.owner)
    assert snapshot() == once
