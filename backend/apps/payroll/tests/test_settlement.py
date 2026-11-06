"""The final settlement of someone who leaves (docs/PLAN-OWNER.md §3.17, §1.8): the golden
numbers, the regular run skipping the leaver, a month already finalized, a negative net left as a
receivable, the offboarding wizard's step and answer, and the owner API."""

import re
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from apps.core.exceptions import DomainError
from apps.finance.models import Debt
from apps.inbox.models import Notification
from apps.members import services as members
from apps.members.models import AccessRole, Membership
from apps.members.permissions import Perm
from apps.payroll import finance_bridge, queries, services, settlement
from apps.payroll.models import (
    Advance,
    PayrollRun,
    Payslip,
    PayslipLine,
)
from apps.payroll.tests.conftest import OCTOBER, local

pytestmark = pytest.mark.django_db

D = Decimal
Kind = PayslipLine.Kind
HIRED = date(2025, 10, 1)
LAST_DAY = date(2026, 10, 14)  # a Wednesday


def url(company, path=""):
    return f"/api/v1/owner/companies/{company.pk}/payroll/{path}"


@pytest.fixture
def leaving(freeze):
    """The clock stands at 10:00 on Thursday 15 October 2026, the day after Ali's last day."""
    return freeze(local(date(2026, 10, 15), 10))


@pytest.fixture
def hired(monkeypatch, staff):
    """Everyone has worked here since 1 October 2025 (fixed employment dates); a test puts
    someone's last day in `staff.ends`."""
    staff.ends = {}

    def employment_dates(company, member_ids):
        return {pk: (HIRED, staff.ends.get(pk)) for pk in member_ids}

    monkeypatch.setattr("apps.hr.queries.employment_dates", employment_dates)
    return staff


@pytest.fixture
def team(hired, leaving):
    """Ali 5 200 000 a month, Sara 4 680 000 (both from 1 October 2025)."""
    staff = hired
    services.set_pay(staff.ali, by=None, effective_from=HIRED, amount="5200000")
    services.set_pay(staff.sara, by=None, effective_from=HIRED, amount="4680000")
    return staff


def history(shop, member, *, months=12, base="5200000", overtime="275000"):
    """Finalized regular payslips for the months before October 2026: 12 x (5 200 000 base +
    275 000 overtime) = 65 700 000 over the 365 days of October 2025 to September 2026."""
    period = OCTOBER
    for _ in range(months):
        period = date(period.year - (period.month == 1), (period.month - 2) % 12 + 1, 1)
        run, _created = PayrollRun.objects.get_or_create(
            company=shop,
            kind=PayrollRun.Kind.REGULAR,
            period=period,
            defaults={"status": PayrollRun.Status.PAID},
        )
        gross = D(base) + D(overtime)
        payslip = Payslip.objects.create(
            company=shop,
            run=run,
            membership=member,
            currency="UZS",
            pay_type="monthly",
            base_pay=D(base),
            scheduled_days=D(26),
            paid_days=D(26),
            gross=gross,
            net=gross,
            status=Payslip.Status.PAID,
        )
        PayslipLine.objects.create(payslip=payslip, kind=Kind.BASE, label="Base", amount=D(base))
        PayslipLine.objects.create(
            payslip=payslip, kind=Kind.OVERTIME, label="Overtime", amount=D(overtime), order=1
        )
        # A one-off bonus never counts in the average day.
        PayslipLine.objects.create(
            payslip=payslip, kind=Kind.BONUS, label="Bonus", amount=D("1000000"), order=2
        )


def give_advance(staff, cash, member, amount):
    row = services.create_advance(member, by=staff.owner, amount=amount)
    return services.pay_advance(row, by=staff.accountant, account=cash)


def leave(member):
    Membership.objects.filter(pk=member.pk).update(status=Membership.Status.LEFT)
    member.refresh_from_db()
    return member


def lines(payslip, kind):
    return [line for line in payslip.lines.all() if line.kind == kind]


