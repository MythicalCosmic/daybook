"""Payroll runs: calculate, finalize (locks and the finance bridge), reopen, cancel, publish,
mark paid, "I received it", hand-made lines, the owner and employee API."""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from apps.core.exceptions import DomainError
from apps.finance import services as finance
from apps.finance.models import Debt, MoneyAccount, Transaction
from apps.inbox.models import Notification
from apps.payroll import finance_bridge, services
from apps.payroll.models import (
    Adjustment,
    Advance,
    AdvanceRepayment,
    Compensation,
    PayrollRun,
    Payslip,
    PayslipLine,
)
from apps.payroll.tests.conftest import OCTOBER, local

pytestmark = pytest.mark.django_db

D = Decimal
Kind = PayslipLine.Kind


def url(company, path=""):
    return f"/api/v1/owner/companies/{company.pk}/payroll/{path}"


def my_url(company, path=""):
    return f"/api/v1/companies/{company.pk}/payroll/{path}"


@pytest.fixture
def november(freeze):
    """The clock stands at 10:00 on Tuesday 3 November 2026: October is over."""
    return freeze(local(date(2026, 11, 3), 10))


@pytest.fixture
def hired(monkeypatch, staff):
    """Everyone has worked here since June 2025 (fixed employment dates)."""

    def employment_dates(company, member_ids):
        return {pk: (date(2025, 6, 1), None) for pk in member_ids}

    monkeypatch.setattr("apps.hr.queries.employment_dates", employment_dates)
    return staff


@pytest.fixture
def team(hired, november):
    """Ali 5 200 000 a month, Sara 4 680 000; Vali has no pay setup."""
    staff = hired
    services.set_pay(staff.ali, by=None, effective_from=date(2026, 1, 1), amount="5200000")
    services.set_pay(staff.sara, by=None, effective_from=date(2026, 1, 1), amount="4680000")
    return staff


def payslip_of(run, member) -> Payslip:
    return run.payslips.get(membership=member)


def lines(payslip, kind=None):
    rows = payslip.lines.all()
    return [line for line in rows if kind is None or line.kind == kind]


def ledger(run):
    """What a run left in finance that still stands: (kind, amount, base, category, source key)
    of each live row, and (kind, amount, paid, status) of each live debt of its people."""
    rows = sorted(
        (row.kind, row.amount, row.base_amount, row.category_id, row.source_key)
        for row in finance_bridge.live_rows(run)
    )
    debts = sorted(
        (debt.kind, debt.direction, debt.amount, debt.paid, debt.status)
        for debt in Debt.objects.filter(company=run.company).exclude(status="cancelled")
    )
    return rows, debts


