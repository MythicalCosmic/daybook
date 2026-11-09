"""Davomat's writes (docs/DAVOMAT.md §1): each one checks `by`, is audited and bumps its pulse
key after commit. `by=None` is the system (the first-run setup, a terminal, the bot).

First run
    setup_organization(name=, timezone=, language=, admin={username, password, first_name,
                       last_name}) -> Membership                       the owner's membership
Settings
    update_settings(company, *, by, product_name=, auto_create_employees=)
Users (the web app)
    create_user(company, *, by, username, password, role, ...) -> Membership
    update_user(membership, *, by, **changes) · set_active(membership, *, by, active)
Employees (the terminals)
    create_employee(company, *, by, first_name, ...) -> Membership
    update_employee(membership, *, by, **changes) · set_photo(membership, *, by, photo)
    leave(membership, *, by, left_on) · return_employee(membership, *, by, hire_date)
    add_face_number(membership, *, by, number) · remove_face_number(membership, *, by, number)
    auto_create_employee(company, device, employee_no, name)   faceid's unknown-number hook
Telegram
    connect_bot(company, *, by, token) · disconnect_bot(company, *, by)
    make_link(membership, *, by) -> NewLink
    claim_link(code, telegram_id, username, first_name) -> Membership     (the bot calls it)
    unlink_telegram(membership, *, by)
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import partial

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connection, transaction
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.attendance import clock
from apps.attendance import services as attendance
from apps.attendance.models import MemberSchedule, WorkSchedule
from apps.audit import services as audit
from apps.companies import services as companies
from apps.companies.models import Branch, BranchKind, Company, Feature
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.davomat import conf, queries
from apps.davomat import telegram as tg
from apps.davomat.audit_actions import DavomatAction
from apps.davomat.models import DavomatSettings, Employee, TelegramLink
from apps.davomat.passwords import FieldError, check_password_rules, clean_username
from apps.faceid import conf as faceid_conf
from apps.faceid import hikvision
from apps.faceid import services as faceid
from apps.faceid.models import FaceLink
from apps.hr import services as hr
from apps.members import scope
from apps.members import services as members
from apps.members.models import AccessRole, Department, Membership, Position
from apps.members.permissions import Perm
from apps.signin import services as signin

logger = logging.getLogger(__name__)

PULSE_EMPLOYEES = "davomat.employees"
PULSE_USERS = "davomat.users"
PULSE_TELEGRAM = "davomat.telegram"
PULSE_SETTINGS = "davomat.settings"
PEOPLE = "members.people"

LINK_LIFETIME = timedelta(hours=24)
LINK_PREFIX = "link_"
UNSET = members.UNSET
CURRENT = queries.CURRENT

# The roles of an organization (§1.3). Administrators hold every permission; what only owners
# may do (give or take the Owner role, change an owner) the anti-escalation rules keep.
MANAGER_PERMS = (
    Perm.ATTENDANCE_VIEW,
    Perm.ATTENDANCE_MANAGE,
    Perm.MEMBERS_VIEW,
    Perm.MEMBERS_MANAGE,
    Perm.MEMBERS_APPROVE,
    Perm.REPORTS_VIEW,
    Perm.DASHBOARD_ACCESS,
)
VIEWER_PERMS = (Perm.ATTENDANCE_VIEW, Perm.MEMBERS_VIEW, Perm.REPORTS_VIEW, Perm.DASHBOARD_ACCESS)
MODULES = (Feature.ATTENDANCE, Feature.FACE_ID)
SETUP_LOCK = 7_302_611  # pg_advisory_xact_lock key: one first-run setup at a time


class SetupDone(DomainError):
    """The organization exists already: the first-run setup happens once."""


def _require(by: Membership | None, perm: Perm) -> None:
    if by is not None and not by.has_perm(perm):
        raise PermissionDenied(_("You don't have permission to do this."))


def _audit(by: Membership | None, action: str, target, **details) -> None:
    audit.record(
        action,
        company_id=target.company_id if hasattr(target, "company_id") else target.pk,
        actor=by.user if by is not None else None,
        target=target,
        **details,
    )


def _bump(company_id: int, *keys: str) -> None:
    transaction.on_commit(partial(pulse.bump, company_id, *keys))


def _today(company: Company) -> date:
    return clock.today(company)


def _clean_name(value, field: str, *, required: bool) -> str:
    name = " ".join(str(value or "").split())[:100]
    if required and not name:
        raise FieldError(field, _("A first name is required."))
    return name


PHONE_DIGITS = re.compile(r"\d+")


def clean_phone(value) -> str:
    """A phone number as typed, tidied: "+998 90 123 45 67", "90 123-45-67" and "998901234567"
    are all +998901234567; anything else keeps its digits (and a leading +), at most 20."""
    text = str(value or "").strip()
    if not text:
        return ""
    digits = "".join(PHONE_DIGITS.findall(text))
    if len(digits) == 9:
        return f"+998{digits}"
    if len(digits) == 12 and digits.startswith("998"):
        return f"+{digits}"
    if len(digits) < 5 or len(digits) > 15:
        raise FieldError("phone", _("Check the phone number."))
    return f"+{digits}" if text.startswith("+") else digits


# First run ---------------------------------------------------------------------------------


def needs_setup() -> bool:
    return not Company.objects.exists()


@transaction.atomic
def setup_organization(*, name: str, timezone: str, language: str, admin: dict) -> Membership:
    """The organization, as the first-run setup (or `manage.py davomat_init`) makes it: its
    owner (a user with this password), one branch "Main" (renamed later), the four roles, the
    Face ID and attendance modules on, check-ins without a location. Once only."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [SETUP_LOCK])
    if not needs_setup():
        raise SetupDone(_("The organization is already set up. Sign in instead."))
    if not " ".join(str(name or "").split()):
        raise FieldError("organization", _("Give the organization a name."))
    user = User(
        username=clean_username(admin.get("username", ""), field="admin.username"),
        first_name=_clean_name(admin.get("first_name"), "admin.first_name", required=False),
        last_name=_clean_name(admin.get("last_name"), "admin.last_name", required=False),
        language=language,
    )
    check_password_rules(admin.get("password", ""), user, field="admin.password")
    user.set_password(admin["password"])
    user.save()
    company = companies.create_company(
        name=" ".join(name.split()), timezone=timezone, language=language, owner=user
    )
    owner = Membership.objects.select_related("company", "user", "role").get(
        company=company, user=user
    )
    if not owner.first_name:
        owner.first_name = user.username[:100]
        owner.save(update_fields=["first_name", "updated_at"])
    with translation.override(language):
        main = _("Main")
    branch = company.branches.order_by("order", "pk").first()
    branch.name, branch.kind = main, BranchKind.OFFICE
    branch.save(update_fields=["name", "kind", "updated_at"])
    _organization_roles(company)
    owner.refresh_from_db()
    companies.set_features(company, by=None, features=[str(module) for module in MODULES])
    company.refresh_from_db()
    attendance.update_settings(company, by=None, require_location=False)
    faceid_conf.get_settings(company)
    conf.get_settings(company)
    Company.objects.filter(pk=company.pk).update(
        setup_completed_at=timezone_now(), business_confirmed_at=timezone_now()
    )
    audit.record(
        DavomatAction.SETUP_DONE,
        company_id=company.pk,
        actor=user,
        target=company,
        organization=company.name,
        username=user.username,
    )
    return owner


