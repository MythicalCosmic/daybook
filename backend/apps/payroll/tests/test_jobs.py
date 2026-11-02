"""Payroll's jobs (prepare the month, pay day reminders), the run spreadsheet and the other
registrations (person fields, file check, setup step, finance sources)."""

from datetime import date
from decimal import Decimal

import pytest

from apps.console import contracts, registry
from apps.exports.registry import EXPORTERS
from apps.finance import sources
from apps.inbox.models import Notification
from apps.payroll import jobs, providers, services
from apps.payroll.models import PayrollRun
from apps.payroll.tests.conftest import local

pytestmark = pytest.mark.django_db


@pytest.fixture
def team(staff, monkeypatch):
    monkeypatch.setattr(
        "apps.hr.queries.employment_dates",
        lambda company, member_ids: {pk: (date(2025, 6, 1), None) for pk in member_ids},
    )
    services.set_pay(staff.ali, by=None, effective_from=date(2026, 1, 1), amount="5200000")
    return staff


def test_prepare_runs_once_on_the_first(shop, team, django_capture_on_commit_callbacks):
    assert jobs.prepare_runs(local(date(2026, 11, 1), 5)) == 0  # before 06:00
    with django_capture_on_commit_callbacks(execute=True):
        assert jobs.prepare_runs(local(date(2026, 11, 1), 7)) == 1
    run = PayrollRun.objects.get(company=shop)
    assert run.period == date(2026, 10, 1) and run.status == "draft"
    assert run.payslips.get().net == Decimal("5200000.00")
    told = Notification.objects.filter(kind="payroll.run_prepared")
    assert {n.recipient_id for n in told} == {team.owner.pk}  # payroll.finalize
    assert jobs.prepare_runs(local(date(2026, 11, 1), 8)) == 0
    assert jobs.prepare_runs(local(date(2026, 11, 2), 7)) == 0


def test_prepare_runs_skips_switched_off_companies(shop, team):
    services.update_settings(shop, by=None, auto_prepare=False)
    assert jobs.prepare_runs(local(date(2026, 11, 1), 7)) == 0
    services.update_settings(shop, by=None, auto_prepare=True)
    shop.features = ["finance"]
    shop.save(update_fields=["features"])
    assert jobs.prepare_runs(local(date(2026, 11, 1), 7)) == 0


def test_pay_day_reminder_once_a_month(shop, team, freeze, django_capture_on_commit_callbacks):
    freeze(local(date(2026, 11, 3), 10))
    run = services.create_run(shop, by=team.owner, period="2026-10")
    services.finalize_run(run, by=team.owner)
    assert jobs.pay_day_reminders(local(date(2026, 11, 5), 7)) == 0  # too early
    with django_capture_on_commit_callbacks(execute=True):
        assert jobs.pay_day_reminders(local(date(2026, 11, 5), 9)) == 1
    told = Notification.objects.filter(kind="payroll.pay_day")
    assert {n.recipient_id for n in told} == {team.owner.pk, team.accountant.pk}
    assert jobs.pay_day_reminders(local(date(2026, 11, 5), 10)) == 0


def test_run_spreadsheet_rows(shop, team, freeze):
    freeze(local(date(2026, 11, 3), 10))
    run = services.create_run(shop, by=team.owner, period="2026-10")
    rows = list(providers.run_rows(team.accountant, {"run": run.pk}))
    assert len(rows) == 1
    row = rows[0]
    assert row["person"] == str(team.ali) and row["net"] == Decimal("5200000.00")
    assert row["base_pay"] == Decimal("5200000.00") and row["currency"] == "UZS"
    assert EXPORTERS.get("payroll.run").sensitive
    assert list(providers.run_rows(team.accountant, {"run": 999999})) == []


def test_salary_person_field(shop, team, freeze):
    now = freeze(local(date(2026, 11, 3), 10))
    found = providers.person_fields(shop, [team.ali.pk, team.vali.pk], now)
    assert contracts.problems(contracts.PERSON_FIELDS["payroll"], found[team.ali.pk]) == []
    assert found[team.ali.pk]["salary"] == {
        "amount": "5200000.00",
        "currency": "UZS",
        "pay_type": "monthly",
    }
    assert found[team.vali.pk] == {"salary": None}
    entry = registry.PERSON_FIELDS.get("payroll")
    assert str(entry.perm) == "payroll.view"


def test_registrations(shop, team):
    assert sources.get("payroll.payslip") and sources.get("payroll.advance")
    assert registry.QUEUE.get("payroll.adjustments") and registry.QUEUE.get("payroll.disputes")
    assert providers.setup_done(shop)