class TestGolden:
    def test_the_final_settlement_of_14_october(self, shop, team, cash):
        """§3.17: 11 of 26 days → 2 200 000; 5.5 days at a = 180 000 → 990 000; the advance of
        500 000 deducted in full → net 2 690 000."""
        staff = team
        history(shop, staff.ali)
        advance = give_advance(staff, cash, staff.ali, "500000")
        leave(staff.ali)

        run = services.create_final_run(
            staff.ali, by=staff.accountant, last_day=LAST_DAY, leave_days="5,5"
        )

        assert run.kind == "final" and run.status == "draft"
        assert run.period == OCTOBER and run.last_day == LAST_DAY
        assert run.leave_days == D("5.50") and not run.after_regular
        payslip = run.payslips.get()
        assert payslip.membership == staff.ali
        assert payslip.base_pay == D("2200000.00")
        assert payslip.paid_days == D(11) and payslip.scheduled_days == D(26)
        payout = lines(payslip, Kind.LEAVE_PAYOUT)[0]
        assert payout.amount == D("990000.00")
        assert payout.quantity == D("5.50") and payout.rate == D("180000.00")
        assert payout.params["basis"] == "history"
        assert payout.params["history_gross"] == "65700000.00"
        assert payout.params["history_days"] == "365.00"
        taken = lines(payslip, Kind.ADVANCE)[0]
        assert taken.amount == D("-500000.00") and taken.params["in_full"]
        assert payslip.net == D("2690000.00")
        assert run.totals["net"] == "2690000.00" and run.totals["people"] == 1

        services.finalize_run(run, by=staff.owner)
        payslip.refresh_from_db()
        salary = payslip.salary_debt
        assert salary.amount == D("3190000.00") and salary.paid == D("500000.00")
        assert salary.issued_on == LAST_DAY
        advance.refresh_from_db()
        assert advance.status == Advance.Status.REPAID
        assert advance.debt.status == Debt.Status.PAID

        services.mark_paid(run, by=staff.accountant, payslip_ids=[payslip.pk], account=cash)
        run.refresh_from_db()
        salary.refresh_from_db()
        assert run.status == "paid" and salary.status == Debt.Status.PAID

    def test_without_a_full_month_of_history_a_day_is_the_monthly_pay_over_its_days(
        self, shop, team
    ):
        staff = team
        leave(staff.ali)
        run = services.create_final_run(
            staff.ali, by=staff.accountant, last_day=LAST_DAY, leave_days="5.5"
        )
        payout = lines(run.payslips.get(), Kind.LEAVE_PAYOUT)[0]
        # 5 200 000 / 31 calendar days, times 5.5
        assert payout.params["basis"] == "current_pay" and payout.params["divisor"] == "31.00"
        assert payout.amount == D("922580.65")
        assert "leave_current_pay" in [w["code"] for w in run.warnings]

    def test_leave_counted_in_working_days(self, shop, team):
        staff = team
        history(shop, staff.ali)
        services.update_settings(shop, by=staff.owner, leave_payout_unit="work_days")
        day, params = settlement.average_day(staff.ali, OCTOBER, last_day=LAST_DAY)
        # 65 700 000 over 12 months of 26 paid days.
        assert params["history_days"] == "312.00"
        assert day == D("65700000") / D(312)