def timezone_now() -> datetime:
    return timezone.now()


def _organization_roles(company: Company) -> dict[str, AccessRole]:
    """Owner (kept from the company's start), Administrator, Manager, Viewer and Employee (the
    default role, for people who only scan), named in the organization's language. The
    company's pharmacy roles go: nobody holds them yet."""
    with translation.override(company.default_language):
        names = {
            queries.OWNER: _("Owner"),
            queries.ADMIN: _("Administrator"),
            queries.MANAGER: _("Manager"),
            queries.VIEWER: _("Viewer"),
            queries.EMPLOYEE: _("Employee"),
        }
    roles = AccessRole.objects.for_company(company)
    owner = roles.filter(is_owner=True).order_by("pk").first()
    roles.exclude(pk=owner.pk).filter(members__isnull=True, positions__isnull=True).delete()
    owner.name = names[queries.OWNER]
    owner.save(update_fields=["name", "updated_at"])
    made = {queries.OWNER: owner}
    for kind, permissions, default in (
        (queries.ADMIN, [str(perm) for perm in Perm], False),
        (queries.MANAGER, [str(perm) for perm in MANAGER_PERMS], False),
        (queries.VIEWER, [str(perm) for perm in VIEWER_PERMS], False),
        (queries.EMPLOYEE, [], True),
    ):
        made[kind], _created = AccessRole.objects.update_or_create(
            company=company,
            name=names[kind],
            defaults={"permissions": permissions, "is_default": default, "is_owner": False},
        )
    return made


# Settings ----------------------------------------------------------------------------------

SETTINGS_FIELDS = ("product_name", "auto_create_employees")


def update_settings(company: Company, *, by: Membership | None, **changes) -> DavomatSettings:
    _require(by, Perm.COMPANY_SETTINGS)
    unknown = set(changes) - set(SETTINGS_FIELDS)
    if unknown:
        raise ValueError(f"Unknown Davomat settings: {sorted(unknown)}")
    if "product_name" in changes:
        changes["product_name"] = " ".join(str(changes["product_name"] or "").split())[:60]
    with transaction.atomic():
        row = DavomatSettings.objects.select_for_update().get(pk=conf.get_settings(company).pk)
        changed = {
            field: [getattr(row, field), value]
            for field, value in changes.items()
            if getattr(row, field) != value
        }
        if not changed:
            return row
        for field, value in changes.items():
            setattr(row, field, value)
        row.save()
        _audit(by, DavomatAction.SETTINGS_CHANGED, company, changes=changed)
    _bump(company.pk, PULSE_SETTINGS)
    return row


