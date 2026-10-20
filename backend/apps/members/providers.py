"""What memberships hand to the shared registries (registered in hooks.py): join requests in
Needs you and their inbox buttons, palette search, the activity stream, the brief section,
the offboarding step, the directory export, the setup step and copying setup."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext

from apps.audit.models import AuditLog
from apps.companies.models import Branch, Company
from apps.console.registry import OffboardStep, QueueAction, QueueItem, SearchHit, StreamItem
from apps.core.exceptions import DomainError
from apps.members import queries, scope, services
from apps.members.models import AccessRole, Membership, Position

# Needs you ------------------------------------------------------------------------------


def queue_count(member: Membership) -> int:
    return queries.pending_count(member.company)


def approve_defaults(viewer: Membership) -> tuple[dict, str] | None:
    """What a one-click Approve in Needs you gives, as (request body, the branch's name) for
    `viewer`: nothing to choose with one branch; their home branch with several (when they
    may give it); None when they have to pick in the Requests page."""
    branches = list(
        Branch.objects.filter(company_id=viewer.company_id, is_active=True).order_by("order", "pk")
    )
    if len(branches) <= 1:
        return {}, ""
    home = next((b for b in branches if b.pk == viewer.home_branch_id), None)
    allowed = scope.branch_ids(viewer)
    if home is None or (allowed is not None and home.pk not in allowed):
        return None
    return {"branch_ids": [home.pk], "home_branch_id": home.pk}, home.name


def queue_items(member: Membership, limit: int) -> list[QueueItem]:
    rows = queries.join_requests(member.company).filter(onboarded_at__isnull=False)[:limit]
    defaults = approve_defaults(member)
    items = []
    for request in rows:
        parts = [request.position.name if request.position else None, request.user.phone]
        actions = []
        if defaults is not None:
            body, branch = defaults
            label = _("Approve · %(branch)s") % {"branch": branch} if branch else _("Approve")
            actions.append(
                QueueAction(
                    "approve",
                    label,
                    "primary",
                    "POST",
                    f"join-requests/{request.pk}/approve/",
                    body,
                )
            )
        actions.append(
            QueueAction(
                "reject", _("Reject"), "danger", "POST", f"join-requests/{request.pk}/reject/"
            )
        )
        items.append(
            QueueItem(
                kind="members.join",
                id=request.pk,
                title=_("%(name)s wants to join") % {"name": request},
                subtitle=" · ".join(part for part in parts if part),
                created_at=request.onboarded_at or request.created_at,
                url=f"people/requests?request={request.pk}",
                actions=tuple(actions),
            )
        )
    return items


def _target(notification) -> Membership:
    membership = Membership.objects.filter(
        pk=notification.target_id, company_id=notification.company_id
    ).first()
    if membership is None:
        raise DomainError(_("This request no longer exists."))
    return membership


def approve_from_inbox(notification, by: Membership, reason: str) -> str:
    """The generic Approve button (the bot answers its own first; this serves other paths)."""
    defaults = approve_defaults(by)
    if defaults is None:
        raise DomainError(_("Choose their branches in the dashboard's Requests page."))
    body, _branch = defaults
    branch_ids = body.get("branch_ids") or []
    branches = list(Branch.objects.filter(pk__in=branch_ids))
    services.approve_request(
        _target(notification),
        by=by,
        branches=branches or None,
        home_branch=branches[0] if branches else None,
    )
    return _("Approved")


def reject_from_inbox(notification, by: Membership, reason: str) -> str:
    services.reject_request(_target(notification), by=by, reason=reason)
    return _("Rejected")


# Search, stream, brief ----------------------------------------------------------------


def search(member: Membership, q: str, limit: int) -> list[SearchHit]:
    people = queries.directory(
        member.company, branch_ids=scope.branch_ids(member), q=q, include=member
    ).order_by("first_name", "last_name")[:limit]
    return [
        SearchHit(
            type="members.person",
            id=person.pk,
            title=str(person),
            subtitle=" · ".join(
                part
                for part in (
                    person.position.name if person.position else None,
                    person.home_branch.name if person.home_branch else None,
                )
                if part
            ),
            url=f"people/{person.pk}",
        )
        for person in people
    ]


def stream_joined(member: Membership, since: datetime | None, limit: int) -> list[StreamItem]:
    """ "Ali joined the team" for approvals of people the viewer can see."""
    from apps.audit import queries as audit_queries

    rows = audit_queries.events(
        member,
        target_type="membership",
        actions=[AuditLog.Action.MEMBER_APPROVED],
        since=since or timezone.now() - timedelta(days=30),
    )[: limit * 2]
    ids = [row.target_id for row in rows]
    visible = set(
        queries.directory(
            member.company, branch_ids=scope.branch_ids(member), status="current", include=member
        )
        .filter(pk__in=ids)
        .values_list("pk", flat=True)
    )
    items = []
    for row in rows:
        if row.target_id not in visible:
            continue
        items.append(
            StreamItem(
                at=row.created_at,
                kind="members.joined",
                actor=None,
                title=_("%(name)s joined the team") % {"name": row.target},
                url=f"people/{row.target_id}",
            )
        )
    return items[:limit]


def brief_section(company: Company, day: date, now: datetime, branch_ids) -> dict | None:
    """People today: join requests waiting, who joined this week, who is off and suspended."""
    from apps.timeoff.models import TimeOff

    people = queries.directory(company, branch_ids=branch_ids, status="current")
    ids = list(people.values_list("pk", flat=True))
    off = (
        TimeOff.objects.filter(
            company=company,
            status=TimeOff.Status.APPROVED,
            first_day__lte=day,
            last_day__gte=day,
            membership_id__in=ids,
        )
        .select_related("membership")
        .order_by("membership__first_name")
    )
    week_ago = now - timedelta(days=7)
    joined = people.filter(decided_at__gte=week_ago, status=Membership.Status.APPROVED)
    data = {
        "pending_requests": queries.pending_count(company) if branch_ids is None else 0,
        "joined_this_week": [{"id": p.pk, "name": str(p)} for p in joined[:10]],
        "off_today": [{"id": t.membership_id, "name": str(t.membership)} for t in off[:20]],
        "suspended": people.filter(status=Membership.Status.SUSPENDED).count(),
        "headcount": people.filter(status=Membership.Status.APPROVED).count(),
    }
    quiet = not (
        data["pending_requests"]
        or data["joined_this_week"]
        or data["off_today"]
        or data["suspended"]
    )
    return None if quiet else data


# Offboarding --------------------------------------------------------------------------


def offboard_step(membership: Membership) -> OffboardStep:
    """What ends with the person here: access, their work, routines."""
    from apps.tasks.models import Task

    lines = [_("Their access to the bot, the app and the dashboard ends at once.")]
    open_tasks = Task.objects.filter(assignee=membership, status__in=Task.OPEN_STATUSES)
    given = open_tasks.filter(kind=Task.Kind.ASSIGNED).exclude(created_by=membership)
    returned = given.filter(created_by__status=Membership.Status.APPROVED).count()
    cancelled = open_tasks.count() - returned
    if returned:
        lines.append(
            ngettext(
                "%(count)d open task goes back to the person who gave it.",
                "%(count)d open tasks go back to the people who gave them.",
                returned,
            )
            % {"count": returned}
        )
    if cancelled:
        lines.append(
            ngettext(
                "%(count)d daily or personal task is cancelled.",
                "%(count)d daily and personal tasks are cancelled.",
                cancelled,
            )
            % {"count": cancelled}
        )
    routines = membership.task_templates.filter(is_active=True, personal=False).count()
    if routines:
        lines.append(
            ngettext(
                "They are taken off %(count)d routine.",
                "They are taken off %(count)d routines.",
                routines,
            )
            % {"count": routines}
        )
    blockers = []
    if membership.role is not None and membership.role.is_owner:
        owners = Membership.objects.filter(
            company_id=membership.company_id,
            status=Membership.Status.APPROVED,
            role__is_owner=True,
        ).exclude(pk=membership.pk)
        if not owners.exists():
            blockers.append(
                _("This is the company's only owner. Make someone else an owner first.")
            )
    return OffboardStep(lines=lines, blockers=blockers, fields=[], defaults={})


# Export -------------------------------------------------------------------------------


EXPORT_COLUMNS = [
    ("name", gettext_lazy("Name")),
    ("position", gettext_lazy("Position")),
    ("role", gettext_lazy("Role")),
    ("home_branch", gettext_lazy("Home branch")),
    ("branches", gettext_lazy("Branches")),
    ("phone", gettext_lazy("Phone")),
    ("telegram", gettext_lazy("Telegram")),
    ("status", gettext_lazy("Status")),
    ("joined_on", gettext_lazy("Joined"), "date"),
    ("on_time_30d", gettext_lazy("On time, 30 days (%)"), "number"),
]


def export_rows(member: Membership, params: dict):
    people = queries.directory(
        member.company,
        branch_ids=scope.branch_ids(member),
        status=params.get("status") or "current",
        q=params.get("q") or None,
        include=member,
    ).order_by("first_name", "last_name")
    people = list(people)
    scores = queries.work_scores(member.company, [p.pk for p in people], timezone.now())
    for person in people:
        joined = person.decided_at or person.created_at
        yield {
            "name": str(person),
            "position": person.position.name if person.position else "",
            "role": person.role.name if person.role else "",
            "home_branch": person.home_branch.name if person.home_branch else "",
            "branches": ", ".join(sorted(b.name for b in person.branches.all())),
            "phone": person.user.phone or "",
            "telegram": f"@{person.user.telegram_username}"
            if person.user.telegram_username
            else "",
            "status": person.get_status_display(),
            "joined_on": timezone.localtime(joined).date() if joined else None,
            "on_time_30d": scores.get(person.pk, {}).get("on_time_30d"),
        }


# Setup and copying setup ----------------------------------------------------------------


def positions_done(company: Company) -> bool:
    return Position.objects.for_company(company).filter(is_active=True).count() >= 2


def copy_positions(source: Company, target: Company, by: Membership) -> int:
    taken = {
        name.lower() for name in Position.objects.for_company(target).values_list("name", flat=True)
    }
    order = Position.objects.for_company(target).count()
    created = 0
    for position in Position.objects.for_company(source).filter(is_active=True).order_by("order"):
        if position.name.lower() in taken:
            continue
        Position.objects.create(company=target, name=position.name, order=order + created)
        created += 1
    return created


def copy_roles(source: Company, target: Company, by: Membership) -> int:
    """Roles other than the Owner role, by name; permissions `by` doesn't hold are left out."""
    taken = {
        name.lower()
        for name in AccessRole.objects.for_company(target).values_list("name", flat=True)
    }
    created = 0
    for role in AccessRole.objects.for_company(source).filter(is_owner=False).order_by("name"):
        if role.name.lower() in taken:
            continue
        permissions = [code for code in role.permissions if services.may_grant(by, [code])]
        AccessRole.objects.create(company=target, name=role.name, permissions=permissions)
        created += 1
    return created


# Audit history -----------------------------------------------------------------------


def history_check(member: Membership, target_id: int) -> bool:
    person = Membership.objects.filter(company_id=member.company_id, pk=target_id).first()
    return person is not None and queries.in_scope(member, person)


def role_history_check(member: Membership, target_id: int) -> bool:
    return AccessRole.objects.filter(company_id=member.company_id, pk=target_id).exists()


def position_history_check(member: Membership, target_id: int) -> bool:
    return Position.objects.filter(company_id=member.company_id, pk=target_id).exists()