class TestRegularRun:
    def test_the_regular_run_skips_the_leaver(self, shop, team):
        staff = team
        leave(staff.ali)
        services.create_final_run(staff.ali, by=staff.accountant, last_day=LAST_DAY)
        regular = services.create_run(shop, by=staff.accountant, period="2026-10")
        assert set(regular.payslips.values_list("membership_id", flat=True)) == {staff.sara.pk}

    def test_their_draft_payslip_moves_to_the_final_run_with_its_hand_made_lines(self, shop, team):
        staff = team
        regular = services.create_run(shop, by=staff.accountant, period="2026-10")
        old = regular.payslips.get(membership=staff.ali)
        services.set_manual_lines(
            old, by=staff.accountant, lines=[{"label": "Taxi to the warehouse", "amount": "45000"}]
        )
        leave(staff.ali)

        run = services.create_final_run(staff.ali, by=staff.accountant, last_day=LAST_DAY)

        regular.refresh_from_db()
        assert not regular.payslips.filter(membership=staff.ali).exists()
        assert regular.totals["people"] == 1
        payslip = run.payslips.get()
        assert [line.label for line in lines(payslip, Kind.MANUAL)] == ["Taxi to the warehouse"]
        assert payslip.net == D("2245000.00")

    def test_a_finalized_month_leaves_only_the_rest_to_the_final_run(
        self, shop, team, cash, freeze
    ):
        """October was finalized on the 26th; Ali's last day is Wednesday the 28th."""
        staff = team
        history(shop, staff.ali)
        freeze(local(date(2026, 10, 26), 10))
        regular = services.create_run(shop, by=staff.accountant, period="2026-10")
        services.finalize_run(regular, by=staff.owner)
        assert regular.payslips.get(membership=staff.ali).net == D("5200000.00")
        freeze(local(date(2026, 10, 29), 10))
        leave(staff.ali)
        staff.ends[staff.ali.pk] = date(2026, 10, 28)

        run = services.create_final_run(
            staff.ali, by=staff.accountant, last_day=date(2026, 10, 28), leave_days="5.5"
        )

        assert run.after_regular
        payslip = run.payslips.get()
        assert not lines(payslip, Kind.BASE) and not lines(payslip, Kind.PRORATION)
        assert payslip.net == D("990000.00")
        codes = {w["code"]: w for w in run.warnings}
        assert "after_regular" in codes
        # Thursday 29 to Saturday 31 October: 3 days at 200 000 paid after the last day.
        assert codes["paid_after_last_day"]["amount"] == "600000.00"
        assert codes["paid_after_last_day"]["days"] == "3.00"
        # Reopened, the month still pays Ali (now through the last day).
        services.reopen_run(regular, by=staff.owner)
        services.calculate_run(regular, by=staff.accountant)
        assert regular.payslips.get(membership=staff.ali).net == D("4600000.00")


class TestNegativeNet:
    def test_what_the_pay_cant_cover_stays_owed_on_the_advance(self, shop, team, cash):
        """Last day Monday 5 October: 3 days → 600 000 against an advance of 3 000 000."""
        staff = team
        advance = give_advance(staff, cash, staff.ali, "3000000")
        leave(staff.ali)

        run = services.create_final_run(staff.ali, by=staff.accountant, last_day=date(2026, 10, 5))
        payslip = run.payslips.get()
        assert payslip.base_pay == D("600000.00")
        assert payslip.net == D("-2400000.00")
        owes = next(w for w in run.warnings if w["code"] == "owes")
        assert owes["amount"] == "2400000.00" and owes["level"] == "info"

        services.finalize_run(run, by=staff.owner)
        advance.refresh_from_db()
        debt = advance.debt
        assert advance.status == Advance.Status.PAID
        assert queries.advance_left(advance) == D("2400000.00")
        assert debt.direction == Debt.Direction.RECEIVABLE and debt.status == Debt.Status.OPEN
        assert debt.amount - debt.paid == D("2400000.00")
        payslip.refresh_from_db()
        assert payslip.salary_debt.amount == D("600000.00")
        assert payslip.salary_debt.status == Debt.Status.PAID  # all of it offset

        # Reopening gives the advance back all it was owed.
        services.reopen_run(run, by=staff.owner)
        debt.refresh_from_db()
        assert debt.amount - debt.paid == D("3000000.00")
        assert finance_bridge.booked_total(run) == 0

        # Paying it moves no money: there is nothing to pay.
        services.finalize_run(run, by=staff.owner)
        cash.refresh_from_db()
        before = cash.balance
        services.mark_paid(run, by=staff.accountant, payslip_ids=[payslip.pk], account=cash)
        cash.refresh_from_db()
        run.refresh_from_db()
        assert run.status == "paid" and cash.balance == before

    def test_hand_made_deductions_never_take_the_pay_below_zero(self, shop, team):
        staff = team
        leave(staff.ali)
        run = services.create_final_run(staff.ali, by=staff.accountant, last_day=date(2026, 10, 5))
        services.set_manual_lines(
            run.payslips.get(),
            by=staff.accountant,
            lines=[{"label": "Broken fridge", "amount": "-900000"}],
        )
        with pytest.raises(DomainError, match="more than the pay"):
            services.finalize_run(run, by=staff.owner)