# Users -------------------------------------------------------------------------------------


def _web_role(company: Company, role: AccessRole | None, field: str = "role_id") -> AccessRole:
    if (
        role is None
        or role.company_id != company.pk
        or queries.role_kind(role) not in (queries.WEB_KINDS)
    ):
        raise FieldError(field, _("Pick one of the roles offered."))
    return role


def _branches(company: Company, by: Membership | None, branches, field="branch_ids") -> list:
    """The branches asked for, each the company's and open, and each one `by` sees."""
    found = list(dict.fromkeys(branches or ()))
    if any(branch.company_id != company.pk or not branch.is_active for branch in found):
        raise FieldError(field, _("Pick branches of this organization."))
    allowed = scope.branch_ids(by) if by is not None else None
    if allowed is not None and any(branch.pk not in allowed for branch in found):
        raise PermissionDenied(_("You can only give the branches you manage."))
    return found


def _default_branches(company: Company, by: Membership | None, field="branch_ids") -> list:
    """Where someone works when nobody said: the first open branch, for someone who sees every
    branch; a manager names one."""
    if by is not None and scope.branch_ids(by) is not None:
        raise FieldError(field, _("Pick the branch they work at."))
    first = company.branches.filter(is_active=True).order_by("order", "pk").first()
    return [first] if first is not None else []


def _ensure_may_touch(by: Membership | None, membership: Membership) -> None:
    """Only owners change an owner."""
    if by is None or members._is_owner_member(by):
        return
    if membership.role is not None and membership.role.is_owner:
        raise PermissionDenied(_("Only owners can change an owner."))


@transaction.atomic
def create_user(
    company: Company,
    *,
    by: Membership | None,
    username: str,
    password: str,
    role: AccessRole | None,
    first_name: str = "",
    last_name: str = "",
    branches=(),
    employee: Membership | None = None,
) -> Membership:
    """A new user of the web app; or, with `employee`, an employee given a username, a password
    and a role (they keep scanning as before)."""
    _require(by, Perm.ROLES_MANAGE)
    role = _web_role(company, role)
    if not members.may_assign_role(by, role):
        raise PermissionDenied(_("You can only give a role whose permissions you have yourself."))
    chosen = _branches(company, by, branches)
    kind = queries.role_kind(role)
    if not chosen and kind in (queries.MANAGER, queries.VIEWER):
        raise FieldError("branch_ids", _("Pick the branches this user sees."))
    now = timezone.now()
    if employee is not None:
        membership = members._lock(employee)
        if membership.company_id != company.pk or membership.status != Membership.Status.APPROVED:
            raise FieldError("employee_id", _("Pick a current employee."))
        if queries.is_user(membership):
            raise FieldError("employee_id", _("This employee is a user already."))
        user = membership.user
        user.username = clean_username(username, user=user)
        if first_name:
            membership.first_name = _clean_name(first_name, "first_name", required=True)
        if last_name:
            membership.last_name = _clean_name(last_name, "last_name", required=False)
        user.first_name, user.last_name = membership.first_name, membership.last_name
        check_password_rules(password, user)
        user.set_password(password)
        user.is_active = True
        user.save()
        membership.role = role
        membership.save()
        if chosen:
            membership.branches.set(chosen)
            if membership.home_branch_id not in {branch.pk for branch in chosen}:
                membership.home_branch = chosen[0]
                membership.save(update_fields=["home_branch", "updated_at"])
    else:
        user = User(
            username=clean_username(username),
            first_name=_clean_name(first_name, "first_name", required=True),
            last_name=_clean_name(last_name, "last_name", required=False),
            language=company.default_language,
        )
        check_password_rules(password, user)
        user.set_password(password)
        user.save()
        chosen = chosen or _first_branch(company)
        membership = Membership.objects.create(
            company=company,
            user=user,
            status=Membership.Status.APPROVED,
            role=role,
            first_name=user.first_name,
            last_name=user.last_name,
            decided_by=by.user if by is not None else None,
            decided_at=now,
            onboarded_at=now,
            home_branch=chosen[0] if chosen else None,
        )
        membership.branches.set(chosen)
    _audit(
        by,
        DavomatAction.USER_CREATED,
        membership,
        username=user.username,
        role=role.name,
        branches=sorted(branch.name for branch in chosen),
        from_employee=employee is not None,
    )
    _bump(company.pk, PULSE_USERS, PULSE_EMPLOYEES, PEOPLE)
    return membership


def _first_branch(company: Company) -> list[Branch]:
    first = company.branches.filter(is_active=True).order_by("order", "pk").first()
    return [first] if first is not None else []


