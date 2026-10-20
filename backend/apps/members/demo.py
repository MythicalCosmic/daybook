"""Demo data of the team: a believable shop of twenty people across Chilonzor and Yunusobod,
with a branch manager who sees only her branch, a suspension, people who left, join requests
(one from a former employee) and two weeks of work history so the numbers mean something.

Demo users get Telegram ids 3001 to 3040. `seed_demo --reset` doesn't remove them yet (they
aren't in its EVERYONE list), so they are reused by id when the demo is rebuilt.

The twelve extra working staff come with `DEMO_EXTRA_STAFF=1` (`DEMO_EXTRA_STAFF=1 make demo`):
`core/tests/test_seed_demo.py` still expects exactly the six core people to be approved. The
suspension, the people who left and the join requests are always there.
"""

import os
from datetime import timedelta

from django.utils import timezone

from apps.accounts.models import User
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.members.audit_actions import MemberAction
from apps.members.models import AccessRole, Membership, Position
from apps.members.permissions import Perm

# telegram id, first, last, position, role, branches ("C" Chilonzor, "Y" Yunusobod),
# joined (days ago), phone, username, on-time profile (late days, missed days)
STAFF = [
    (
        3001,
        "Sardor",
        "Rahimov",
        "Cashier",
        "Cashier",
        "C",
        410,
        "+998901112233",
        "sardor_r",
        ({3}, set()),
    ),
    (
        3002,
        "Gulnora",
        "Ismoilova",
        "Sales floor",
        "Employee",
        "C",
        265,
        "+998935557711",
        "",
        (set(), set()),
    ),
    (
        3003,
        "Otabek",
        "Nazarov",
        "Stock & warehouse",
        "Employee",
        "C",
        190,
        "+998977001122",
        "otabek_n",
        ({2, 6, 11}, {9}),
    ),
    (
        3004,
        "Shahzoda",
        "Yusupova",
        "Sales floor",
        "Employee",
        "C",
        96,
        "+998998887766",
        "",
        ({5}, set()),
    ),
    (
        3005,
        "Ulug‘bek",
        "Qodirov",
        "Delivery",
        "Employee",
        "C",
        44,
        "+998903334455",
        "ulugbek_q",
        ({1, 4, 8, 12}, {6, 13}),
    ),
    (
        3006,
        "Kamola",
        "Ergasheva",
        "Cashier",
        "Cashier",
        "C",
        21,
        "+998946662200",
        "",
        (set(), {10}),
    ),
    (
        3007,
        "Farrux",
        "Aliyev",
        "Shift lead",
        "Branch manager",
        "Y",
        520,
        "+998901234000",
        "farrux_aliyev",
        (set(), set()),
    ),
    (
        3008,
        "Dilshod",
        "Karimov",
        "Sales floor",
        "Employee",
        "Y",
        330,
        "+998935550909",
        "",
        ({7, 9}, set()),
    ),
    (
        3009,
        "Malika",
        "Tosheva",
        "Cashier",
        "Cashier",
        "Y",
        150,
        "+998977773311",
        "malika_t",
        ({4}, set()),
    ),
    (
        3010,
        "Sherzod",
        "Umarov",
        "Delivery",
        "Employee",
        "Y",
        73,
        "+998998001234",
        "",
        ({2, 3, 10}, {5}),
    ),
    (
        3011,
        "Zarina",
        "Abdullayeva",
        "Stock & warehouse",
        "Employee",
        "Y",
        12,
        "+998903219876",
        "",
        (set(), set()),
    ),
    (
        3012,
        "Aziza",
        "Rasulova",
        "Office",
        "Accountant",
        "CY",
        610,
        "+998946543210",
        "aziza_buxgalter",
        (set(), set()),
    ),
]
ROUTINES = {
    "Sales floor": "Tidy the sales floor and face the shelves",
    "Cashier": "Count the float and check the card terminal",
    "Stock & warehouse": "Check deliveries against the nakladnaya",
    "Delivery": "Deliver online orders",
    "Shift lead": "Open the branch and brief the shift",
    "Office": "Reconcile yesterday's card payments",
}
BRANCH_MANAGER = [
    Perm.MEMBERS_VIEW,
    Perm.MEMBERS_APPROVE,
    Perm.TASKS_VIEW_ALL,
    Perm.TASKS_ASSIGN,
    Perm.TASKS_CONFIRM,
    Perm.REPORTS_VIEW,
    Perm.TIME_OFF_APPROVE,
    Perm.ANNOUNCE,
    Perm.DASHBOARD_ACCESS,
    Perm.ATTENDANCE_VIEW,
    Perm.SALES_VIEW,
    Perm.FINANCE_CLAIM,
]