class TestRules:
    def test_only_for_someone_who_left_once_and_with_a_pay_setup(self, shop, team):
        staff = team
        with pytest.raises(DomainError, match="left"):
            services.create_final_run(staff.ali, by=staff.accountant, last_day=LAST_DAY)
        leave(staff.ali)
        leave(staff.vali)
        with pytest.raises(DomainError, match="no pay setup"):
            services.create_final_run(staff.vali, by=staff.accountant, last_day=LAST_DAY)
        with pytest.raises(PermissionDenied):
            services.create_final_run(staff.ali, by=staff.manager, last_day=LAST_DAY)
        services.create_final_run(staff.ali, by=staff.accountant, last_day=LAST_DAY)
        with pytest.raises(DomainError, match="already"):
            services.create_final_run(staff.ali, by=staff.accountant, last_day=LAST_DAY)

    def test_the_leave_days_change_on_the_draft_only(self, shop, team):
        staff = team
        history(shop, staff.ali)
        leave(staff.ali)
        run = services.create_final_run(staff.ali, by=staff.accountant, last_day=LAST_DAY)
        assert not lines(run.payslips.get(), Kind.LEAVE_PAYOUT)
        run = services.set_leave_days(run, by=staff.accountant, leave_days="2")
        assert lines(run.payslips.get(), Kind.LEAVE_PAYOUT)[0].amount == D("360000.00")
        with pytest.raises(DomainError, match="0 to 366"):
            services.set_leave_days(run, by=staff.accountant, leave_days="-1")
        services.finalize_run(run, by=staff.owner)
        with pytest.raises(DomainError, match="draft"):
            services.set_leave_days(run, by=staff.accountant, leave_days="3")


class TestOffboarding:
    def test_the_wizard_prepares_the_draft_and_tells_payroll(
        self, shop, team, django_capture_on_commit_callbacks
    ):
        staff = team
        history(shop, staff.ali)
        with django_capture_on_commit_callbacks(execute=True):
            members.complete_offboarding(
                staff.ali,
                by=staff.owner,
                terminated_on=LAST_DAY,
                reason="resignation",
                steps={"payroll": {"prepare": True, "leave_days": 5.5}},
            )
        run = PayrollRun.objects.get(kind="final", membership=staff.ali)
        assert run.last_day == LAST_DAY and run.leave_days == D("5.50")
        assert run.payslips.get().net == D("3190000.00")
        told = set(
            Notification.objects.filter(kind="payroll.final_run").values_list(
                "recipient_id", flat=True
            )
        )
        assert staff.accountant.pk in told and staff.owner.pk in told
        assert staff.manager.pk not in told  # payroll.propose only

    def test_switched_off_or_answered_no_nothing_is_prepared(
        self, shop, team, django_capture_on_commit_callbacks
    ):
        staff = team
        with django_capture_on_commit_callbacks(execute=True):
            members.complete_offboarding(
                staff.ali,
                by=staff.owner,
                terminated_on=LAST_DAY,
                reason="resignation",
                steps={"payroll": {"prepare": False}},
            )
        shop.features = [name for name in shop.features if name != "payroll"]
        shop.save(update_fields=["features"])
        with django_capture_on_commit_callbacks(execute=True):
            members.complete_offboarding(
                staff.sara, by=staff.owner, terminated_on=LAST_DAY, reason="resignation"
            )
        assert not PayrollRun.objects.filter(kind="final").exists()

    def test_the_step_shows_pay_only_to_payroll_managers(self, shop, team, owner_api):
        staff = team
        history(shop, staff.ali)
        hr = AccessRole.objects.create(
            company=shop,
            name="HR",
            permissions=[
                Perm.DASHBOARD_ACCESS,
                Perm.MEMBERS_VIEW,
                Perm.MEMBERS_MANAGE,
                Perm.PAYROLL_VIEW,
            ],
        )
        clerk = staff.lead
        clerk.role = hr
        clerk.save(update_fields=["role"])
        path = f"/api/v1/owner/companies/{shop.pk}/people/{staff.ali.pk}/offboard-preview/"

        steps = {step["key"]: step for step in owner_api(staff.owner).get(path).json()["steps"]}
        step = steps["payroll"]
        assert step["label"] == "Final payslip"
        assert step["defaults"] == {"prepare": True, "leave_days": 0}
        assert [field["name"] for field in step["fields"]] == ["prepare", "leave_days"]
        text = re.sub(r"\s", "", " ".join(step["lines"]))
        assert "2400000" in text  # 12 of 26 days if they left today (15 October)
        assert "180000" in text  # what one unused leave day pays

        seen = owner_api(clerk).get(path)
        assert seen.status_code == 200
        assert "payroll" not in {step["key"] for step in seen.json()["steps"]}

    def test_no_pay_setup_nothing_to_settle(self, shop, team, owner_api):
        staff = team
        path = f"/api/v1/owner/companies/{shop.pk}/people/{staff.vali.pk}/offboard-preview/"
        step = next(
            s for s in owner_api(staff.owner).get(path).json()["steps"] if s["key"] == "payroll"
        )
        assert step["defaults"] == {"prepare": False} and not step["fields"]


