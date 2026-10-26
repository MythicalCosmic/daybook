"""Team links: one link (or QR code) that adds many people at once (the owner, 26.10.2026: "i
show one qr code or link, and it can add lot of people at once").

Everyone who opens a team link and creates their account joins with the link's branch, role and
position: straight away when the link says so (`services.admit`), else as a join request with
those choices made. The company's own invite link keeps asking for approval.

    create_link / update_link / delete_link   the dashboard and the owner bot (members.approve)
    open_link                                 the employee bot's `/start j_…`
    report_joins                              one note per burst of joins (tasks.queue_link_report)
"""

from datetime import datetime, timedelta

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.accounts.models import User
from apps.audit import services as audit
from apps.companies.models import Branch, Company
from apps.core.exceptions import DomainError
from apps.groups import tasks as group_jobs
from apps.inbox import services as inbox
from apps.members import scope, services
from apps.members.audit_actions import MemberAction
from apps.members.models import AccessRole, JoinLink, Membership, Position
from apps.members.permissions import Perm
from apps.members.queries import members_with_perm

MAX_PLACES = 500
MAX_DAYS = 365
# Approvers hear about people who joined through a link in one note per burst.
REPORT_KIND = "members.link_joined"
# How many names one note or group post lists before "and N more".
LISTED = 15
EDITABLE = ("name", "auto_approve", "branch", "role", "position", "max_uses", "expires_at")
# Changing these makes the editor the one whose approval the link stands for.
AUTHORITY = {"auto_approve", "branch", "role"}


# Reading ----------------------------------------------------------------------------------


def visible_links(member: Membership) -> QuerySet[JoinLink]:
    """The links `member` sees: all of them with every branch, else those of their branches and
    the ones they made."""
    links = (
        JoinLink.objects.for_company(member.company)
        .filter(deleted_at__isnull=True)
        .select_related("branch", "role", "position", "created_by__user")
    )
    allowed = scope.branch_ids(member)
    if allowed is not None:
        links = links.filter(Q(branch_id__in=allowed) | Q(created_by=member))
    return links


def may_edit(member: Membership, link: JoinLink, *, default: AccessRole | None = None) -> bool:
    """Whether `member` could make the link as it stands: its branch is theirs to give (a link
    without one, only with every branch or when they made it) and so is its role. `default`
    saves looking up the company's default role for each of many links."""
    allowed = scope.branch_ids(member)
    if link.branch_id is None:
        if allowed is not None and link.created_by_id != member.pk:
            return False
    elif not scope.allows(allowed, link.branch_id):
        return False
    role = link.role or default or default_role(link.company)
    return role is None or services.may_assign_role(member, role)


def default_role(company: Company) -> AccessRole | None:
    return AccessRole.objects.for_company(company).filter(is_default=True).first()


def ordered(links: QuerySet[JoinLink], now: datetime | None = None) -> list[JoinLink]:
    """Working links first, then the rest; newest first within each."""
    now = now or timezone.now()
    return sorted(links, key=lambda link: link.status_at(now) != JoinLink.Status.ACTIVE)


# Changing ---------------------------------------------------------------------------------


@transaction.atomic
def create_link(
    company: Company,
    *,
    by: Membership,
    name: str,
    auto_approve: bool = True,
    branch: Branch | None = None,
    role: AccessRole | None = None,
    position: Position | None = None,
    max_uses: int | None = None,
    expires_at: datetime | None = None,
) -> JoinLink:
    _ensure_approver(company, by)
    link = JoinLink(company=company, created_by=by)
    _apply(
        link,
        by,
        {
            "name": name,
            "auto_approve": auto_approve,
            "branch": branch,
            "role": role,
            "position": position,
            "max_uses": max_uses,
            "expires_at": expires_at,
        },
    )
    link.save()
    audit.record(MemberAction.LINK_CREATED, company_id=company.pk, actor=by.user, target=link)
    services.bump_on_commit(company.pk, "members.links")
    return link


@transaction.atomic
def update_link(link: JoinLink, *, by: Membership, **fields) -> JoinLink:
    """Change any of EDITABLE, or `is_active` (False stops the link, True turns it back on)."""
    link = _lock(link)
    _ensure_approver(link.company, by)
    if not may_edit(by, link):
        raise PermissionDenied(_("You can't change this link."))
    unknown = set(fields) - {*EDITABLE, "is_active"}
    if unknown:
        raise TypeError(f"update_link: unknown fields {sorted(unknown)}")
    changed = _apply(link, by, {name: fields[name] for name in EDITABLE if name in fields})
    action = None
    if "is_active" in fields and bool(fields["is_active"]) != link.is_active:
        link.is_active = bool(fields["is_active"])
        action = MemberAction.LINK_RESUMED if link.is_active else MemberAction.LINK_STOPPED
    if not changed and action is None:
        return link
    if changed & AUTHORITY or action == MemberAction.LINK_RESUMED:
        # Whoever sets the rules (or turns the link back on) is whose approval it stands for
        # from now on: joins are checked against their rights, which these rules passed.
        link.created_by = by
    link.save()
    if changed:
        audit.record(
            MemberAction.LINK_CHANGED,
            company_id=link.company_id,
            actor=by.user,
            target=link,
            fields=sorted(changed),
        )
    if action is not None:
        audit.record(action, company_id=link.company_id, actor=by.user, target=link)
    services.bump_on_commit(link.company_id, "members.links")
    return link


