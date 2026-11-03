"""The payroll demo tells one coherent story (apps/core/demo_plan.py): pay setups from the
finance demo's pay table, last month finalized and paid, this month a draft, the night premium
at Yunusobod, adjustments in every state, advances, and each salary booked once."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.attendance import demo as attendance_demo
from apps.companies.models import Feature
from apps.core.management.commands.ensure_company_defaults import ensure_company_defaults
from apps.core.management.commands.seed_demo import Command
from apps.finance import demo as finance_demo
from apps.finance import services as finance
from apps.finance.models import MoneyAccount, Transaction
from apps.payroll import demo
from apps.payroll.models import (
    Adjustment,
    AdjustmentRule,
    Advance,
    Compensation,
    PayrollRun,
    PayslipLine,
)
from apps.payroll.tests.conftest import local
from apps.timeoff import demo as timeoff_demo

pytestmark = pytest.mark.django_db

D = Decimal
SEED_DAY = date(2026, 11, 2)  # a Monday: last month is October, this one November


def test_core_demo_with_the_six_people(company, demo_people, freeze):
    now = freeze(local(SEED_DAY, 14))
    company.features = list(Feature.values)
    company.save(update_fields=["features"])
    ensure_company_defaults(company)
    people = demo_people(company)
    kassa = MoneyAccount.objects.filter(company=company).order_by("pk").first()
    finance.record_transaction(
        company,
        by=people["owner"],
        kind="opening",
        amount=D("200000000"),
        occurred_on=date(2026, 9, 1),
        account=kassa,
    )
    demo.seed(company, people, now)

    worker = people["worker"]
    setups = list(Compensation.objects.filter(membership=worker).order_by("effective_from"))
    assert [row.amount for row in setups] == [D("4900000"), D("5200000")]
    assert setups[1].effective_from == date(2026, 11, 1) and setups[0].locked
    october = PayrollRun.objects.get(company=company, period=date(2026, 10, 1))
    assert october.status == "paid"
    assert october.payslips.filter(received_at__isnull=False).exists()
    november = PayrollRun.objects.get(company=company, period=date(2026, 11, 1))
    assert november.status == "draft" and november.payslips.exists()
    sales_bonus = AdjustmentRule.objects.get(company=company, example_key="sales_bonus")
    assert sales_bonus.is_active and sales_bonus.auto_approve
    madina = october.payslips.get(membership=people["madina"])
    assert madina.lines.filter(kind="bonus").get().amount == D("300000.00")
    jasur = Advance.objects.get(membership=people["jasur"])
    assert jasur.status == "paid" and jasur.repayments.get().amount == D("500000.00")
    assert november.payslips.get(membership=people["jasur"]).lines.get(kind="advance").amount == D(
        "-500000.00"
    )


@pytest.fixture
def pharmacy(freeze):
    """Demo Dorixona as seed_demo makes it, with the time off, books and attendance demos."""
    freeze(local(SEED_DAY, 14))
    now = timezone.now()
    company, people = Command()._build_pharmacy(now)
    company.features = list(Feature.values)
    company.save()
    ensure_company_defaults(company)
    for module in (timeoff_demo, finance_demo, attendance_demo):
        module.seed(company, people, now)
    demo.seed(company, people, now)
    return company, people


def test_every_payslip_row_adds_up(pharmacy, owner_api):
    """The run page's columns: in both demo months each row's parts are exactly its net."""
    company, people = pharmacy
    owner = owner_api(people["owner"])
    parts = (
        "base_pay",
        "extras",
        "bonuses",
        "fines",
        "advances",
        "taxes_withheld",
        "reimbursements",
    )
    runs = PayrollRun.objects.filter(company=company)
    assert runs.count() == 2
    for run in runs:
        url = f"/api/v1/owner/companies/{company.pk}/payroll/runs/{run.pk}/payslips/?page_size=200"
        rows = owner.get(url).data["results"]
        assert rows
        for row in rows:
            assert sum((D(row[name]) for name in parts), D(0)) == D(row["net"]), row
    # October's overtime and night premium are in extras, not lost between base and net.
    october = runs.get(period=date(2026, 10, 1))
    url = f"/api/v1/owner/companies/{company.pk}/payroll/runs/{october.pk}/payslips/?page_size=200"
    nigora = next(
        row for row in owner.get(url).data["results"] if row["member"]["id"] == people["nigora"].pk
    )
    assert D(nigora["extras"]) > D("2000000")


def test_the_whole_story(pharmacy):
    company, people = pharmacy
    october = PayrollRun.objects.get(company=company, period=date(2026, 10, 1))
    assert october.status == "paid"
    # The night pharmacist at Yunusobod: the premium of her 20:00 to 08:00 shifts on top.
    nigora = october.payslips.get(membership=people["nigora"])
    night = nigora.lines.get(kind=PayslipLine.Kind.NIGHT_WORK)
    assert night.amount > 0 and nigora.night_minutes > 0
    assert D("6000000") <= nigora.net <= D("7500000")
    # Each October salary is booked once: the finance demo's own rows are void.
    demo_rows = Transaction.objects.filter(
        company=company, source_type="finance.demo", source_key="sal:202610"
    )
    assert demo_rows.exists() and not demo_rows.exclude(status="void").exists()
    accruals = Transaction.objects.filter(
        company=company, debt__kind="salary", kind="expense", status="posted"
    )
    assert accruals.count() == october.payslips.filter(salary_debt__isnull=False).count()
    # Bonuses and fines in every state, and Kamola's request waiting.
    this_month = Adjustment.objects.filter(company=company, period=date(2026, 11, 1))
    assert this_month.filter(status="proposed").exists()
    assert this_month.filter(disputed_at__isnull=False, dispute_answered_at__isnull=True).exists()
    assert Advance.objects.filter(company=company, status="requested").exists()
    # Alisher's card advance from the finance demo comes off November's pay.
    worker_advance = Advance.objects.get(
        membership=people["worker"], debt__isnull=False, payout_method="card"
    )
    assert worker_advance.first_period == date(2026, 11, 1)
    assert worker_advance.debt.created_at <= timezone.now() + timedelta(seconds=1)