@transaction.atomic
def update_user(
    membership: Membership,
    *,
    by: Membership,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    role: AccessRole | None = None,
    branches=None,
    is_active: bool | None = None,
    is_employee: bool | None = None,
) -> Membership:
    """Change a user's username, name, role, branches, whether they may sign in and whether
    they scan at the terminals too (an `Employee` row)."""
    _require(by, Perm.ROLES_MANAGE)
    membership = members._lock(membership)
    _ensure_may_touch(by, membership)
    company = membership.company
    user = membership.user
    changes: dict[str, list] = {}
    if username is not None:
        name = clean_username(username, user=user)
        if name != user.username:
            changes["username"] = [user.username, name]
            user.username = name
            user.save(update_fields=["username"])
    if role is not None and role.pk != membership.role_id:
        role = _web_role(company, role)
        changes["role"] = [membership.role.name if membership.role else None, role.name]
        membership = members.change_role(membership, by=by, role=role)
    if first_name is not None or last_name is not None or branches is not None:
        chosen = _branches(company, by, branches) if branches is not None else None
        if (
            chosen is not None
            and not chosen
            and queries.role_kind(membership.role)
            in (
                queries.MANAGER,
                queries.VIEWER,
            )
        ):
            raise FieldError("branch_ids", _("Pick the branches this user sees."))
        membership = members.update_member(
            membership,
            by=by,
            first_name=_clean_name(first_name, "first_name", required=True)
            if first_name is not None
            else None,
            last_name=_clean_name(last_name, "last_name", required=False)
            if last_name is not None
            else None,
            branches=chosen,
        )
        _sync_user_name(membership)
    if is_employee is not None and is_employee != queries.is_employee(membership):
        changes["is_employee"] = [not is_employee, is_employee]
        if is_employee:
            Employee.objects.create(
                company=company, membership=membership, created_by=by.user if by else None
            )
        else:
            Employee.objects.filter(membership=membership).delete()
    if changes:
        _audit(by, DavomatAction.USER_CHANGED, membership, changes=changes)
    if is_active is not None and is_active != _is_active(membership):
        membership = set_active(membership, by=by, active=is_active)
    _bump(company.pk, PULSE_USERS, PULSE_EMPLOYEES)
    return membership


def _is_active(membership: Membership) -> bool:
    return membership.user.is_active and membership.status == Membership.Status.APPROVED


def _sync_user_name(membership: Membership) -> None:
    user = membership.user
    if (user.first_name, user.last_name) != (membership.first_name, membership.last_name):
        user.first_name, user.last_name = membership.first_name, membership.last_name
        User.objects.filter(pk=user.pk).update(
            first_name=membership.first_name, last_name=membership.last_name
        )


@transaction.atomic
def set_active(membership: Membership, *, by: Membership | None, active: bool) -> Membership:
    """Switch a user's sign-in off (every session of theirs ends at once) or back on. An
    employee who is switched off keeps scanning; the organization keeps an owner who can."""
    _require(by, Perm.ROLES_MANAGE)
    membership = members._lock(membership)
    _ensure_may_touch(by, membership)
    user = User.objects.select_for_update().get(pk=membership.user_id)
    if active == user.is_active:
        return membership
    if not active:
        if by is not None and by.user_id == user.pk:
            raise DomainError(_("You can't switch yourself off."))
        if membership.role is not None and membership.role.is_owner:
            others = (
                Membership.objects.filter(
                    company_id=membership.company_id,
                    status=Membership.Status.APPROVED,
                    role__is_owner=True,
                    user__is_active=True,
                )
                .exclude(pk=membership.pk)
                .exists()
            )
            if not others:
                raise DomainError(_("This is the only owner who can sign in."))
    user.is_active = active
    user.save(update_fields=["is_active"])
    membership.user = user
    if not active:
        signin.revoke_all(user)
    _audit(
        by,
        DavomatAction.USER_ACTIVATED if active else DavomatAction.USER_DEACTIVATED,
        membership,
    )
    _bump(membership.company_id, PULSE_USERS)
    return membership


# Employees ---------------------------------------------------------------------------------


def _username_for_employee() -> str:
    """Employees never sign in, but every account has a username: "e-" and random hex."""
    while True:
        name = f"e-{secrets.token_hex(5)}"
        if not User.objects.filter(username__iexact=name).exists():
            return name


def _position(company: Company, position: Position | None) -> Position | None:
    if position is not None and (position.company_id != company.pk or not position.is_active):
        raise FieldError("position_id", _("Pick a position of this organization."))
    return position


def _department(company: Company, department: Department | None) -> Department | None:
    if department is not None and department.company_id != company.pk:
        raise FieldError("department_id", _("Pick a department of this organization."))
    return department


def _schedule(company: Company, schedule: WorkSchedule | None) -> WorkSchedule | None:
    if schedule is not None and (schedule.company_id != company.pk or not schedule.is_active):
        raise FieldError("schedule_id", _("Pick a schedule of this organization."))
    return schedule


def _hire_date(company: Company, value: date | None) -> date | None:
    if value is not None and value > _today(company):
        raise FieldError("hire_date", _("The hire date can't be in the future."))
    return value


def _numbers(values) -> list[str]:
    """Terminal numbers as typed ("00000002"), one per number ("2" is the same one)."""
    found: dict[str, str] = {}
    for value in values or ():
        number = str(value or "").strip()[:32]
        key = hikvision.number_key(number)
        if not key:
            raise FieldError("face_numbers", _("Give the Employee No from the terminal."))
        found.setdefault(key, number)
    return list(found.values())