class TestCalculate:
    def test_payslips_and_warnings(self, shop, team):
        staff = team
        services.propose(
            staff.ali, by=staff.manager, kind="bonus", amount=1, reason="x", period="2026-10"
        )
        run = services.create_run(shop, by=staff.accountant, period="2026-10")
        assert run.status == "draft" and run.calculated_at is not None
        assert set(run.payslips.values_list("membership_id", flat=True)) == {
            staff.ali.pk,
            staff.sara.pk,
        }
        assert payslip_of(run, staff.ali).net == D("5200000.00")
        assert run.totals["people"] == 2 and run.totals["net"] == "9880000.00"
        codes = [w["code"] for w in run.warnings]
        assert "no_pay_setup" in codes and "proposed" in codes
        no_setup = {w["member"]["id"] for w in run.warnings if w["code"] == "no_pay_setup"}
        assert staff.vali.pk in no_setup and staff.owner.pk not in no_setup
        with pytest.raises(DomainError, match="already"):
            services.create_run(shop, by=staff.accountant, period="2026-10")
        with pytest.raises(DomainError, match="started"):
            services.create_run(shop, by=staff.accountant, period="2026-12")

    def test_no_pay_setup_warns_only_about_people_who_worked_that_month(
        self, shop, team, monkeypatch
    ):
        staff = team
        joined = {staff.vali.pk: (date(2026, 11, 2), None)}  # started after October
        monkeypatch.setattr(
            "apps.hr.queries.employment_dates",
            lambda company, ids: {pk: joined.get(pk, (date(2025, 6, 1), None)) for pk in ids},
        )
        run = services.create_run(shop, by=staff.accountant, period="2026-10")
        warned = {w["member"]["id"] for w in run.warnings if w["code"] == "no_pay_setup"}
        assert staff.vali.pk not in warned and staff.manager.pk in warned

    def test_recalculating_follows_the_data_and_keeps_hand_made_lines(self, shop, team):
        staff = team
        run = services.create_run(shop, by=staff.owner, period="2026-10")
        payslip = payslip_of(run, staff.ali)
        services.set_manual_lines(
            payslip, by=staff.owner, lines=[{"label": "Taxi to the warehouse", "amount": "45000"}]
        )
        payslip.refresh_from_db()
        assert payslip.net == D("5245000.00")
        bonus = services.propose(
            staff.ali,
            by=staff.owner,
            kind="bonus",
            amount="300000",
            reason="Best month",
            period="2026-10",
            approve=True,
        )
        services.calculate_run(run, by=staff.owner)
        payslip.refresh_from_db()
        assert payslip.net == D("5545000.00")
        assert [line.label for line in lines(payslip, Kind.MANUAL)] == ["Taxi to the warehouse"]
        assert lines(payslip, Kind.BONUS)[0].adjustment_id == bonus.pk
        # Removing the setup takes the person out of the draft.
        Compensation.objects.filter(membership=staff.sara).delete()
        services.calculate_run(run, by=staff.owner)
        assert not run.payslips.filter(membership=staff.sara).exists()

    def test_the_deductions_cap(self, shop, team):
        staff = team
        services.propose(
            staff.ali,
            by=staff.owner,
            kind="fine",
            amount="2000000",
            reason="Storage breach",
            period="2026-10",
            approve=True,
        )
        run = services.create_run(shop, by=staff.owner, period="2026-10")
        payslip = payslip_of(run, staff.ali)
        fine = lines(payslip, Kind.FINE)[0]
        assert fine.amount == D("-1040000.00")  # 20 % of 5 200 000
        assert fine.params["capped"] and fine.params["full"] == "2000000.00"
        assert payslip.net == D("4160000.00")
        assert "deductions_capped" in [w["code"] for w in run.warnings]

    def test_only_a_draft_is_calculated_and_permissions(self, shop, team):
        staff = team
        run = services.create_run(shop, by=staff.owner, period="2026-10")
        with pytest.raises(PermissionDenied):
            services.calculate_run(run, by=staff.manager)
        with pytest.raises(PermissionDenied):
            services.finalize_run(run, by=staff.accountant)  # payroll.finalize: owners only
        services.finalize_run(run, by=staff.owner)
        with pytest.raises(DomainError, match="draft"):
            services.calculate_run(run, by=staff.owner)


