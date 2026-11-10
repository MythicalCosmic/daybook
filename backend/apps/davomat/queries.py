"""Read functions of Davomat, for its owner API, the bot (D4) and the reports.

    role_kind(role)                         owner · admin · manager · viewer · employee
    users(company)                          memberships whose role opens the web app
    employees(company, *, branch_ids)       memberships with an `Employee` row, in scope
    membership_for_telegram(telegram_id)    who a linked Telegram account is (the bot)
    is_employee(membership)
    today_states(company, members, now)     {membership id: {state, since} | None}
    bot_token() · token_version()           the organization's bot, for the bot process

A function returning branch-bound data takes the required keyword `branch_ids`
(`apps.members.scope.branch_ids(member)`): managers see only their branches' people.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.attendance import clock
from apps.attendance import queries as attendance
from apps.attendance.models import AttendanceRecord, WorkShift
from apps.companies.models import Company
from apps.davomat import conf
from apps.davomat.models import DavomatSettings, Employee
from apps.members import scope
from apps.members.models import AccessRole, Membership
from apps.members.permissions import Perm

# Who is who (docs/DAVOMAT.md §1.3): the kinds of role a user can hold, strongest first.
OWNER, ADMIN, MANAGER, VIEWER, EMPLOYEE = "owner", "admin", "manager", "viewer", "employee"
WEB_KINDS = (OWNER, ADMIN, MANAGER, VIEWER)
# Today's state of an employee (§1.4).
IN, OUT, NOT_IN, OFF, LEAVE = "in", "out", "not_in", "off", "leave"
TODAY_STATES = (IN, OUT, NOT_IN, OFF, LEAVE)
CURRENT = (Membership.Status.APPROVED, Membership.Status.SUSPENDED)
EMPLOYEE_STATUSES = (*CURRENT, Membership.Status.LEFT)
TOKEN_VERSION_KEY = ("davomat", "bot_token_version")


# Roles -----------------------------------------------------------------------------------


def role_kind(role: AccessRole | None) -> str:
    """What a role amounts to in Davomat, read from what it grants (its name may be anything):
    the Owner role; roles.manage (administrators); attendance.manage or members.manage
    (managers); the web app alone (viewers); otherwise an employee's role (no web app)."""
    if role is None:
        return EMPLOYEE
    if role.is_owner:
        return OWNER
    granted = set(role.permissions)
    if Perm.DASHBOARD_ACCESS not in granted:
        return EMPLOYEE
    if Perm.ROLES_MANAGE in granted:
        return ADMIN
    if Perm.ATTENDANCE_MANAGE in granted or Perm.MEMBERS_MANAGE in granted:
        return MANAGER
    return VIEWER


def web_role_filter(prefix: str = "role") -> Q:
    """Roles that open the web app: the Owner role or `dashboard.access` (on the role itself
    with `prefix=""`, on a membership's role by default)."""
    path = f"{prefix}__" if prefix else ""
    return Q(**{f"{path}is_owner": True}) | Q(
        **{f"{path}permissions__contains": [Perm.DASHBOARD_ACCESS]}
    )


def web_roles(company: Company) -> list[AccessRole]:
    """The company's roles a user can be given, strongest first, then by name."""
    order = {kind: index for index, kind in enumerate(WEB_KINDS)}
    roles = [
        role
        for role in AccessRole.objects.for_company(company).filter(web_role_filter(""))
        if role_kind(role) in order
    ]
    return sorted(roles, key=lambda role: (order[role_kind(role)], role.name.casefold()))


def employee_role(company: Company) -> AccessRole | None:
    """The role employees get: the company's default role when it opens no web app, else the
    first role that opens nothing."""
    roles = list(AccessRole.objects.for_company(company).order_by("-is_default", "pk"))
    return next((role for role in roles if role_kind(role) == EMPLOYEE), None)


# People ------------------------------------------------------------------------------------


def users(company: Company) -> QuerySet[Membership]:
    """Everyone whose role opens the web app (switched off or gone included), by name."""
    return (
        Membership.objects.for_company(company)
        .filter(web_role_filter())
        .exclude(status__in=(Membership.Status.PENDING, Membership.Status.REJECTED))
        .select_related("user", "role", "company")
        .prefetch_related("branches")
        .order_by("first_name", "last_name", "pk")
    )


def employees(company: Company, *, branch_ids: list[int] | None) -> QuerySet[Membership]:
    """Employees (current and gone) whose branches meet `branch_ids`."""
    people = Membership.objects.for_company(company).filter(
        davomat_employee__isnull=False, status__in=EMPLOYEE_STATUSES
    )
    return scope.restrict(people, branch_ids, field="branches")


def membership_for_telegram(telegram_id: int) -> Membership | None:
    """The organization's current person whose linked Telegram this is (the bot's `/today` and
    `/me` ask), or None."""
    company = conf.organization()
    if company is None or telegram_id is None:
        return None
    return (
        Membership.objects.filter(
            company=company, user__telegram_id=telegram_id, status__in=CURRENT
        )
        .select_related("company", "user", "role", "position", "home_branch")
        .first()
    )