class TestApi:
    def test_final_runs_in_the_list_and_their_page(self, shop, team, owner_api):
        staff = team
        history(shop, staff.ali)
        leave(staff.ali)
        client = owner_api(staff.accountant)
        made = client.post(url(shop, "runs/final/"), {"member": staff.ali.pk}, format="json")
        assert made.status_code == 201, made.content
        data = made.json()
        assert data["kind"] == "final" and data["member"]["id"] == staff.ali.pk
        assert data["last_day"] == "2026-10-15"  # no last day on file: today
        assert "leave_payout" in data["actions"]
        listed = client.get(url(shop, "runs/?kind=final")).json()["results"]
        assert [row["id"] for row in listed] == [data["id"]]

        changed = client.post(
            url(shop, f"runs/{data['id']}/leave-payout/"), {"leave_days": "5.5"}, format="json"
        )
        assert changed.status_code == 200, changed.content
        assert changed.json()["leave_days"] == "5.50"
        payslips = client.get(url(shop, f"runs/{data['id']}/payslips/")).json()["results"]
        assert payslips[0]["run_kind"] == "final"
        assert D(payslips[0]["extras"]) == D("990000.00")

    def test_another_company_and_permissions(self, shop, team, owner_api, other_company, member):
        staff = team
        leave(staff.ali)
        stranger = member.registered(other_company, "Employee")
        client = owner_api(staff.accountant)
        made = client.post(url(shop, "runs/final/"), {"member": stranger.pk}, format="json")
        assert made.status_code == 404
        # payroll.propose only: no final runs.
        denied = owner_api(staff.manager).post(
            url(shop, "runs/final/"), {"member": staff.ali.pk}, format="json"
        )
        assert denied.status_code == 403
        run = services.create_final_run(staff.ali, by=staff.accountant, last_day=LAST_DAY)
        assert (
            owner_api(staff.manager)
            .post(url(shop, f"runs/{run.pk}/leave-payout/"), {"leave_days": "1"}, format="json")
            .status_code
            == 403
        )
        other_owner = member.registered(other_company, "Owner")
        other_company.features = ["payroll"]
        other_company.save(update_fields=["features"])
        assert owner_api(other_owner).get(url(other_company, f"runs/{run.pk}/")).status_code == 404
        # A regular run has no leave to pay out.
        regular = services.create_run(shop, by=staff.accountant, period="2026-10")
        wrong = client.post(
            url(shop, f"runs/{regular.pk}/leave-payout/"), {"leave_days": "1"}, format="json"
        )
        assert wrong.status_code == 400


def test_the_pdf_of_a_final_payslip_below_zero(shop, team, cash):
    from apps.payroll import payslip_pdf

    staff = team
    give_advance(staff, cash, staff.ali, "3000000")
    leave(staff.ali)
    run = services.create_final_run(staff.ali, by=staff.accountant, last_day=date(2026, 10, 5))
    data = payslip_pdf.context(run.payslips.get())
    assert data["title"].startswith("Final payslip")
    assert "Last working day: 05.10.2026" in data["facts"]
    assert data["net_label"] == "They owe the company"
    assert re.sub(r"\s", "", data["net"]).startswith("2400000")
    assert data["owes_note"]