@transaction.atomic
def delete_link(link: JoinLink, *, by: Membership) -> None:
    """The link stops working at once and leaves every list. People who joined through it
    stay, and so does its row: their history, and the note about a burst of joins still due,
    need it (nothing else is touched, so no lock waits on a join in progress)."""
    link = _lock(link)
    _ensure_approver(link.company, by)
    if not may_edit(by, link):
        raise PermissionDenied(_("You can't change this link."))
    link.is_active = False
    link.deleted_at = timezone.now()
    link.save(update_fields=["is_active", "deleted_at", "updated_at"])
    audit.record(MemberAction.LINK_DELETED, company_id=link.company_id, actor=by.user, target=link)
    services.bump_on_commit(link.company_id, "members.links")


def _apply(link: JoinLink, by: Membership, fields: dict) -> set[str]:
    """Check `fields` and set them on `link`; returns the names that changed."""
    if not fields:
        return set()
    company = link.company
    now = timezone.now()
    changed = set()
    for name, value in fields.items():
        if name == "name":
            value = " ".join(str(value or "").split())
            if not value:
                raise DomainError(_("Give the link a name."))
            if len(value) > 100:
                raise DomainError(_("A link's name can be at most 100 characters."))
        elif name == "auto_approve":
            value = bool(value)
        elif name == "branch" and value is not None:
            if value.company_id != company.pk or not value.is_active:
                raise DomainError(_("Pick a branch of this company."))
            if not scope.allows(scope.branch_ids(by), value.pk):
                raise DomainError(_("You can only give the branches you manage."))
        elif name == "role" and value is not None:
            if value.company_id != company.pk:
                raise DomainError(_("Pick a role of this company."))
            if value.is_owner:  # a leaked QR code must never make strangers owners
                raise DomainError(_("A team link can't make people owners."))
        elif name == "position" and value is not None:
            if value.company_id != company.pk or not value.is_active:
                raise DomainError(_("Pick a position of this company."))
        elif name == "max_uses" and value is not None:
            if not 1 <= value <= MAX_PLACES:
                raise DomainError(
                    _("A link can take from 1 to %(count)d people.") % {"count": MAX_PLACES}
                )
        elif name == "expires_at" and value is not None:
            if value <= now:
                raise DomainError(_("The end must be in the future."))
            if value > now + timedelta(days=MAX_DAYS):
                raise DomainError(_("A link can work for at most a year."))
        if name in ("branch", "role", "position"):
            if getattr(link, f"{name}_id") != (value.pk if value is not None else None):
                changed.add(name)
        elif getattr(link, name) != value:
            changed.add(name)
        setattr(link, name, value)

    # The link stands for its maker's approval: the role is one they may give.
    role = link.role or default_role(company)
    if role is not None and not services.may_assign_role(by, role):
        raise DomainError(_("You can only give a role whose permissions you have yourself."))
    allowed = scope.branch_ids(by)
    if link.branch_id is None and allowed is not None:
        raise DomainError(_("Choose one of your branches."))
    if link.auto_approve and link.branch_id is None and _several_branches(company):
        raise DomainError(_("Choose the branch these people will work in."))
    return changed


def _several_branches(company: Company) -> bool:
    return Branch.objects.filter(company=company, is_active=True).count() > 1


def _ensure_approver(company: Company, by: Membership) -> None:
    if by.company_id != company.pk or not by.has_perm(Perm.MEMBERS_APPROVE):
        raise PermissionDenied(_("You don't have permission to do this."))


def _lock(link: JoinLink) -> JoinLink:
    return (
        JoinLink.objects.select_for_update(of=("self",))
        .select_related("company", "branch", "role", "position")
        .get(pk=link.pk)
    )


# Joining ----------------------------------------------------------------------------------


