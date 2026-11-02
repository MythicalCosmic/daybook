"""Bonuses, fines, allowances and deductions: propose → approve / reject / void, disputes and
answers, bulk decisions, `propose_fine` for other apps, the owner and employee API."""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.inbox.models import Notification
from apps.payroll import queries, services
from apps.payroll.models import Adjustment, PayrollRun
from apps.payroll.tests.conftest import OCTOBER

pytestmark = pytest.mark.django_db


def url(company, path=""):
    return f"/api/v1/owner/companies/{company.pk}/payroll/{path}"


def my_url(company, path=""):
    return f"/api/v1/companies/{company.pk}/payroll/{path}"


@pytest.fixture
def fine(staff, today, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        return services.propose(
            staff.ali,
            by=staff.manager,
            kind="fine",
            amount=Decimal("50000"),
            reason="Late for the shift three times",
        )


def test_propose_then_approve(shop, staff, fine, django_capture_on_commit_callbacks):
    assert fine.status == "proposed" and fine.period == OCTOBER and fine.currency == "UZS"
    assert fine.source == "manual" and fine.proposed_by == staff.manager.user
    # The approvers hear about it in Telegram (a Needs-you kind: no in-app row).
    sent = Notification.objects.filter(kind="payroll.adjustment", target_id=fine.pk)
    assert {n.recipient_id for n in sent} == {staff.owner.pk, staff.accountant.pk}
    assert queries.pending_count(staff.owner) == 1
    with django_capture_on_commit_callbacks(execute=True):
        services.approve(fine, by=staff.accountant)
    fine.refresh_from_db()
    assert fine.status == "approved" and fine.decided_by == staff.accountant.user
    told = Notification.objects.get(kind="payroll.adjustment_decided", recipient=staff.ali)
    assert "50" in told.title and told.app_screen == "wallet"
    assert AuditLog.objects.filter(
        action="payroll.adjustment_approved", target_type="membership", target_id=staff.ali.pk
    ).exists()
    assert queries.pending_count(staff.owner) == 0
    with pytest.raises(DomainError, match="already decided"):
        services.reject(fine, by=staff.owner, reason="no")


def test_rules_of_proposing(shop, staff, today):
    with pytest.raises(DomainError, match="yourself"):
        services.propose(staff.manager, by=staff.manager, kind="bonus", amount=1, reason="x")
    with pytest.raises(DomainError, match="Say why"):
        services.propose(staff.ali, by=staff.manager, kind="bonus", amount=1, reason=" ")
    with pytest.raises(DomainError):
        services.propose(staff.ali, by=staff.manager, kind="bonus", amount=0, reason="x")
    with pytest.raises(PermissionDenied):
        services.propose(staff.ali, by=staff.vali, kind="bonus", amount=1, reason="x")
    with pytest.raises(PermissionDenied):  # approving at once needs payroll.manage
        services.propose(
            staff.ali, by=staff.manager, kind="bonus", amount=1, reason="x", approve=True
        )
    PayrollRun.objects.create(company=shop, period=OCTOBER, status="finalized")
    with pytest.raises(DomainError, match="finalized"):
        services.propose(staff.ali, by=staff.manager, kind="bonus", amount=1, reason="x")
    later = services.propose(
        staff.ali, by=staff.manager, kind="bonus", amount=1, reason="x", period="2026-11"
    )
    assert later.period == date(2026, 11, 1)


def test_approving_your_own_is_refused(shop, staff, today):
    row = services.propose(staff.accountant, by=staff.owner, kind="bonus", amount=1, reason="x")
    with pytest.raises(DomainError, match="own"):
        services.approve(row, by=staff.accountant)


def test_dispute_and_answer(shop, staff, fine, django_capture_on_commit_callbacks):
    with pytest.raises(PermissionDenied):
        services.dispute(fine, by=staff.vali, text="Not me")
    with django_capture_on_commit_callbacks(execute=True):
        services.dispute(fine, by=staff.ali, text="The bus broke down")
    fine.refresh_from_db()
    assert fine.dispute_open and fine.dispute_text == "The bus broke down"
    assert Notification.objects.filter(kind="payroll.dispute", target_id=fine.pk).exists()
    with pytest.raises(DomainError, match="already disputed"):
        services.dispute(fine, by=staff.ali, text="Again")
    with django_capture_on_commit_callbacks(execute=True):
        services.answer_dispute(fine, by=staff.owner, answer="Fair: taken back", void_it=True)
    fine.refresh_from_db()
    assert fine.status == "void" and not fine.dispute_open
    assert Notification.objects.filter(
        kind="payroll.adjustment_decided", recipient=staff.ali, target_id=fine.pk
    ).exists()


def test_a_bonus_cannot_be_disputed(shop, staff, today):
    bonus = services.propose(staff.ali, by=staff.manager, kind="bonus", amount=1, reason="x")
    with pytest.raises(DomainError):
        services.dispute(bonus, by=staff.ali, text="More please")


def test_locked_adjustments_never_change(shop, staff, fine):
    services.approve(fine, by=staff.owner)
    run = PayrollRun.objects.create(company=shop, period=OCTOBER)
    payslip = run.payslips.create(company=shop, membership=staff.ali, pay_type="monthly")
    Adjustment.objects.filter(pk=fine.pk).update(payslip=payslip)
    fine.refresh_from_db()
    with pytest.raises(DomainError, match="finalized payslip"):
        services.void(fine, by=staff.owner, reason="Changed my mind")


def test_propose_fine_for_other_apps(shop, staff, today):
    row = services.propose_fine(
        staff.ali, by=staff.manager, amount="200000", reason="Storage breach", source="discipline"
    )
    assert row.kind == "fine" and row.source == "discipline" and row.status == "proposed"
    assert row.period == OCTOBER and row.amount == Decimal("200000.00")
    # A plain employee may issue it through their own app's permission check.
    assert (
        services.propose_fine(
            staff.ali, by=staff.vali, amount=1, reason="x", source="lifecycle.disciplinaryrecord"
        ).source
        == "discipline"
    )
    with pytest.raises(ValueError):
        services.propose_fine(staff.ali, by=staff.manager, amount=1, reason="x", source="moon")


def test_bulk_decide(shop, staff, today):
    rows = [
        services.propose(staff.ali, by=staff.manager, kind="bonus", amount=10, reason="x"),
        services.propose(staff.vali, by=staff.manager, kind="bonus", amount=20, reason="y"),
        services.propose(staff.accountant, by=staff.manager, kind="bonus", amount=30, reason="z"),
    ]
    results = services.bulk_decide(rows, by=staff.accountant, approve_them=True)
    assert [r["ok"] for r in results] == [True, True, False]  # not their own
    assert "own" in results[2]["error"]


class TestApi:
    def test_propose_list_approve(self, shop, staff, owner_api, today):
        response = owner_api(staff.manager).post(
            url(shop, "adjustments/"),
            {"membership": staff.ali.pk, "kind": "bonus", "amount": "300000", "reason": "Best"},
            format="json",
        )
        assert response.status_code == 201, response.data
        # The manager has no payroll.view: no amounts, even on their own proposal.
        assert "amount" not in response.data
        listed = owner_api(staff.manager).get(url(shop, "adjustments/"))
        assert listed.data["count"] == 1 and "amount" not in listed.data["results"][0]
        assert (
            owner_api(staff.manager)
            .post(url(shop, f"adjustments/{response.data['id']}/approve/"))
            .status_code
            == 403
        )
        approved = owner_api(staff.accountant).post(
            url(shop, f"adjustments/{response.data['id']}/approve/"), {}, format="json"
        )
        assert approved.status_code == 200 and approved.data["status"] == "approved"
        assert approved.data["amount"] == "300000.00"

    def test_filters(self, shop, staff, owner_api, fine):
        services.dispute(fine, by=staff.ali, text="No")
        client = owner_api(staff.owner)
        assert client.get(url(shop, "adjustments/"), {"disputed": "open"}).data["count"] == 1
        assert client.get(url(shop, "adjustments/"), {"period": "2026-11"}).data["count"] == 0
        assert client.get(url(shop, "adjustments/"), {"status": "approved"}).data["count"] == 0
        assert client.get(url(shop, "adjustments/"), {"kind": "fine"}).data["count"] == 1

    def test_answer_dispute_from_needs_you_reason(self, shop, staff, owner_api, fine):
        services.dispute(fine, by=staff.ali, text="No")
        response = owner_api(staff.owner).post(
            url(shop, f"adjustments/{fine.pk}/answer-dispute/"),
            {"reason": "Seen on camera"},
            format="json",
        )
        assert response.status_code == 200 and response.data["dispute_answer"] == "Seen on camera"
        assert response.data["status"] == "proposed"

    def test_bulk_decide_endpoint(self, shop, staff, owner_api, fine):
        response = owner_api(staff.owner).post(
            url(shop, "adjustments/bulk-decide/"),
            {"ids": [fine.pk, 999999], "approve": False, "reason": "Too harsh"},
            format="json",
        )
        assert response.status_code == 200
        assert [row["ok"] for row in response.data] == [True, False]

    def test_branch_scope(self, shop, staff, owner_api, today):
        # The lead proposes at Chilonzor only: Sara (Yunusobod) is out of reach.
        client = owner_api(staff.lead)
        response = client.post(
            url(shop, "adjustments/"),
            {"membership": staff.sara.pk, "kind": "bonus", "amount": "1", "reason": "x"},
            format="json",
        )
        assert response.status_code == 404
        ok = client.post(
            url(shop, "adjustments/"),
            {"membership": staff.ali.pk, "kind": "bonus", "amount": "1", "reason": "x"},
            format="json",
        )
        assert ok.status_code == 201

    def test_employee_sees_and_disputes_their_own(self, shop, staff, api_as, fine):
        client = api_as(staff.ali)
        rows = client.get(my_url(shop, "adjustments/")).data
        assert [row["id"] for row in rows] == [fine.pk]
        assert rows[0]["amount"] == "50000.00"
        disputed = client.post(
            my_url(shop, f"adjustments/{fine.pk}/dispute/"), {"text": "Not true"}, format="json"
        )
        assert disputed.status_code == 200 and disputed.data["dispute_open"]
        # Someone else's fine doesn't exist for Vali.
        assert api_as(staff.vali).get(my_url(shop, "adjustments/")).data == []
        assert (
            api_as(staff.vali)
            .post(my_url(shop, f"adjustments/{fine.pk}/dispute/"), {"text": "x"}, format="json")
            .status_code
            == 404
        )
