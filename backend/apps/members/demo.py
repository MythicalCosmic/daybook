"""Demo data of the team (apps/core/demo_plan.py): the core demo makes Demo Dorixona's fifteen
people; this adds what HR sees around them. Bobur, a pharmacist, is suspended while a shortage
of prescription medicines is looked into, Nodira (a Yunusobod pharmacist) left, Rustam (a
courier) was blocked, two people ask to join and a former storekeeper asks to come back;
approvals, a promotion and a move between the pharmacies give Person 360 a history. Team links:
one from this morning's staff meeting that three new pharmacists joined through (a fourth is
still making an account), one for Yunusobod that asks first (two requests wait), and one that
ended.
"""

from datetime import time, timedelta

from apps.accounts.models import User
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.core import demo_plan as story_plan
from apps.members.audit_actions import MemberAction
from apps.members.models import AccessRole, JoinLink, Membership, Position

# People who came through the demo's team links: key, telegram id, first, last, minutes ago
# (None: still making their account).
MEETING_JOINERS = [
    ("sevara", 3101, "Sevara", "Qodirova", 52),
    ("javohir", 3102, "Javohir", "Usmonov", 47),
    ("dilfuza", 3103, "Dilfuza", "Rahmonova", 31),
    ("bahodir", 3104, "Bahodir", "Ergashev", None),
]
YUNUSOBOD_REQUESTS = [
    ("zarina", 3105, "Zarina", "Abdullayeva", 180),
    ("ulugbek", 3106, "Ulug‘bek", "Sobirov", 95),
]


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

    _team_links(company, story, owner, positions, roles, now)

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


def _team_links(company, story, owner, positions, roles, now) -> None:
    chilonzor, yunusobod = story.branches["C"], story.branches["Y"]
    pharmacist = positions[story_plan.PHARMACIST]

    def link(name, made_minutes_ago, **fields):
        created = JoinLink.objects.create(company=company, created_by=owner, name=name, **fields)
        made = now - timedelta(minutes=made_minutes_ago)
        JoinLink.objects.filter(pk=created.pk).update(created_at=made)
        _audit_at(MemberAction.LINK_CREATED, company, owner.user, created, made)
        return created

    def joiner(key, tg, first_name, last_name, through, minutes_ago, *, branch, status):
        person = story_plan.Person(key, tg, first_name, last_name, None, "Employee", "C", 0, None)
        finished = now - timedelta(minutes=minutes_ago) if minutes_ago is not None else None
        membership = Membership.objects.create(
            company=company,
            user=_user(person),
            first_name=first_name if finished else "",
            last_name=last_name if finished else "",
            position=pharmacist if finished or through.position_id else None,
            status=status,
            join_link=through,
            onboarded_at=finished,
        )
        opened = (finished or now) - timedelta(minutes=4)
        Membership.objects.filter(pk=membership.pk).update(created_at=opened)
        if status == Membership.Status.APPROVED:
            Membership.objects.filter(pk=membership.pk).update(
                role=through.role,
                joined_by_link=True,
                decided_by=owner.user,
                decided_at=finished,
                home_branch=branch,
            )
            membership.branches.set([branch])
            _audit_at(
                AuditLog.Action.MEMBER_APPROVED,
                company,
                owner.user,
                membership,
                finished,
                link=through.name,
            )
        return membership

    meeting = link(
        "Xodimlar yig‘ilishi",
        70,
        branch=chilonzor,
        role=roles.get(story_plan.TILL),
        position=pharmacist,
        max_uses=10,
        expires_at=now + timedelta(days=2),
    )
    for key, tg, first_name, last_name, minutes_ago in MEETING_JOINERS:
        done = minutes_ago is not None
        status = Membership.Status.APPROVED if done else Membership.Status.PENDING
        joiner(
            key, tg, first_name, last_name, meeting, minutes_ago, branch=chilonzor, status=status
        )
    JoinLink.objects.filter(pk=meeting.pk).update(uses=3, reported_at=now - timedelta(minutes=30))

    asking = link(
        "Yunusobod: yangi xodimlar",
        60 * 26,
        auto_approve=False,
        branch=yunusobod,
        expires_at=now + timedelta(days=29),
    )
    for key, tg, first_name, last_name, minutes_ago in YUNUSOBOD_REQUESTS:
        joiner(
            key,
            tg,
            first_name,
            last_name,
            asking,
            minutes_ago,
            branch=yunusobod,
            status=Membership.Status.PENDING,
        )
    JoinLink.objects.filter(pk=asking.pk).update(uses=len(YUNUSOBOD_REQUESTS))

    ended = link(
        "Ochilish kuni",
        60 * 24 * 40,
        branch=yunusobod,
        role=roles.get(story_plan.TILL),
        max_uses=6,
        expires_at=now - timedelta(days=38),
    )
    assert ended.pk


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
