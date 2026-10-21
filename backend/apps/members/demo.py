"""Demo data of the team (apps/core/demo_plan.py): the core demo makes Demo Dorixona's fifteen
people; this adds what HR sees around them. Bobur, a pharmacist, is suspended while a shortage
of prescription medicines is looked into, Nodira (a Yunusobod pharmacist) left, Rustam (a
courier) was blocked, two people ask to join and a former storekeeper asks to come back;
approvals, a promotion and a move between the pharmacies give Person 360 a history.
"""

from datetime import time, timedelta

from apps.accounts.models import User
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.core import demo_plan as story_plan
from apps.members.audit_actions import MemberAction
from apps.members.models import AccessRole, Membership, Position


def seed(company, people, now) -> None:
    """Add demo rows to `company`. `people` maps owner, manager, worker, madina, jasur
    and nigora to their memberships."""
    story = story_plan.Plan(company, people, now)
    owner = people["owner"]
    positions = {p.name: p for p in Position.objects.for_company(company)}
    for index, name in enumerate(story_plan.POSITIONS):
        if name not in positions:  # the module's own tests start without them
            positions[name] = Position.objects.create(company=company, name=name, order=index)
    roles = {role.name: role for role in AccessRole.objects.for_company(company)}

    def joined(key):
        return story.at(story.joined(key), time(10))

    # Everyone's approval, on the day they joined.
    for key, member in story.members().items():
        if key != "owner":
            _audit_at(AuditLog.Action.MEMBER_APPROVED, company, owner.user, member, joined(key))

    def member(person, status, decided_at, **fields):
        user = _user(person)
        branch = story.branches[person.branches[0]]
        created = Membership.objects.create(
            company=company,
            user=user,
            first_name=person.first,
            last_name=person.last,
            position=positions.get(person.position),
            role=roles.get(person.role) or roles.get("Cashier") or roles.get("Employee"),
            status=status,
            onboarded_at=joined(person.key) + timedelta(hours=1),
            decided_at=decided_at,
            decided_by=owner.user,
            home_branch=branch,
            **fields,
        )
        created.branches.set([branch])
        _audit_at(AuditLog.Action.MEMBER_APPROVED, company, owner.user, created, joined(person.key))
        return created

    # Bobur, a day pharmacist at Chilonzor, is suspended until the count is checked.
    first, last, reason = story_plan.SUSPENSION
    bobur = member(
        story_plan.SUSPENDED,
        Membership.Status.SUSPENDED,
        joined("bobur"),
        suspended_until=story.day(last),
    )
    _audit_at(
        MemberAction.SUSPENDED,
        company,
        owner.user,
        bobur,
        story.at(story.day(first), time(18, 20)),
        until=story.day(last).isoformat(),
        reason=reason,
    )
    # Nodira, a Yunusobod pharmacist, resigned; Kamola came two days before her last day.
    left_on = story.day(-story_plan.LEFT_DAYS_AGO)
    nodira = member(story_plan.LEFT, Membership.Status.LEFT, story.at(left_on, time(18)))
    _audit_at(
        AuditLog.Action.MEMBER_LEFT,
        company,
        owner.user,
        nodira,
        story.at(left_on, time(18)),
        terminated_on=left_on.isoformat(),
        reason="resignation",
    )
    blocked_on = story.day(-story_plan.BLOCKED_DAYS_AGO)
    rustam = member(story_plan.BLOCKED, Membership.Status.BLOCKED, story.at(blocked_on, time(11)))
    _audit_at(
        AuditLog.Action.MEMBER_BLOCKED,
        company,
        owner.user,
        rustam,
        story.at(blocked_on, time(11)),
        terminated_on=blocked_on.isoformat(),
    )

    # Join requests waiting: two new people and a former storekeeper asking to come back.
    for _key, tg, first_name, last_name, position, hours in story_plan.REQUESTS:
        person = story_plan.Person(
            _key, tg, first_name, last_name, position, "Employee", "C", 0, None
        )
        request = Membership.objects.create(
            company=company,
            user=_user(person),
            first_name=first_name,
            last_name=last_name,
            position=positions[position],
            status=Membership.Status.PENDING,
            onboarded_at=now - timedelta(hours=hours),
        )
        Membership.objects.filter(pk=request.pk).update(created_at=now - timedelta(hours=hours + 1))
    returning = story_plan.RETURNING
    jahongir = member(returning, Membership.Status.APPROVED, joined("jahongir"))
    left_then = story.day(-240)
    _audit_at(
        AuditLog.Action.MEMBER_LEFT,
        company,
        owner.user,
        jahongir,
        story.at(left_then, time(17)),
        terminated_on=left_then.isoformat(),
        reason="mutual_agreement",
    )
    Membership.objects.filter(pk=jahongir.pk).update(
        status=Membership.Status.PENDING,
        role=None,
        decided_at=None,
        decided_by=None,
        onboarded_at=now - timedelta(hours=5),
    )
    jahongir.branches.clear()

    # A little history on Person 360: a promotion and a move between the pharmacies.
    sardor, dilshod = story.member("sardor"), story.member("dilshod")
    if sardor is not None:
        _audit_at(
            MemberAction.CHANGED,
            company,
            owner.user,
            sardor,
            now - timedelta(days=60),
            changes={"position": ["Farmatsevt", "Provizor"]},
        )
    if dilshod is not None:
        _audit_at(
            MemberAction.CHANGED,
            company,
            people["manager"].user,
            dilshod,
            now - timedelta(days=33),
            changes={
                "branches": [["Chilonzor"], ["Yunusobod"]],
                "home_branch": ["Chilonzor", "Yunusobod"],
            },
        )


def _user(person) -> User:
    user, created = User.objects.get_or_create(
        telegram_id=person.telegram_id,
        defaults={
            "username": f"tg{person.telegram_id}",
            "first_name": person.first,
            "last_name": person.last,
            "phone": person.phone,
            "telegram_username": person.username,
            "language": person.language,
        },
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user


def _audit_at(action, company, actor, target, when, **details) -> None:
    row = audit.record(action, company_id=company.pk, actor=actor, target=target, **details)
    AuditLog.objects.filter(pk=row.pk).update(created_at=when)