def seed(company, people, now) -> None:
    """Add demo rows to `company`. `people` maps owner, manager, worker, madina, jasur
    and nigora to their memberships."""
    owner, manager = people["owner"], people["manager"]
    branches = list(company.branches.order_by("order", "pk"))
    chilonzor = branches[0]
    yunusobod = branches[1] if len(branches) > 1 else branches[0]
    by_code = {"C": chilonzor, "Y": yunusobod}
    positions = {p.name: p for p in Position.objects.for_company(company)}
    for index, name in enumerate(ROUTINES):
        if name not in positions:
            positions[name] = Position.objects.create(company=company, name=name, order=index)
    roles = {role.name: role for role in AccessRole.objects.for_company(company)}
    if "Branch manager" not in roles:
        roles["Branch manager"] = AccessRole.objects.create(
            company=company, name="Branch manager", permissions=[str(p) for p in BRANCH_MANAGER]
        )

    # When the six core people joined (the core demo leaves it empty).
    for key, days in (
        ("owner", 1100),
        ("manager", 760),
        ("worker", 380),
        ("madina", 230),
        ("jasur", 140),
        ("nigora", 58),
    ):
        person = people[key]
        Membership.objects.filter(pk=person.pk).update(decided_at=now - timedelta(days=days))

    staff = []
    for tg, first, last, position, role, codes, days, phone, username, profile in (
        STAFF if extra_staff() else []
    ):
        person = _member(
            company,
            tg,
            first,
            last,
            phone=phone,
            username=username,
            position=positions[position],
            role=roles.get(role) or roles.get("Employee"),
            branches=[by_code[code] for code in codes],
            joined=now - timedelta(days=days),
            onboarded=now - timedelta(days=days),
        )
        staff.append((person, position, profile))
        _audit_at(
            AuditLog.Action.MEMBER_APPROVED, company, owner.user, person, now - timedelta(days=days)
        )
    if staff and yunusobod != chilonzor:
        yunusobod.manager = staff[6][0]
        yunusobod.save(update_fields=["manager", "updated_at"])

    # Two weeks of daily work for each of them, so on-time rates differ.
    _work_history(company, manager, staff, now)

    # A suspension (an investigation into a cash shortage), people who left, a block.
    bobur = _member(
        company,
        3013,
        "Bobur",
        "Saidov",
        phone="+998901118899",
        position=positions["Sales floor"],
        role=roles["Employee"],
        branches=[chilonzor],
        joined=now - timedelta(days=300),
        onboarded=now - timedelta(days=300),
    )
    until = timezone.localdate() + timedelta(days=5)
    Membership.objects.filter(pk=bobur.pk).update(
        status=Membership.Status.SUSPENDED, suspended_until=until
    )
    _audit_at(
        MemberAction.SUSPENDED,
        company,
        owner.user,
        bobur,
        now - timedelta(days=2),
        until=until.isoformat(),
        reason="Cash shortage under review",
    )
    nodira = _member(
        company,
        3014,
        "Nodira",
        "Xolmatova",
        phone="+998935554433",
        position=positions["Cashier"],
        role=roles["Employee"],
        branches=[yunusobod],
        joined=now - timedelta(days=420),
        onboarded=now - timedelta(days=420),
    )
    Membership.objects.filter(pk=nodira.pk).update(
        status=Membership.Status.LEFT, decided_at=now - timedelta(days=19)
    )
    _audit_at(
        AuditLog.Action.MEMBER_LEFT,
        company,
        owner.user,
        nodira,
        now - timedelta(days=19),
        terminated_on=(timezone.localdate() - timedelta(days=19)).isoformat(),
        reason="resignation",
    )
    rustam = _member(
        company,
        3015,
        "Rustam",
        "Nurmatov",
        phone="+998977008800",
        position=positions["Delivery"],
        role=roles["Employee"],
        branches=[chilonzor],
        joined=now - timedelta(days=200),
        onboarded=now - timedelta(days=200),
    )
    Membership.objects.filter(pk=rustam.pk).update(
        status=Membership.Status.BLOCKED, decided_at=now - timedelta(days=64)
    )
    _audit_at(
        AuditLog.Action.MEMBER_BLOCKED,
        company,
        owner.user,
        rustam,
        now - timedelta(days=64),
        terminated_on=(timezone.localdate() - timedelta(days=64)).isoformat(),
    )

    # Join requests waiting: two new people and a former employee asking to come back.
    for tg, first, last, position, hours, phone, username in (
        (3016, "Akmal", "Jo‘rayev", "Cashier", 2, "+998901239988", "akmal_j"),
        (3017, "Laylo", "Hamidova", "Delivery", 26, "+998946001100", ""),
    ):
        user = _user(tg, first, last, phone, username)
        request = Membership.objects.create(
            company=company,
            user=user,
            first_name=first,
            last_name=last,
            position=positions[position],
            status=Membership.Status.PENDING,
            onboarded_at=now - timedelta(hours=hours),
        )
        Membership.objects.filter(pk=request.pk).update(created_at=now - timedelta(hours=hours + 1))
    jahongir = _member(
        company,
        3018,
        "Jahongir",
        "Mirzaev",
        phone="+998935001234",
        position=positions["Stock & warehouse"],
        role=roles["Employee"],
        branches=[],
        joined=now - timedelta(days=700),
        onboarded=now - timedelta(days=700),
    )
    _audit_at(
        AuditLog.Action.MEMBER_LEFT,
        company,
        owner.user,
        jahongir,
        now - timedelta(days=240),
        terminated_on=(timezone.localdate() - timedelta(days=240)).isoformat(),
        reason="mutual_agreement",
    )
    Membership.objects.filter(pk=jahongir.pk).update(
        status=Membership.Status.PENDING,
        role=None,
        decided_at=None,
        decided_by=None,
        onboarded_at=now - timedelta(hours=5),
    )

    # A little history on Person 360: a promotion and a branch move.
    if staff:
        sardor, malika = staff[0][0], staff[8][0]
        _audit_at(
            MemberAction.ROLE_CHANGED,
            company,
            owner.user,
            sardor,
            now - timedelta(days=60),
            changes={"role": ["Employee", "Cashier"]},
        )
        _audit_at(
            MemberAction.CHANGED,
            company,
            manager.user,
            malika,
            now - timedelta(days=33),
            changes={
                "branches": [["Chilonzor"], ["Yunusobod"]],
                "home_branch": ["Chilonzor", "Yunusobod"],
            },
        )


