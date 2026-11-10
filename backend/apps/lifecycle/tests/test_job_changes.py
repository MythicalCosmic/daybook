"""Job changes: proposed, approved by someone who may (never about themselves), applied on their
day by the beat (once), the pay reaching payroll, the role following a new job title only within
what the approver may give, a change that can't apply, scope and hidden pay, and the person's
history in the dashboard and the mini app.

The clock stands at 10:00 on Wednesday 21 October 2026 (Asia/Tashkent).
"""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.hr.tests.conftest import DAY, local
from apps.inbox import services as inbox
from apps.inbox.models import Notification
from apps.lifecycle import job_changes, providers
from apps.lifecycle.models import JobChange
from apps.members.models import AccessRole, Department, Position
from apps.members.permissions import Perm

pytestmark = pytest.mark.django_db

NOVEMBER = date(2026, 11, 1)
DECEMBER = date(2026, 12, 1)


def base(company) -> str:
    return f"/api/v1/owner/companies/{company.pk}/lifecycle/job-changes/"


@pytest.fixture
def run(django_capture_on_commit_callbacks):
    def call(fn, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return fn(*args, **kwargs)

    return call


@pytest.fixture
def senior(shop):
    return Position.objects.create(company=shop, name="Senior pharmacist", order=3)


@pytest.fixture
def hr_lead(shop, staff):
    """Someone who runs HR and people for every branch, without the Manager role's rights."""
    role = AccessRole.objects.create(
        company=shop,
        name="HR lead",
        permissions=[
            Perm.DASHBOARD_ACCESS,
            Perm.HR_VIEW,
            Perm.HR_MANAGE,
            Perm.MEMBERS_MANAGE,
            Perm.ROLES_MANAGE,
            Perm.BRANCHES_ALL,
        ],
    )
    staff.manager.role = role
    staff.manager.save(update_fields=["role"])
    return staff.manager


@pytest.fixture
def paid(staff):
    from apps.payroll import services as payroll

    payroll.set_pay(staff.ali, by=None, effective_from=date(2025, 10, 1), amount="5200000")
    return staff


def test_a_new_position_waits_for_approval_and_applies_itself_on_its_day(
    shop, staff, senior, owner_api, run, freeze
):
    response = run(
        owner_api(staff.accountant).post,
        base(shop),
        {
            "member_id": staff.ali.pk,
            "effective_on": "2026-11-01",
            "position_id": senior.pk,
            "reason": "Ikki yil tajriba, provizor diplomi bor",
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["status"] == "proposed" and body["parts"] == ["position"]
    assert body["before"]["position"]["name"] == "Pharmacist"
    assert body["after"]["position"]["name"] == "Senior pharmacist"
    assert body["can"] == {"decide": False, "cancel": True, "retry": False}  # no members.manage
    change = JobChange.objects.get(pk=body["id"])

    # Whoever may decide hears (Needs you, a Telegram copy with buttons); the proposer doesn't.
    notice = Notification.objects.get(recipient=staff.owner, kind="lifecycle.job_change")
    assert notice.title == "Job change to approve: Ali Valiyev" and notice.in_app is False
    assert "Position: Senior pharmacist (was: Pharmacist)" in notice.body
    assert "Starts: 01.11.2026" in notice.body
    assert not Notification.objects.filter(
        recipient=staff.accountant, kind="lifecycle.job_change"
    ).exists()
    queue = owner_api(staff.owner).get(f"/api/v1/owner/companies/{shop.pk}/queue/").json()
    assert [
        str(item["id"]) for item in queue["items"] if item["kind"] == "lifecycle.job_changes"
    ] == [str(change.pk)]

    path = f"{base(shop)}{change.pk}/approve/"
    assert owner_api(staff.accountant).post(path).status_code == 403
    response = run(owner_api(staff.owner).post, path)
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "approved" and response.json()["upcoming"] is True
    decided = Notification.objects.get(
        recipient=staff.accountant, kind="lifecycle.job_change_update"
    )
    assert decided.title == "Job change approved: Ali Valiyev"

    freeze(local(date(2026, 10, 31), 23, 50))
    assert run(job_changes.apply_due) == 0
    freeze(local(NOVEMBER, 0, 5))
    assert run(job_changes.apply_due) == 1
    staff.ali.refresh_from_db()
    change.refresh_from_db()
    assert staff.ali.position_id == senior.pk
    assert change.status == "applied" and change.applied_at is not None
    assert change.after["position"]["name"] == "Senior pharmacist"
    row = AuditLog.objects.get(action="lifecycle.change_applied")
    assert row.target_id == staff.ali.pk
    assert row.details["position"] == ["Pharmacist", "Senior pharmacist"]
    told = Notification.objects.get(recipient=staff.ali, kind="lifecycle.job_changed")
    assert told.title == "Your job has changed" and told.app_screen == "lifecycle.career"
    assert "Position: Senior pharmacist" in told.body

    assert run(job_changes.apply_due) == 0  # once only


def test_a_pay_change_reaches_payroll_on_its_day(shop, paid, owner_api, run, freeze):
    from apps.payroll import queries as payroll

    staff = paid
    response = run(
        owner_api(staff.owner).post,
        base(shop),
        {
            "member_id": staff.ali.pk,
            "effective_on": "2026-12-01",
            "pay_amount": "6000000",
            "reason": "Yillik ko‘rib chiqish",
            "approve": True,
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["status"] == "approved" and body["parts"] == ["pay"]
    assert body["after"]["pay"] == {
        "amount": "6000000.00",
        "currency": "UZS",
        "pay_type": "monthly",
    }
    assert body["before"]["pay"]["amount"] == "5200000.00"
    # The pay is for payroll.view: the manager reads the change without it.
    hidden = owner_api(staff.manager).get(f"{base(shop)}{body['id']}/").json()
    assert hidden["has_pay"] is True
    assert hidden["before"]["pay"] is None and hidden["after"]["pay"] is None
    assert "6000000" not in str(AuditLog.objects.filter(action__startswith="lifecycle.").values())

    freeze(local(DECEMBER, 8))
    assert run(job_changes.apply_due) == 1
    assert payroll.compensation(staff.ali, on=DECEMBER).amount == Decimal("6000000")
    assert payroll.compensation(staff.ali, on=date(2026, 11, 30)).amount == Decimal("5200000")
    change = JobChange.objects.get(pk=body["id"])
    assert change.status == "applied" and change.after["pay"]["amount"] == "6000000.00"
    assert "Your pay changes too" in Notification.objects.get(kind="lifecycle.job_changed").body


def test_approved_on_its_day_it_applies_at_once_and_a_transfer_moves_the_home_branch(
    shop, staff, yunusobod, chilonzor, run
):
    change = run(
        job_changes.propose,
        staff.ali,
        by=staff.owner,
        effective_on=DAY,
        reason="Yunusobodda farmatsevt yetishmaydi",
        branch=yunusobod,
        approve=True,
    )
    assert change.status == "applied"
    staff.ali.refresh_from_db()
    assert staff.ali.home_branch_id == yunusobod.pk
    assert set(staff.ali.branches.values_list("pk", flat=True)) == {yunusobod.pk}
    assert change.before["branch"]["name"] == "Chilonzor"
    assert change.after["branch"]["name"] == "Yunusobod"
    assert [ref["name"] for ref in change.after["branches"]] == ["Yunusobod"]


def test_the_role_follows_the_new_title_only_within_what_the_approver_may_give(
    shop, staff, hr_lead, run
):
    manager_role = AccessRole.objects.get(company=shop, name="Manager")
    head = Position.objects.create(company=shop, name="Head of pharmacy", role=manager_role)
    employee = staff.ali.role

    change = run(
        job_changes.propose,
        staff.ali,
        by=hr_lead,
        effective_on=DAY,
        reason="Mudir bo‘ldi",
        position=head,
        approve=True,
    )
    staff.ali.refresh_from_db()
    assert change.status == "applied" and staff.ali.position_id == head.pk
    assert staff.ali.role_id == employee.pk  # HR lead can't give the Manager role
    assert change.after["role"]["name"] == change.before["role"]["name"] == employee.name

    other = run(
        job_changes.propose,
        staff.vali,
        by=staff.owner,
        effective_on=DAY,
        reason="Mudir bo‘ldi",
        position=head,
        approve=True,
    )
    staff.vali.refresh_from_db()
    assert staff.vali.role_id == manager_role.pk
    assert other.after["role"]["name"] == "Manager"
    row = AuditLog.objects.filter(action="lifecycle.change_applied", target_id=staff.vali.pk).get()
    assert row.details["role"] == [employee.name, "Manager"]


def test_who_may_propose_and_decide(shop, staff, senior, yunusobod, run):
    department = Department.objects.create(company=shop, name="Kassa")
    # Nobody changes their own job; an owner's only an owner may.
    with pytest.raises(DomainError):
        job_changes.propose(
            staff.owner, by=staff.owner, effective_on=DAY, reason="X", position=senior
        )
    with pytest.raises(PermissionDenied):
        job_changes.propose(
            staff.owner, by=staff.accountant, effective_on=DAY, reason="X", position=senior
        )
    mine = run(
        job_changes.propose,
        staff.accountant,
        by=staff.owner,
        effective_on=NOVEMBER,
        reason="Bosh hisobchi",
        department=department,
    )
    with pytest.raises(DomainError):
        job_changes.approve(mine, by=staff.accountant)
    # The branch lead (hr.manage at Chilonzor, no members.manage, no payroll.manage).
    proposed = run(
        job_changes.propose,
        staff.ali,
        by=staff.lead,
        effective_on=NOVEMBER,
        reason="Kassa bo‘limiga",
        department=department,
    )
    with pytest.raises(PermissionDenied):
        job_changes.approve(proposed, by=staff.lead)
    with pytest.raises(PermissionDenied):
        job_changes.propose(
            staff.vali, by=staff.lead, effective_on=NOVEMBER, reason="X", pay_amount="1"
        )
    with pytest.raises(PermissionDenied, match="branches you manage"):
        job_changes.propose(
            staff.vali, by=staff.lead, effective_on=NOVEMBER, reason="X", branch=yunusobod
        )
    with pytest.raises(PermissionDenied):
        job_changes.propose(
            staff.sara, by=staff.lead, effective_on=NOVEMBER, reason="X", position=senior
        )
    # One open change a part; nothing that changes nothing; never before today.
    store = Department.objects.create(company=shop, name="Ombor")
    with pytest.raises(DomainError, match="already waits"):
        job_changes.propose(
            staff.ali, by=staff.owner, effective_on=DECEMBER, reason="X", department=store
        )
    with pytest.raises(DomainError, match="Nothing changes"):
        job_changes.propose(
            staff.vali, by=staff.owner, effective_on=DECEMBER, reason="X", position=staff.pharmacist
        )
    with pytest.raises(DomainError, match="today or later"):
        job_changes.propose(
            staff.vali, by=staff.owner, effective_on=date(2026, 10, 20), reason="X", position=senior
        )
    # Rejected with a reason the proposer reads; cancelled by whoever proposed it.
    with pytest.raises(DomainError, match="Say why"):
        job_changes.reject(proposed, by=staff.owner, reason=" ")
    rejected = run(job_changes.reject, proposed, by=staff.owner, reason="Hozircha kerak emas")
    assert rejected.status == "rejected"
    note = Notification.objects.get(recipient=staff.lead, kind="lifecycle.job_change_update")
    assert note.title == "Job change rejected: Ali Valiyev" and "Hozircha kerak emas" in note.body
    cancelled = run(job_changes.cancel, mine, by=staff.owner)
    assert cancelled.status == "cancelled"


def test_a_change_that_cant_apply_waits_for_try_again(
    shop, staff, senior, hr_lead, owner_api, run, freeze
):
    change = run(
        job_changes.propose,
        staff.ali,
        by=hr_lead,
        effective_on=NOVEMBER,
        reason="Provizor",
        position=senior,
        approve=True,
    )
    assert change.status == "approved"
    role = hr_lead.role
    role.permissions = [p for p in role.permissions if p != Perm.MEMBERS_MANAGE]
    role.save(update_fields=["permissions"])

    freeze(local(NOVEMBER, 6))
    assert run(job_changes.apply_due) == 0
    change.refresh_from_db()
    assert change.status == "approved" and "may no longer" in change.error
    note = Notification.objects.get(recipient=hr_lead, kind="lifecycle.job_change_update")
    assert note.title == "Job change not applied: Ali Valiyev"
    assert run(job_changes.apply_due) == 0  # waits for a person
    assert AuditLog.objects.filter(action="lifecycle.change_failed").count() == 1

    detail = owner_api(staff.owner).get(f"{base(shop)}{change.pk}/").json()
    assert detail["can"]["retry"] is True and detail["error"]
    response = run(owner_api(staff.owner).post, f"{base(shop)}{change.pk}/retry/")
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "applied" and response.json()["error"] == ""
    staff.ali.refresh_from_db()
    assert staff.ali.position_id == senior.pk


def test_scope_permissions_and_another_company(shop, staff, senior, owner_api, outsider, run):
    ali = run(
        job_changes.propose,
        staff.ali,
        by=staff.owner,
        effective_on=NOVEMBER,
        reason="Provizor",
        position=senior,
    )
    sara = run(
        job_changes.propose,
        staff.sara,
        by=staff.owner,
        effective_on=NOVEMBER,
        reason="Provizor",
        position=senior,
    )
    assert owner_api(staff.manager).get(base(shop)).status_code == 200  # hr.view reads
    payload = {"member_id": staff.vali.pk, "effective_on": "2026-11-01", "reason": "X"}
    assert owner_api(staff.manager).post(base(shop), payload, format="json").status_code == 403
    assert owner_api(staff.ali).get(base(shop)).status_code == 403
    assert owner_api(outsider).get(f"{base(outsider.company)}{ali.pk}/").status_code == 404
    rows = owner_api(staff.lead).get(base(shop)).json()["results"]
    assert [row["id"] for row in rows] == [ali.pk]  # Chilonzor only
    assert owner_api(staff.lead).get(f"{base(shop)}{sara.pk}/").status_code == 404
    assert owner_api(staff.owner).get(f"{base(shop)}counts/").json() == {
        "proposed": 2,
        "upcoming": 0,
        "applied": 0,
        "closed": 0,
    }
    current = owner_api(staff.owner).get(f"{base(shop)}current/", {"member": staff.ali.pk}).json()
    assert current["position"]["name"] == "Pharmacist" and current["may_change_pay"] is True
    assert [row["id"] for row in current["open_changes"]] == [ali.pk]
    assert (
        owner_api(staff.lead).get(f"{base(shop)}current/", {"member": staff.sara.pk}).status_code
        == 404
    )


def test_approving_from_the_telegram_button(shop, staff, senior, run):
    change = run(
        job_changes.propose,
        staff.ali,
        by=staff.accountant,
        effective_on=NOVEMBER,
        reason="Provizor",
        position=senior,
    )
    notice = Notification.objects.get(recipient=staff.owner, kind="lifecycle.job_change")
    assert run(inbox.run_action, notice.pk, "approve", by=staff.owner) == "Approved"
    change.refresh_from_db()
    assert change.status == "approved" and change.decided_by_id == staff.owner.pk


def test_the_history_in_the_dashboard_the_app_and_the_calendar(
    shop, paid, senior, owner_api, api_as, run, freeze
):
    staff = paid
    applied = run(
        job_changes.propose,
        staff.ali,
        by=staff.owner,
        effective_on=DAY,
        reason="Provizor",
        position=senior,
        approve=True,
    )
    coming = run(
        job_changes.propose,
        staff.ali,
        by=staff.owner,
        effective_on=DECEMBER,
        reason="Yangi maosh",
        pay_amount="6500000",
        approve=True,
    )
    career = owner_api(staff.owner).get(
        f"/api/v1/owner/companies/{shop.pk}/lifecycle/people/{staff.ali.pk}/career/"
    )
    assert career.status_code == 200, career.content
    body = career.json()
    assert [row["id"] for row in body["changes"]] == [coming.pk, applied.pk]
    assert body["changes"][0]["upcoming"] is True and body["leavings"] == []
    hidden = (
        owner_api(staff.manager)
        .get(f"/api/v1/owner/companies/{shop.pk}/lifecycle/people/{staff.ali.pk}/career/")
        .json()
    )
    assert hidden["changes"][0]["after"]["pay"] is None

    mine = api_as(staff.ali).get(f"/api/v1/companies/{shop.pk}/lifecycle/career/").json()
    assert mine["position"] == "Senior pharmacist"
    assert [row["status"] for row in mine["changes"]] == ["approved", "applied"]
    assert mine["changes"][0]["after"]["pay"]["amount"] == "6500000.00"  # their own pay

    items = providers.calendar_job_changes(shop, DAY, DECEMBER, staff.owner)
    assert [item.start for item in items] == [DAY, DECEMBER]
    assert items[0].title == "Job change: Ali Valiyev"


def test_without_hr_the_pages_answer_403(shop, staff, owner_api, api_as):
    shop.features = ["payroll"]
    shop.save(update_fields=["features"])
    assert owner_api(staff.owner).get(base(shop)).status_code == 403
    assert (
        api_as(staff.ali).get(f"/api/v1/companies/{shop.pk}/lifecycle/career/").status_code == 403
    )
