import pytest

from apps.members.models import AccessRole, Membership
from apps.members.permissions import DEFAULT_ROLES, Perm

pytestmark = pytest.mark.django_db


def role(company, name) -> AccessRole:
    return AccessRole.objects.get(company=company, name=name)


def test_owner_role_grants_every_permission(company):
    owner = role(company, "Owner")

    assert all(owner.grants(perm) for perm in Perm)


def test_employee_role_grants_only_expense_claims(company):
    employee = role(company, "Employee")

    assert [perm for perm in Perm if employee.grants(perm)] == [Perm.FINANCE_CLAIM]


def test_manager_role_grants_only_its_permissions(company):
    manager = role(company, "Manager")

    assert manager.grants(Perm.MEMBERS_APPROVE)
    assert not manager.grants(Perm.ROLES_MANAGE)
    assert not manager.grants(Perm.MEMBERS_MANAGE)


@pytest.mark.parametrize(
    "status",
    [
        Membership.Status.PENDING,
        Membership.Status.REJECTED,
        Membership.Status.BLOCKED,
        Membership.Status.LEFT,
        Membership.Status.SUSPENDED,
    ],
)
def test_only_approved_members_have_permissions(company, member, status):
    owner = member(company, "Owner", status=status)

    assert not owner.has_perm(Perm.MEMBERS_VIEW)


def test_member_without_role_has_no_permissions(company, member):
    membership = member(company)
    membership.role = None

    assert not membership.has_perm(Perm.MEMBERS_VIEW)


# The owner console permissions (docs/PLAN-OWNER.md §5 and §13).
OWNER_CONSOLE = {
    "dashboard.access": {"Manager", "Accountant"},
    "company.settings": set(),
    "audit.view": {"Accountant"},
    "data.export": {"Accountant"},
    "branches.all": {"Manager", "Accountant"},
    "sales.view": {"Manager", "Accountant"},
    "sales.operate": {"Cashier"},
    "sales.manage": {"Manager"},
    "sales.invoices": {"Accountant"},
    "stock.manage": {"Manager"},
    "finance.view": {"Accountant"},
    "finance.record": {"Accountant"},
    "finance.manage": {"Accountant"},
    "finance.approve": {"Accountant"},
    "finance.claim": {"Manager", "Accountant", "Cashier", "Employee"},
    "hr.view": {"Manager", "Accountant"},
    "hr.manage": {"Accountant"},
    "hr.sensitive": set(),
    "hr.hiring": {"Manager"},
    "attendance.view": {"Manager", "Accountant"},
    "attendance.manage": {"Manager"},
    "time_off.manage": {"Accountant"},
    "payroll.view": {"Accountant"},
    "payroll.propose": {"Manager", "Accountant"},
    "payroll.manage": {"Accountant"},
    "payroll.finalize": set(),
    "payroll.pay": {"Accountant"},
    "ai.use": set(),
    "ai.configure": set(),
}
ADDITIONS = {
    "projects.view_all": {"Manager"},
    "projects.manage": {"Manager"},
    "projects.time_view": {"Manager"},
    "hr.discipline": {"Manager"},
    "hr.suspend": set(),
    "hr.terminate": set(),
    "assets.manage": set(),
    "reviews.manage": {"Manager"},
    "knowledge.manage": set(),
    "agenda.manage": set(),
    "crm.view": set(),
    "crm.manage": set(),
}


def test_the_registry_has_every_new_permission():
    assert len(OWNER_CONSOLE) == 29
    assert set(OWNER_CONSOLE) | set(ADDITIONS) <= set(Perm.values)
    assert len(Perm.values) == 14 + 29 + 12


@pytest.mark.parametrize("code", [*OWNER_CONSOLE, *ADDITIONS])
def test_default_roles_hold_exactly_the_planned_new_permissions(company, code):
    holders = {r.name for r in AccessRole.objects.filter(company=company) if code in r.permissions}

    assert holders == {**OWNER_CONSOLE, **ADDITIONS}[code]
    assert role(company, "Owner").grants(Perm(code))


def test_manager_keeps_its_original_permissions(company):
    manager = role(company, "Manager")

    for perm in (
        Perm.MEMBERS_VIEW,
        Perm.MEMBERS_APPROVE,
        Perm.TASKS_VIEW_ALL,
        Perm.TASKS_ASSIGN,
        Perm.TASKS_TEMPLATES,
        Perm.TASKS_CONFIRM,
        Perm.GROUPS_MANAGE,
        Perm.REPORTS_VIEW,
        Perm.TIME_OFF_APPROVE,
        Perm.ANNOUNCE,
    ):
        assert manager.grants(perm)


def test_accountant_also_reads_members_and_reports(company):
    accountant = role(company, "Accountant")

    assert accountant.grants(Perm.MEMBERS_VIEW)
    assert accountant.grants(Perm.REPORTS_VIEW)
    assert not accountant.grants(Perm.MEMBERS_APPROVE)


def test_default_roles_are_well_formed():
    names = [entry["name"] for entry in DEFAULT_ROLES]
    assert names == ["Owner", "Manager", "Accountant", "Cashier", "Employee"]
    assert [entry["name"] for entry in DEFAULT_ROLES if entry.get("is_default")] == ["Employee"]
    for entry in DEFAULT_ROLES:
        permissions = entry.get("permissions", [])
        assert len(permissions) == len(set(permissions)), entry["name"]
        assert all(isinstance(perm, Perm) for perm in permissions)


def test_changing_a_role_is_not_part_of_managing_members():
    assert Perm.MEMBERS_MANAGE.label == "Edit, block and offboard members"