def extra_staff() -> bool:
    return os.environ.get("DEMO_EXTRA_STAFF", "").strip().lower() in ("1", "true", "yes")


def _user(telegram_id, first, last, phone="", username="") -> User:
    user, created = User.objects.get_or_create(
        telegram_id=telegram_id,
        defaults={
            "username": f"tg{telegram_id}",
            "first_name": first,
            "last_name": last,
            "phone": phone,
            "telegram_username": username,
            "language": "uz",
        },
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user


def _member(
    company,
    telegram_id,
    first,
    last,
    *,
    phone,
    position,
    role,
    branches,
    joined,
    onboarded,
    username="",
):
    user = _user(telegram_id, first, last, phone, username)
    member = Membership.objects.create(
        company=company,
        user=user,
        first_name=first,
        last_name=last,
        position=position,
        role=role,
        status=Membership.Status.APPROVED,
        onboarded_at=onboarded,
        decided_at=joined,
        home_branch=branches[0] if branches else None,
    )
    member.branches.set(branches)
    return member


def _audit_at(action, company, actor, target, when, **details) -> None:
    row = audit.record(action, company_id=company.pk, actor=actor, target=target, **details)
    AuditLog.objects.filter(pk=row.pk).update(created_at=when)


def _work_history(company, manager, staff, now) -> None:
    from apps.tasks.models import Task, TaskTemplate

    templates = {}
    for person, position, (late, missed) in staff:
        title = ROUTINES[position]
        template = templates.get(title)
        if template is None:
            template = TaskTemplate.objects.create(
                company=company, title=title, due_time="10:00", created_by=manager
            )
            templates[title] = template
        template.assignees.add(person)
        rows = []
        for days_ago in range(1, 15):
            due = now - timedelta(days=days_ago)
            done_at = None if days_ago in missed else due - timedelta(minutes=12 + days_ago)
            if days_ago in late:
                done_at = due + timedelta(minutes=35 + 5 * days_ago)
            rows.append(
                Task(
                    company=company,
                    kind=Task.Kind.DAILY,
                    template=template,
                    for_date=timezone.localtime(due).date(),
                    title=title,
                    assignee=person,
                    branch=person.home_branch,
                    created_by=manager,
                    due_at=due,
                    status=Task.Status.TODO if done_at is None else Task.Status.DONE,
                    completed_at=done_at,
                )
            )
        Task.objects.bulk_create(rows)