@transaction.atomic
def create_employee(
    company: Company,
    *,
    by: Membership | None,
    first_name: str,
    last_name: str = "",
    phone: str = "",
    position: Position | None = None,
    department: Department | None = None,
    branches=(),
    hire_date: date | None = None,
    schedule: WorkSchedule | None = None,
    face_numbers=(),
    source: str = Employee.Source.MANUAL,
) -> Membership:
    """Someone who scans at the terminals: an approved membership with the Employee role, an
    account that can't sign in, their numbers linked on the terminals."""
    _require(by, Perm.MEMBERS_MANAGE)
    first = _clean_name(first_name, "first_name", required=True)
    last = _clean_name(last_name, "last_name", required=False)
    chosen = _branches(company, by, branches) or _default_branches(company, by)
    numbers = _numbers(face_numbers)
    role = queries.employee_role(company)
    if role is None:
        raise DomainError(_("The organization has no role for employees."))
    now = timezone.now()
    user = User(
        username=_username_for_employee(),
        first_name=first,
        last_name=last,
        phone=clean_phone(phone),
        language=company.default_language,
    )
    user.set_unusable_password()
    user.save()
    membership = Membership.objects.create(
        company=company,
        user=user,
        status=Membership.Status.APPROVED,
        role=role,
        first_name=first,
        last_name=last,
        position=_position(company, position),
        department=_department(company, department),
        decided_by=by.user if by is not None else None,
        decided_at=now,
        onboarded_at=now,
        home_branch=chosen[0] if chosen else None,
    )
    membership.branches.set(chosen)
    Employee.objects.create(
        company=company,
        membership=membership,
        source=source,
        created_by=by.user if by is not None else None,
    )
    hired = _hire_date(company, hire_date)
    if hired is not None:
        hr.update_profile(membership, by=None, hire_date=hired)
    else:
        hr.ensure_profile(membership)
    if schedule is not None:
        attendance.assign_schedule(company, _schedule(company, schedule), [membership.pk], by=by)
    for number in numbers:
        faceid.link_number(company, by=by, employee_no=number, membership=membership)
    _audit(
        by,
        DavomatAction.EMPLOYEE_CREATED,
        membership,
        name=membership.full_name,
        branches=sorted(branch.name for branch in chosen),
        numbers=numbers,
        source=source,
    )
    _bump(company.pk, PULSE_EMPLOYEES, PEOPLE)
    return membership


@transaction.atomic
def update_employee(
    membership: Membership,
    *,
    by: Membership,
    first_name: str | None = None,
    last_name: str | None = None,
    phone: str | None = None,
    position=UNSET,
    department=UNSET,
    branches=None,
    hire_date=UNSET,
    schedule=UNSET,
    face_numbers=None,
) -> Membership:
    """Change an employee: what members' `update_member` keeps (name, position, department,
    branches; audited there), and the phone, hire date, schedule and terminal numbers."""
    _require(by, Perm.MEMBERS_MANAGE)
    company = membership.company
    if membership.status not in CURRENT:
        raise DomainError(_("Take them back first to change them."))
    _ensure_may_touch(by, membership)
    changes: dict[str, list] = {}
    member_fields = {}
    if first_name is not None:
        member_fields["first_name"] = _clean_name(first_name, "first_name", required=True)
    if last_name is not None:
        member_fields["last_name"] = _clean_name(last_name, "last_name", required=False)
    if position is not UNSET:
        member_fields["position"] = _position(company, position)
    if department is not UNSET:
        member_fields["department"] = _department(company, department)
    if branches is not None:
        chosen = _branches(company, by, branches)
        if not chosen:
            raise FieldError("branch_ids", _("Pick the branch they work at."))
        member_fields["branches"] = chosen
    if member_fields:
        membership = members.update_member(membership, by=by, **member_fields)
        _sync_user_name(membership)
    user = membership.user
    if phone is not None:
        tidy = clean_phone(phone)
        if tidy != user.phone:
            changes["phone"] = [user.phone, tidy]
            user.phone = tidy
            User.objects.filter(pk=user.pk).update(phone=tidy)
    if hire_date is not UNSET and hire_date is not None:
        hired = _hire_date(company, hire_date)
        before = hr.ensure_profile(membership).hire_date
        if before != hired:
            changes["hire_date"] = [_iso(before), _iso(hired)]
            hr.update_profile(membership, by=None, hire_date=hired)
    if schedule is not UNSET:
        wanted = _schedule(company, schedule)
        current = MemberSchedule.objects.filter(membership=membership).first()
        if (current.schedule_id if current else None) != (wanted.pk if wanted else None):
            changes["schedule"] = [
                current.schedule.name if current and current.schedule else None,
                wanted.name if wanted else None,
            ]
            attendance.assign_schedule(company, wanted, [membership.pk], by=by)
    if face_numbers is not None:
        wanted_numbers = _numbers(face_numbers)
        links = {link.number_key: link for link in FaceLink.objects.filter(membership=membership)}
        keys = {hikvision.number_key(number): number for number in wanted_numbers}
        for key, link in links.items():
            if key not in keys:
                faceid.unlink(link, by=by)
        for key, number in keys.items():
            if key not in links:
                faceid.link_number(company, by=by, employee_no=number, membership=membership)
        if set(keys) != set(links):
            changes["face_numbers"] = [
                sorted(link.employee_no for link in links.values()),
                sorted(wanted_numbers),
            ]
    if changes:
        _audit(by, DavomatAction.EMPLOYEE_CHANGED, membership, changes=changes)
    _bump(company.pk, PULSE_EMPLOYEES, PEOPLE)
    return membership


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


