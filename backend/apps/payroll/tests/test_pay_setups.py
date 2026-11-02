"""Pay setups (effective-dated compensations), task rates and the payroll settings: the
services, the owner API and its permissions."""

from datetime import date
from decimal import Decimal

import pytest

from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.payroll import queries, services
from apps.payroll.models import Compensation, PayrollRun, Payslip
from apps.payroll.tests.conftest import OCTOBER

pytestmark = pytest.mark.django_db


def url(company, path=""):
    return f"/api/v1/owner/companies/{company.pk}/payroll/{path}"


def test_a_change_is_a_new_row_and_the_setup_in_force_follows_the_dates(shop, staff, today):
    first = services.set_pay(
        staff.ali, by=staff.owner, effective_from=date(2026, 1, 1), amount=Decimal("5200000")
    )
    raise_ = services.set_pay(
        staff.ali, by=staff.owner, effective_from=date(2026, 11, 1), amount="6000000"
    )
    assert queries.compensation(staff.ali) == first
    assert queries.compensation(staff.ali, on=date(2026, 11, 1)) == raise_
    assert queries.compensation(staff.ali, on=date(2025, 12, 31)) is None
    assert first.currency == "UZS" and first.pay_type == "monthly"
    assert first.proration == "attendance" and first.overtime_eligible
    # The pay change is on the person's History, readable only with payroll.view.
    log = AuditLog.objects.get(action="payroll.pay_set", details__compensation=raise_.pk)
    assert log.target_type == "membership" and log.target_id == staff.ali.pk
    assert log.required_perm == "payroll.view"
    with pytest.raises(DomainError):
        services.set_pay(staff.ali, by=staff.owner, effective_from=date(2026, 11, 1), amount=1)


def test_locked_setups_are_read_only_and_finalized_months_closed(shop, staff, today):
    row = services.set_pay(staff.ali, by=staff.owner, effective_from=date(2026, 1, 1), amount=100)
    run = PayrollRun.objects.create(company=shop, period=OCTOBER, status="finalized")
    Payslip.objects.create(company=shop, run=run, membership=staff.ali, pay_type="monthly")
    assert services.lock_pay(staff.ali, date(2026, 10, 1), date(2026, 10, 31)) == 1
    row.refresh_from_db()
    assert row.locked
    with pytest.raises(DomainError, match="Add a new one"):
        services.update_pay(row, by=staff.owner, amount=200)
    with pytest.raises(DomainError):
        services.remove_pay(row, by=staff.owner)
    # A new setup can't start inside the finalized October.
    with pytest.raises(DomainError, match=r"31\.10\.2026"):
        services.set_pay(staff.ali, by=staff.owner, effective_from=date(2026, 10, 20), amount=300)
    later = services.set_pay(
        staff.ali, by=staff.owner, effective_from=date(2026, 11, 1), amount=300
    )
    assert not later.locked
    # Reopening the run unlocks what no finalized run uses any more.
    run.status = "draft"
    run.save()
    assert services.unlock_pay(shop) == 1


def test_propose_pay_change_keeps_what_it_does_not_change(shop, staff, today):
    services.set_pay(
        staff.ali,
        by=staff.owner,
        effective_from=date(2026, 1, 1),
        amount=5200000,
        pays_task_rates=True,
    )
    row = services.propose_pay_change(
        staff.ali,
        by=staff.owner,
        setup={"amount": Decimal("6000000")},
        effective_on=date(2026, 12, 1),
        reason="Promotion to senior pharmacist",
    )
    assert row.amount == Decimal("6000000.00") and row.pays_task_rates
    assert row.note == "Promotion to senior pharmacist"
    again = services.propose_pay_change(
        staff.ali,
        by=staff.owner,
        setup={"amount": "6500000"},
        effective_on=date(2026, 12, 1),
        reason="Raised a bit more",
    )
    assert again.pk == row.pk and again.amount == Decimal("6500000.00")


def test_pay_setups_need_payroll_manage(shop, staff, today):
    with pytest.raises(Exception, match="permission"):
        services.set_pay(staff.ali, by=staff.manager, effective_from=OCTOBER, amount=1)