def is_employee(membership: Membership) -> bool:
    return Employee.objects.filter(membership=membership).exists()


def is_user(membership: Membership) -> bool:
    return role_kind(membership.role) in WEB_KINDS


def in_scope(viewer: Membership, person: Membership) -> bool:
    """Whether `viewer` sees `person`: every branch, or one of the person's branches."""
    allowed = scope.branch_ids(viewer)
    if allowed is None:
        return True
    return person.branches.filter(pk__in=allowed).exists()


# Today -------------------------------------------------------------------------------------


def today_states(
    company: Company, members: list[Membership], now: datetime | None = None
) -> dict[int, dict | None]:
    """Each person's state now, in the company's day: `in` (checked in, since then), `out`
    (came and left, since the check-out; no time when the system closed the day), `leave`
    (approved time off), `off` (a day off: no shift on their roster, a holiday, suspended, or not
    one of the company's workdays for someone without a roster) or `not_in` (expected and not
    here, absent included). None for someone who left."""
    now = now or timezone.now()
    today = clock.today(company, now)
    current = [member for member in members if member.status in CURRENT]
    ids = [member.pk for member in current]
    if not ids:
        return {member.pk: None for member in members}
    records = AttendanceRecord.objects.filter(
        company=company,
        membership_id__in=ids,
        date__range=(today - timedelta(days=1), today),
    ).order_by("check_in_at", "pk")
    open_since: dict[int, datetime] = {}
    left_at: dict[int, datetime] = {}
    # Days the system closed (arrivals only, or a forgotten check-out): over, but nobody saw the
    # person leave, so no time is shown for them.
    ended: set[int] = set()
    absent, excused = set(), set()
    for record in records:
        if record.status == AttendanceRecord.Status.OPEN:
            open_since[record.membership_id] = record.check_in_at
        elif record.date != today:
            continue
        elif record.attended and record.check_out_at is not None:
            if record.out_source == AttendanceRecord.Source.SYSTEM:
                ended.add(record.membership_id)
                continue
            left_at[record.membership_id] = max(
                record.check_out_at, left_at.get(record.membership_id, record.check_out_at)
            )
        elif record.status == AttendanceRecord.Status.ABSENT:
            absent.add(record.membership_id)
        elif record.status == AttendanceRecord.Status.EXCUSED:
            excused.add(record.membership_id)
    away = attendance.leave_days(company, today, today, ids)
    holiday = bool(attendance.holidays(company, today, today))
    shifts: dict[int, set[str]] = {}
    for member_id, status in (
        WorkShift.objects.live()
        .filter(company=company, date=today, membership_id__in=ids)
        .exclude(status=WorkShift.Status.OPEN)
        .values_list("membership_id", "status")
    ):
        shifts.setdefault(member_id, set()).add(status)
    rostered = set(
        Membership.objects.filter(pk__in=ids, work_schedule__schedule__isnull=False).values_list(
            "pk", flat=True
        )
    )
    workday = today.weekday() in (company.workdays or [])
    found: dict[int, dict | None] = {member.pk: None for member in members}
    for member in current:
        pk = member.pk
        if pk in open_since:
            found[pk] = {"state": IN, "since": open_since[pk]}
        elif pk in left_at:
            found[pk] = {"state": OUT, "since": left_at[pk]}
        elif pk in ended:
            found[pk] = {"state": OUT, "since": None}
        elif today in away.get(pk, {}) or WorkShift.Status.LEAVE in shifts.get(pk, ()):
            found[pk] = {"state": LEAVE, "since": None}
        elif member.status == Membership.Status.SUSPENDED or pk in excused or holiday:
            found[pk] = {"state": OFF, "since": None}
        elif pk in absent or WorkShift.Status.PLANNED in shifts.get(pk, ()):
            found[pk] = {"state": NOT_IN, "since": None}
        elif pk in rostered or not workday:
            found[pk] = {"state": OFF, "since": None}
        else:
            found[pk] = {"state": NOT_IN, "since": None}
    return found


# The bot --------------------------------------------------------------------------------


def bot_settings() -> DavomatSettings | None:
    """The organization's settings row (its bot), or None before the first-run setup."""
    company = conf.organization()
    return conf.get_settings(company) if company is not None else None


def bot_token() -> str:
    """The organization's bot token (decrypted), or "" when none is connected."""
    row = bot_settings()
    return row.bot_token if row is not None and row.bot_token else ""


def token_version() -> int:
    """Moves on with every token change; the bot restarts when it differs from the one it has.
    Read from Redis (`davomat:bot_token_version`), else from the database."""
    from apps.core import redis as core_redis

    try:
        value = core_redis.get_redis().get(core_redis.key(*TOKEN_VERSION_KEY))
    except Exception:  # Redis down: the database knows too
        value = None
    if value is not None:
        return int(value)
    row = bot_settings()
    return row.token_version if row is not None else 0