@transaction.atomic
def set_photo(membership: Membership, *, by: Membership, photo) -> Membership:
    """A new photo (already through `apps.core.uploads.sanitize_image`), or None to remove it.
    It is the person's avatar everywhere: the attendance board, the Face ID feed, the lists."""
    _require(by, Perm.MEMBERS_MANAGE)
    user = User.objects.select_for_update().get(pk=membership.user_id)
    old = user.photo.name if user.photo else ""
    if photo is None:
        user.photo = ""
    else:
        user.photo.save(photo.name, photo, save=False)
    user.photo_checked_at = timezone.now()
    user.save(update_fields=["photo", "photo_checked_at"])
    membership.user = user
    _audit(by, DavomatAction.EMPLOYEE_PHOTO, membership, removed=photo is None)
    if old:
        storage = user.photo.storage
        transaction.on_commit(partial(storage.delete, old))
    _bump(membership.company_id, PULSE_EMPLOYEES, PEOPLE)
    return membership


def leave(membership: Membership, *, by: Membership, left_on: date | None = None) -> Membership:
    """The employee left on `left_on` (today when not given; never in the future): members'
    offboarding ends their access, closes an open check-in, cancels their future shifts and
    puts the last day on their profile."""
    _require(by, Perm.MEMBERS_MANAGE)
    _ensure_may_touch(by, membership)
    with transaction.atomic():
        membership = members.offboard(membership, by=by.user, terminated_on=left_on)
        _bump(membership.company_id, PULSE_EMPLOYEES, PULSE_USERS)
    return membership


@transaction.atomic
def return_employee(
    membership: Membership, *, by: Membership, hire_date: date | None = None
) -> Membership:
    """Someone who left comes back: a new stint from `hire_date` (today when not given), on the
    schedule they had."""
    _require(by, Perm.MEMBERS_MANAGE)
    membership = members._lock(membership)
    _ensure_may_touch(by, membership)
    if membership.status != Membership.Status.LEFT:
        raise DomainError(_("Only someone who has left can come back."))
    company = membership.company
    hired = _hire_date(company, hire_date) or _today(company)
    membership.status = Membership.Status.APPROVED
    membership.decided_by = by.user
    membership.decided_at = timezone.now()
    membership.save(update_fields=["status", "decided_by", "decided_at", "updated_at"])
    hr.update_profile(
        membership,
        by=None,
        hire_date=hired,
        terminated_on=None,
        termination_reason="",
        termination_note="",
    )
    if MemberSchedule.objects.filter(membership=membership, schedule__isnull=False).exists():
        attendance.regenerate(company, [membership.pk])
    _audit(by, DavomatAction.EMPLOYEE_RETURNED, membership, hire_date=hired.isoformat())
    _bump(company.pk, PULSE_EMPLOYEES, PULSE_USERS, PEOPLE)
    return membership


@transaction.atomic
def add_face_number(membership: Membership, *, by: Membership, number) -> FaceLink:
    _require(by, Perm.MEMBERS_MANAGE)
    if membership.status not in CURRENT:
        raise DomainError(_("Take them back first to change them."))
    (clean,) = _numbers([number])
    link = faceid.link_number(membership.company, by=by, employee_no=clean, membership=membership)
    _bump(membership.company_id, PULSE_EMPLOYEES)
    return link


@transaction.atomic
def remove_face_number(membership: Membership, *, by: Membership, number) -> None:
    _require(by, Perm.MEMBERS_MANAGE)
    key = hikvision.number_key(str(number or ""))
    link = FaceLink.objects.filter(membership=membership, number_key=key).first()
    if link is None:
        raise DomainError(_("This number isn't theirs."))
    faceid.unlink(link, by=by)
    _bump(membership.company_id, PULSE_EMPLOYEES)


def split_name(name: str) -> tuple[str, str]:
    """A terminal's name as first and last name: "Gulirano" is a first name; "Ali Valiyev"
    is Ali, Valiyev. The administrator fixes the rest."""
    parts = " ".join(str(name or "").split()).split(" ", 1)
    first = parts[0][:100] if parts and parts[0] else ""
    last = parts[1][:100] if len(parts) > 1 else ""
    return first, last