class TestApi:
    def test_create_list_and_hide_amounts(self, shop, staff, owner_api, today):
        client = owner_api(staff.accountant)
        response = client.post(
            url(shop, "compensations/"),
            {
                "membership": staff.ali.pk,
                "effective_from": "2026-01-01",
                "pay_type": "monthly",
                "amount": "5200000",
            },
            format="json",
        )
        assert response.status_code == 201, response.data
        assert response.data["amount"] == "5200000.00"
        assert response.data["member"]["id"] == staff.ali.pk
        listed = client.get(url(shop, "compensations/"), {"member": staff.ali.pk})
        assert listed.status_code == 200 and listed.data["count"] == 1
        # A manager holds payroll.propose only: no pay setups at all.
        assert owner_api(staff.manager).get(url(shop, "compensations/")).status_code == 403

    def test_people_lists_everyone_with_and_without_a_setup(self, shop, staff, owner_api, today):
        services.set_pay(staff.ali, by=staff.owner, effective_from=date(2026, 1, 1), amount=100)
        services.set_pay(staff.ali, by=staff.owner, effective_from=date(2026, 12, 1), amount=200)
        response = owner_api(staff.owner).get(url(shop, "compensations/people/"))
        assert response.status_code == 200
        rows = {row["member"]["id"]: row for row in response.data["results"]}
        assert rows[staff.ali.pk]["current"]["amount"] == "100.00"
        assert rows[staff.ali.pk]["next"]["effective_from"] == "2026-12-01"
        assert rows[staff.vali.pk]["current"] is None

    def test_locked_rows_answer_400_with_the_reason(self, shop, staff, owner_api, today):
        row = services.set_pay(staff.ali, by=staff.owner, effective_from=OCTOBER, amount=100)
        Compensation.objects.filter(pk=row.pk).update(locked=True)
        client = owner_api(staff.owner)
        response = client.patch(url(shop, f"compensations/{row.pk}/"), {"amount": "5"})
        assert response.status_code == 400
        detail = client.get(url(shop, f"compensations/{row.pk}/")).data
        assert detail["locked"] and detail["locked_reason"]
        assert client.delete(url(shop, f"compensations/{row.pk}/")).status_code == 400

    def test_another_company_and_other_people_are_404(
        self, shop, staff, owner_api, other_company, member, today
    ):
        outsider = member(other_company, "Owner")
        assert owner_api(outsider).get(url(shop, "compensations/")).status_code == 404
        stranger = member(other_company)
        response = owner_api(staff.owner).post(
            url(shop, "compensations/"),
            {"membership": stranger.pk, "effective_from": "2026-10-01", "amount": "1"},
            format="json",
        )
        assert response.status_code == 404

    def test_module_off_answers_403(self, shop, staff, owner_api, today):
        shop.features = ["finance"]
        shop.save(update_fields=["features"])
        assert owner_api(staff.owner).get(url(shop, "compensations/")).status_code == 403


class TestSettings:
    def test_read_and_change(self, shop, staff, owner_api):
        client = owner_api(staff.accountant)
        data = client.get(url(shop, "settings/")).data
        assert data["night_multiplier"] == "1.50" and data["night_starts_at"] == "22:00:00"
        assert data["daily_hours"] == "8.00" and data["rounding_step"] == "1000.00"
        assert data["taxes_enabled"] is False and data["deductions_cap_percent"] == "20.00"
        response = client.patch(
            url(shop, "settings/"),
            {"night_multiplier": "2.00", "pay_day": 10, "rounding_step": "0"},
            format="json",
        )
        assert response.status_code == 200, response.data
        assert response.data["night_multiplier"] == "2.00" and response.data["pay_day"] == 10
        assert AuditLog.objects.filter(action="payroll.settings_changed").exists()

    def test_bad_values_and_permissions(self, shop, staff, owner_api):
        client = owner_api(staff.owner)
        assert client.patch(url(shop, "settings/"), {"pay_day": 31}).status_code == 400
        assert client.patch(url(shop, "settings/"), {"night_multiplier": "0.5"}).status_code == 400
        response = client.patch(
            url(shop, "settings/"),
            {"night_starts_at": "06:00", "night_ends_at": "06:00"},
            format="json",
        )
        assert response.status_code == 400
        assert owner_api(staff.manager).get(url(shop, "settings/")).status_code == 403


class TestTaskRates:
    def test_crud(self, shop, staff, owner_api):
        client = owner_api(staff.owner)
        response = client.post(
            url(shop, "task-rates/"),
            {"position": staff.pharmacist.pk, "amount": "5000", "on_time_only": True},
            format="json",
        )
        assert response.status_code == 201, response.data
        rate = response.data
        assert rate["position"]["name"] == "Pharmacist" and rate["amount"] == "5000.00"
        changed = client.patch(
            url(shop, f"task-rates/{rate['id']}/"), {"amount": "6000"}, format="json"
        )
        assert changed.data["amount"] == "6000.00"
        assert len(client.get(url(shop, "task-rates/")).data) == 1
        assert client.delete(url(shop, f"task-rates/{rate['id']}/")).status_code == 204
        assert owner_api(staff.manager).get(url(shop, "task-rates/")).status_code == 403