class TestFinalize:
    @pytest.fixture
    def advance(self, shop, team, cash):
        """Ali's advance of 1 000 000, paid on 20 October, back in two months."""
        staff = team
        row = services.create_advance(
            staff.ali, by=staff.owner, amount="1000000", installments=2, first_period="2026-11"
        )
        Advance.objects.filter(pk=row.pk).update(first_period=OCTOBER)
        row.refresh_from_db()
        return services.pay_advance(row, by=staff.owner, account=cash, paid_on=date(2026, 10, 20))

    @pytest.fixture
    def claim(self, shop, team):
        """Sara spent 150 000 of her own money on printer paper; the claim was approved."""
        return finance.open_debt(
            shop,
            by=team.owner,
            direction="payable",
            kind="reimbursement",
            amount=D("150000"),
            currency="UZS",
            issued_on=date(2026, 10, 10),
            membership=team.sara,
            category="other_expense",
            description="Printer paper",
        )

    def test_books_the_month(self, shop, team, advance, claim):
        staff = team
        fine = services.propose(
            staff.sara,
            by=staff.owner,
            kind="fine",
            amount="100000",
            reason="Late",
            period="2026-10",
            approve=True,
        )
        run = services.create_run(shop, by=staff.owner, period="2026-10")
        run = services.finalize_run(run, by=staff.owner)
        assert run.status == "finalized"
        ali = payslip_of(run, staff.ali)
        sara = payslip_of(run, staff.sara)
        # Ali: 5 200 000 less half the advance; Sara: 4 680 000 - 100 000 + 150 000.
        assert ali.net == D("4700000.00") and sara.net == D("4730000.00")
        assert lines(ali, Kind.ADVANCE)[0].amount == D("-500000.00")
        # The salary payable is the pay for the work; the advance offsets both debts.
        assert (ali.salary_debt.amount, ali.salary_debt.paid) == (D("5200000"), D("500000"))
        assert (sara.salary_debt.amount, sara.salary_debt.paid) == (D("4580000"), D("0"))
        assert ali.salary_debt.kind == "salary" and ali.salary_debt.issued_on == date(2026, 10, 31)
        accruals = Transaction.objects.filter(debt__kind="salary", kind="expense")
        assert sorted(row.amount for row in accruals) == [D("-5200000"), D("-4580000")]
        assert {row.category.system_code for row in accruals} == {"salaries"}
        advance.refresh_from_db()
        assert advance.debt.paid == D("500000") and advance.status == "paid"
        assert AdvanceRepayment.objects.get(advance=advance).payslip_line.payslip == ali
        claim.refresh_from_db()
        assert claim.locked_by_type == "payroll.payslip" and claim.locked_by_id == sara.pk
        fine.refresh_from_db()
        assert fine.payslip == sara
        assert Compensation.objects.filter(locked=True).count() == 2
        with pytest.raises(DomainError, match="finalized"):
            services.void(fine, by=staff.owner, reason="Changed my mind")

    def test_finalize_reopen_finalize_books_exactly_once(self, shop, team, advance, claim):
        staff = team
        run = services.create_run(shop, by=staff.owner, period="2026-10")
        services.finalize_run(run, by=staff.owner)
        once = ledger(run)
        cash_balance = MoneyAccount.objects.get(name="Payroll cash").balance
        services.reopen_run(run, by=staff.owner, reason="A fine was wrong")
        run.refresh_from_db()
        assert run.status == "draft"
        assert finance_bridge.live_rows(run).count() == 0
        claim.refresh_from_db()
        advance.refresh_from_db()
        assert claim.locked_by_type == "" and advance.debt.paid == 0
        assert not AdvanceRepayment.objects.exists()
        assert not Compensation.objects.filter(locked=True).exists()
        assert not Adjustment.objects.filter(payslip__isnull=False).exists()
        services.finalize_run(run, by=staff.owner)
        assert ledger(run) == once
        assert MoneyAccount.objects.get(name="Payroll cash").balance == cash_balance

    def test_reopen_rules(self, shop, team, cash):
        staff = team
        run = services.create_run(shop, by=staff.owner, period="2026-10")
        with pytest.raises(DomainError):
            services.reopen_run(run, by=staff.owner)
        services.finalize_run(run, by=staff.owner)
        services.mark_paid(
            run, by=staff.owner, payslip_ids=[payslip_of(run, staff.ali).pk], account=cash
        )
        with pytest.raises(DomainError, match="paid"):
            services.reopen_run(run, by=staff.owner)

    def test_mark_paid_publish_and_received(
        self, shop, team, cash, claim, django_capture_on_commit_callbacks
    ):
        staff = team
        run = services.create_run(shop, by=staff.owner, period="2026-10")
        services.finalize_run(run, by=staff.owner)
        with django_capture_on_commit_callbacks(execute=True):
            services.publish(run, by=staff.owner)
        sara = payslip_of(run, staff.sara)
        assert sara.status == "published" and sara.published_at is not None
        told = Notification.objects.get(kind="payroll.payslip", recipient=staff.sara)
        assert told.app_screen == f"payslip:{sara.pk}"
        sara.refresh_from_db()
        assert sara.pdf.name.endswith(".pdf")  # rendered and sent with the message
        before = MoneyAccount.objects.get(pk=cash.pk).balance
        with django_capture_on_commit_callbacks(execute=True):
            services.mark_paid(
                run,
                by=staff.accountant,
                payslip_ids=[p.pk for p in run.payslips.all()],
                account=cash,
                method="card",
            )
        run.refresh_from_db()
        assert run.status == "paid" and run.paid_at is not None
        after = MoneyAccount.objects.get(pk=cash.pk).balance
        assert before - after == D("5200000") + D("4830000")  # Sara: pay + the paper
        claim.refresh_from_db()
        assert claim.status == "paid"
        sara.refresh_from_db()
        assert sara.salary_debt.status == "paid" and sara.payout_method == "card"
        paid = Notification.objects.filter(kind="payroll.payslip", recipient=staff.sara).latest(
            "pk"
        )
        assert [a["key"] for a in paid.actions] == ["received"]
        with pytest.raises(PermissionDenied):
            services.confirm_received(sara, by=staff.ali)
        services.confirm_received(sara, by=staff.sara)
        sara.refresh_from_db()
        assert sara.received_at is not None

    def test_a_claim_paid_in_cash_first_is_not_paid_twice(self, shop, team, cash, claim):
        staff = team
        run = services.create_run(shop, by=staff.owner, period="2026-10")
        assert lines(payslip_of(run, staff.sara), Kind.REIMBURSEMENT)
        finance.pay_debt(
            claim, by=staff.owner, amount=D("150000"), paid_on=date(2026, 11, 2), account=cash
        )
        services.finalize_run(run, by=staff.owner)  # works the month out once more
        assert not lines(payslip_of(run, staff.sara), Kind.REIMBURSEMENT)

    def test_cancel(self, shop, team):
        run = services.create_run(shop, by=team.owner, period="2026-10")
        services.cancel_run(run, by=team.owner)
        run.refresh_from_db()
        assert run.status == "cancelled"
        again = services.create_run(shop, by=team.owner, period="2026-10")
        assert again.pk != run.pk

    def test_taxes_on_gross_pay(self, shop, team):
        staff = team
        services.update_settings(shop, by=staff.owner, taxes_enabled=True, amounts_are_net=False)
        run = services.create_run(shop, by=staff.owner, period="2026-10")
        ali = payslip_of(run, staff.ali)
        assert lines(ali, Kind.INCOME_TAX)[0].amount == D("-624000.00")
        assert lines(ali, Kind.INPS)[0].amount == D("-5200.00")
        assert ali.taxes["social_tax"] == "624000.00"
        services.finalize_run(run, by=staff.owner)
        taxes = Debt.objects.filter(kind="tax", status="open")
        assert sorted(debt.amount for debt in taxes) == [
            D("1185600"),  # social tax: 12 % of 9 880 000
            D("1195480"),  # income tax and pension withheld
        ]
        assert {debt.counterparty.kind for debt in taxes} == {"state"}