def auto_create_employee(company: Company, device, employee_no: str, name: str):
    """Face ID's hook for a number nobody has (`faceid.services.register_unknown_number`): in
    the Davomat edition, with `auto_create_employees` on, the number becomes a new employee at
    the terminal's branch, named as on the terminal, and the scan counts for them. Returns the
    membership (or None: Daybook, switched off, no number)."""
    if not conf.is_on():
        return None
    number = str(employee_no or "").strip()[:32]
    key = hikvision.number_key(number)
    if not key or not conf.get_settings(company).auto_create_employees:
        return None
    first, last = split_name(name)
    if not first:
        with translation.override(company.default_language):
            first = _("Employee %(number)s") % {"number": number}
    try:
        with transaction.atomic():
            membership = create_employee(
                company,
                by=None,
                first_name=first,
                last_name=last,
                branches=[device.branch] if device.branch.is_active else [],
                face_numbers=[number],
                source=Employee.Source.TERMINAL,
            )
            audit.record(
                DavomatAction.EMPLOYEE_AUTO_CREATED,
                company_id=company.pk,
                actor=None,
                target=membership,
                number=number,
                name_on_device=name or "",
                terminal=device.name,
            )
    except IntegrityError:
        # The same number, made a moment ago by another scan: theirs.
        link = FaceLink.objects.filter(company=company, number_key=key).first()
        membership = link.membership if link is not None else None
        if membership is None:
            return None
    except DomainError as exc:
        logger.warning("Face ID number %s not made an employee: %s", number, exc)
        return None
    return Membership.objects.select_related("company", "user", "role").get(pk=membership.pk)


# Telegram ----------------------------------------------------------------------------------


def _write_token_version(version: int) -> None:
    """Tell the bot process about a new token (it restarts with it); best effort: the bot
    also reads the version from the database."""
    from apps.core import redis as core_redis

    try:
        core_redis.get_redis().set(core_redis.key(*queries.TOKEN_VERSION_KEY), version)
    except Exception as exc:  # Redis down: the bot polls the database too
        logger.warning("Couldn't write the bot token version to Redis: %s", exc)


def connect_bot(company: Company, *, by: Membership | None, token: str) -> DavomatSettings:
    """Check the BotFather token with Telegram (`getMe`) and keep it (encrypted) with the bot's
    name; the bot restarts with it. Raises FieldError (a token Telegram refuses) or DomainError
    (Telegram can't be reached)."""
    _require(by, Perm.COMPANY_SETTINGS)
    token = "".join(str(token or "").split())
    if not token:
        raise FieldError("token", _("Paste the token BotFather gave you."))
    try:
        info = tg.check_token(token)
    except tg.TokenRefused as exc:
        raise FieldError(
            "token", _("Telegram doesn't accept this token. Copy it from BotFather again.")
        ) from exc
    except tg.TelegramUnreachable as exc:
        raise DomainError(_("Telegram can't be reached right now. Try again in a minute.")) from exc
    with transaction.atomic():
        row = DavomatSettings.objects.select_for_update().get(pk=conf.get_settings(company).pk)
        changed = row.bot_token != token
        row.bot_token = token
        row.bot_id, row.bot_username, row.bot_name = info.id, info.username, info.name[:128]
        row.bot_status = DavomatSettings.BotStatus.OK
        row.bot_checked_at = timezone.now()
        if changed:
            row.token_version += 1
        row.save()
        _audit(by, DavomatAction.TELEGRAM_CONNECTED, company, bot=f"@{info.username}")
        version = row.token_version
    transaction.on_commit(partial(_write_token_version, version))
    _bump(company.pk, PULSE_TELEGRAM)
    return row


def disconnect_bot(company: Company, *, by: Membership | None) -> DavomatSettings:
    _require(by, Perm.COMPANY_SETTINGS)
    with transaction.atomic():
        row = DavomatSettings.objects.select_for_update().get(pk=conf.get_settings(company).pk)
        if not row.bot_token and row.bot_status == DavomatSettings.BotStatus.NOT_SET:
            return row
        was = row.bot_username
        row.bot_token, row.bot_id, row.bot_username, row.bot_name = "", None, "", ""
        row.bot_status = DavomatSettings.BotStatus.NOT_SET
        row.bot_checked_at = timezone.now()
        row.token_version += 1
        row.save()
        _audit(by, DavomatAction.TELEGRAM_REMOVED, company, bot=f"@{was}" if was else "")
        version = row.token_version
    transaction.on_commit(partial(_write_token_version, version))
    _bump(company.pk, PULSE_TELEGRAM)
    return row


def mark_bot_refused(company: Company) -> None:
    """Telegram stopped accepting the token (revoked in BotFather): the settings say so."""
    DavomatSettings.objects.filter(company=company).update(
        bot_status=DavomatSettings.BotStatus.INVALID, bot_checked_at=timezone.now()
    )
    _bump(company.pk, PULSE_TELEGRAM)


@dataclass(frozen=True)
class NewLink:
    link: TelegramLink
    code: str
    url: str


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