def find(start_param: str) -> JoinLink:
    """The link a `/start j_…` parameter names, of an active company."""
    code = start_param.removeprefix(JoinLink.PREFIX)
    link = None
    if code != start_param:
        link = (
            JoinLink.objects.select_related("company", "position")
            .filter(code=code, company__is_active=True, deleted_at__isnull=True)
            .first()
        )
    if link is None:
        raise DomainError(
            _("This invite link is invalid or has expired. Ask your manager for a new one.")
        )
    return link


@transaction.atomic
def open_link(user: User, start_param: str) -> tuple[Membership, bool]:
    """`/start j_…`: ask to join the link's company through it. Returns the membership and
    whether the link let them in just now (the bot then welcomes them itself).

    Someone already on the team just hears where they stand; someone whose request waits
    switches to this link and, when it adds people straight away, is let in."""
    link = find(start_param)
    mine = Membership.objects.filter(company=link.company, user=user).first()
    if mine is not None and (
        mine.status in services.CURRENT
        or (mine.status == Membership.Status.PENDING and mine.join_link_id == link.pk)
    ):
        return mine, False  # on the team, or already waiting through this link
    status = link.status_at(timezone.now())
    if status == JoinLink.Status.STOPPED:
        raise DomainError(_("This team link was switched off. Ask your manager for a new one."))
    if status == JoinLink.Status.EXPIRED:
        raise DomainError(_("This team link has expired. Ask your manager for a new one."))
    if status == JoinLink.Status.FULL:
        raise DomainError(_("This team link has no places left. Ask your manager for a new one."))

    membership, _created = services.request_access(user, link.company)
    if membership.status != Membership.Status.PENDING or membership.join_link_id == link.pk:
        return membership, False
    membership.join_link = link
    fields = ["join_link", "updated_at"]
    if link.position_id is not None and not membership.is_onboarded:
        membership.position = link.position  # chosen for them; they can change it
        fields.append("position")
    membership.save(update_fields=fields)
    if membership.is_onboarded:  # their details are on file: the link decides now
        # A place is used only if it lets them in: switching between links takes none.
        admitted = services.admit(membership, welcome=False, count_refusal=False)
        if admitted is not None:
            return admitted, True
    return membership, False


# The note to approvers ----------------------------------------------------------------------


def report_joins(link_id: int) -> int:
    """Tell the approvers who see the link (and its maker) who joined through it since the last
    note, in one message, and post the new people to the company's groups in one go. Returns
    how many people the note named."""
    with transaction.atomic():
        link = (
            JoinLink.objects.select_for_update(of=("self",))
            .select_related("company", "branch")
            .filter(pk=link_id)
            .first()
        )
        if link is None:
            return 0
        people = Membership.objects.filter(
            join_link=link,
            joined_by_link=True,
            status=Membership.Status.APPROVED,
            decided_at__isnull=False,
        )
        if link.reported_at is not None:
            people = people.filter(decided_at__gt=link.reported_at)
        people = list(people.select_related("user", "position").order_by("decided_at", "pk"))
        if not people:
            return 0
        link.reported_at = people[-1].decided_at
        link.save(update_fields=["reported_at", "updated_at"])

    company = link.company
    recipients = [
        person
        for person in members_with_perm(company, Perm.MEMBERS_APPROVE).select_related(
            "user", "company", "role"
        )
        if person.pk == link.created_by_id or scope.allows(scope.branch_ids(person), link.branch_id)
    ]
    inbox.notify(
        recipients,
        REPORT_KIND,
        title=lambda person: report_title(link, len(people)),
        body=lambda person: report_body(link, people),
        url=f"/c/{company.pk}/settings/invite?link={link.pk}",
        target=link,
        dedupe_key=f"{REPORT_KIND}:{link.pk}:{int(link.reported_at.timestamp())}",
    )
    transaction.on_commit(
        lambda: group_jobs.announce_members.delay([person.pk for person in people])
    )
    return len(people)


def report_title(link: JoinLink, count: int) -> str:
    return ngettext(
        "%(count)d person joined through «%(link)s»",
        "%(count)d people joined through «%(link)s»",
        count,
    ) % {"count": count, "link": link.name}


def report_body(link: JoinLink, people: list[Membership]) -> str:
    """Plain text (the inbox escapes it): the names, then how full the link is."""
    lines = [_person_line(person) for person in people[:LISTED]]
    if len(people) > LISTED:
        lines.append(_("and %(count)d more") % {"count": len(people) - LISTED})
    lines.append("")
    if link.max_uses is not None:
        lines.append(
            _("Joined: %(uses)d of %(places)d") % {"uses": link.uses, "places": link.max_uses}
        )
    else:
        lines.append(_("Joined in total: %(uses)d") % {"uses": link.uses})
    return "\n".join(lines)


def _person_line(person: Membership) -> str:
    name = person.full_name or str(person.user)
    return f"{name} · {person.position.name}" if person.position else name