class TestApi:
    def test_run_flow(self, shop, team, cash, owner_api):
        staff = team
        owner = owner_api(staff.owner)
        created = owner.post(url(shop, "runs/"), {"period": "2026-10"}, format="json")
        assert created.status_code == 201, created.data
        run_id = created.data["id"]
        assert created.data["month"] and created.data["totals"]["net"] == "9880000.00"
        assert "finalize" in created.data["actions"]
        assert any(w["text"] for w in created.data["warnings"])
        table = owner.get(url(shop, f"runs/{run_id}/payslips/"))
        assert table.data["count"] == 2 and table.data["results"][0]["net"]
        finalized = owner.post(url(shop, f"runs/{run_id}/finalize/"))
        assert finalized.status_code == 200 and finalized.data["status"] == "finalized"
        assert set(finalized.data["actions"]) >= {"reopen", "publish", "mark_paid"}
        ali = payslip_of(PayrollRun.objects.get(pk=run_id), staff.ali)
        detail = owner.get(url(shop, f"payslips/{ali.pk}/"))
        assert detail.data["lines"][0]["label"] == "Monthly pay"
        pdf = owner.get(url(shop, f"payslips/{ali.pk}/pdf/"))
        assert pdf.status_code == 200 and pdf.data["url"].startswith("/api/v1/files/")
        downloaded = owner.get(pdf.data["url"])
        assert downloaded.status_code == 200 and downloaded["Content-Type"] == "application/pdf"
        paid = owner_api(staff.accountant).post(
            url(shop, f"runs/{run_id}/mark-paid/"),
            {"payslip_ids": [ali.pk], "account": cash.pk, "method": "cash"},
            format="json",
        )
        assert paid.status_code == 200 and paid.data["totals"]["paid"] == 1

    def test_permissions(self, shop, team, owner_api, other_company, member):
        staff = team
        run = services.create_run(shop, by=staff.owner, period="2026-10")
        manager = owner_api(staff.manager)
        assert manager.get(url(shop, "runs/")).status_code == 403
        assert manager.get(url(shop, f"runs/{run.pk}/payslips/")).status_code == 403
        accountant = owner_api(staff.accountant)
        assert accountant.post(url(shop, f"runs/{run.pk}/finalize/")).status_code == 403
        assert accountant.post(url(shop, f"runs/{run.pk}/calculate/")).status_code == 200
        outsider = owner_api(member(other_company, "Owner"))
        assert outsider.get(url(shop, f"runs/{run.pk}/")).status_code == 404

    def test_hand_made_lines_through_patch(self, shop, team, owner_api):
        staff = team
        run = services.create_run(shop, by=staff.owner, period="2026-10")
        ali = payslip_of(run, staff.ali)
        client = owner_api(staff.owner)
        response = client.patch(
            url(shop, f"payslips/{ali.pk}/"),
            {"manual_lines": [{"label": "Phone", "amount": "-20000"}]},
            format="json",
        )
        assert response.status_code == 200, response.data
        assert response.data["net"] == "5180000.00"
        manual = [line for line in response.data["lines"] if line["manual"]]
        assert manual[0]["label"] == "Phone" and manual[0]["amount"] == "-20000.00"
        cleared = client.patch(
            url(shop, f"payslips/{ali.pk}/"), {"manual_lines": []}, format="json"
        )
        assert cleared.data["net"] == "5200000.00"

    def test_the_employee_sees_only_published_payslips_of_their_own(self, shop, team, api_as, cash):
        staff = team
        run = services.create_run(shop, by=staff.owner, period="2026-10")
        client = api_as(staff.ali)
        assert client.get(my_url(shop, "payslips/")).data == []
        services.finalize_run(run, by=staff.owner)
        services.publish(run, by=staff.owner)
        mine = client.get(my_url(shop, "payslips/")).data
        assert [row["member"]["id"] for row in mine] == [staff.ali.pk]
        ali = payslip_of(run, staff.ali)
        detail = client.get(my_url(shop, f"payslips/{ali.pk}/"))
        assert detail.status_code == 200 and detail.data["net"] == "5200000.00"
        ali.refresh_from_db()
        assert ali.viewed_at is not None
        sara = payslip_of(run, staff.sara)
        assert client.get(my_url(shop, f"payslips/{sara.pk}/")).status_code == 404
        assert client.post(my_url(shop, f"payslips/{ali.pk}/received/")).status_code == 400
        services.mark_paid(run, by=staff.owner, payslip_ids=[ali.pk], account=cash)
        received = client.post(my_url(shop, f"payslips/{ali.pk}/received/"))
        assert received.status_code == 200 and received.data["received_at"]
        pdf = client.get(my_url(shop, f"payslips/{ali.pk}/pdf/"))
        assert pdf.status_code == 200
        assert client.get(pdf.data["url"]).status_code == 200