@transaction.atomic
def make_link(membership: Membership, *, by: Membership | None) -> NewLink:
    """A one-time link (24 hours) that links whoever opens it in the bot to `membership`; it
    replaces any earlier link of theirs that is still unused."""
    company = membership.company
    row = conf.get_settings(company)
    if not row.bot_username:
        raise DomainError(_("Connect the Telegram bot first (Settings, Telegram)."))
    if membership.status not in CURRENT:
        raise DomainError(_("Only current people can link their Telegram."))
    now = timezone.now()
    TelegramLink.objects.filter(
        membership=membership, used_at__isnull=True, expires_at__gt=now
    ).update(expires_at=now)
    code = secrets.token_urlsafe(12)
    link = TelegramLink.objects.create(
        company=company,
        membership=membership,
        code_hash=_hash(code),
        expires_at=now + LINK_LIFETIME,
        created_by=by.user if by is not None else None,
    )
    _audit(by, DavomatAction.TELEGRAM_LINK_MADE, membership)
    return NewLink(link, code, f"https://t.me/{row.bot_username}?start={LINK_PREFIX}{code}")


class LinkRefused(DomainError):
    """A link code that links nobody. `code`: not_found, used, expired, inactive."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def claim_link(code: str, telegram_id: int, username: str | None, first_name: str | None):
    """The bot's `/start link_<code>`: the Telegram account `telegram_id` becomes the linked
    one of the link's person (taken from any other account it was linked to), once. Opening the
    same link again from the same account is fine. Raises LinkRefused; returns the membership.

    `first_name` is Telegram's: the names the administrator typed are kept."""
    code = str(code or "").strip().removeprefix(LINK_PREFIX)
    now = timezone.now()
    with transaction.atomic():
        link = (
            TelegramLink.objects.select_for_update()
            .select_related("membership__user", "membership__company")
            .filter(code_hash=_hash(code))
            .first()
            if code
            else None
        )
        if link is None:
            raise LinkRefused("not_found", _("This link doesn't work. Ask for a new one."))
        membership = link.membership
        if link.used_at is not None:
            if link.telegram_id == telegram_id and membership.user.telegram_id == telegram_id:
                return _fresh(membership)
            raise LinkRefused("used", _("This link was used already. Ask for a new one."))
        if link.expires_at <= now:
            raise LinkRefused("expired", _("This link has expired. Ask for a new one."))
        if membership.status not in CURRENT or not membership.company.is_active:
            raise LinkRefused("inactive", _("This account is no longer active."))
        _free_telegram(telegram_id, keep=membership.user_id, company_id=membership.company_id)
        user = User.objects.select_for_update().get(pk=membership.user_id)
        user.telegram_id = telegram_id
        user.telegram_username = (username or "")[:64]
        user.owner_bot_started_at = user.owner_bot_started_at or now
        user.owner_bot_blocked_at = None
        user.save(
            update_fields=[
                "telegram_id",
                "telegram_username",
                "owner_bot_started_at",
                "owner_bot_blocked_at",
            ]
        )
        link.used_at, link.telegram_id = now, telegram_id
        link.save(update_fields=["used_at", "telegram_id", "updated_at"])
        audit.record(
            DavomatAction.TELEGRAM_LINKED,
            company_id=membership.company_id,
            actor=user,
            target=membership,
            telegram=f"@{username}" if username else str(telegram_id),
        )
        _bump(membership.company_id, PULSE_EMPLOYEES, PULSE_USERS)
    return _fresh(membership)


def _fresh(membership: Membership) -> Membership:
    return Membership.objects.select_related("company", "user", "role", "position").get(
        pk=membership.pk
    )


def _free_telegram(telegram_id: int, *, keep: int, company_id: int) -> None:
    """The account `telegram_id` was linked to someone else: no more."""
    other = User.objects.select_for_update().filter(telegram_id=telegram_id).exclude(pk=keep)
    for user in other:
        user.telegram_id, user.telegram_username = None, ""
        user.save(update_fields=["telegram_id", "telegram_username"])
        for membership in Membership.objects.filter(user=user, company_id=company_id):
            audit.record(
                DavomatAction.TELEGRAM_UNLINKED,
                company_id=company_id,
                actor=None,
                target=membership,
                moved=True,
            )


@transaction.atomic
def unlink_telegram(membership: Membership, *, by: Membership | None) -> Membership:
    """Their Telegram is no longer linked (and their unused links stop working)."""
    user = User.objects.select_for_update().get(pk=membership.user_id)
    now = timezone.now()
    TelegramLink.objects.filter(
        membership=membership, used_at__isnull=True, expires_at__gt=now
    ).update(expires_at=now)
    if user.telegram_id is None:
        return membership
    user.telegram_id, user.telegram_username = None, ""
    user.save(update_fields=["telegram_id", "telegram_username"])
    membership.user = user
    _audit(by, DavomatAction.TELEGRAM_UNLINKED, membership)
    _bump(membership.company_id, PULSE_EMPLOYEES, PULSE_USERS)
    return membership
