"""Read functions of the people lifecycle, for other apps, the dashboard and the AI tools.

A function returning branch-bound data takes the required keyword
`branch_ids: list[int] | None` (callers pass `apps.members.scope.branch_ids(member)`).
People are bound to the branches they work in.
"""

from collections import Counter
from datetime import date, timedelta

from django.db.models import Q, QuerySet

from apps.audit.models import AuditLog
from apps.hr import queries as hr_queries
from apps.lifecycle.models import DisciplinaryRecord, JobChange, Termination
from apps.members import scope
from apps.members.audit_actions import MemberAction
from apps.members.models import Membership
from apps.members.permissions import Perm


def records(company, *, branch_ids: list[int] | None) -> QuerySet[DisciplinaryRecord]:
    """Disciplinary records of people who work or worked here, inside the branch scope."""
    rows = DisciplinaryRecord.objects.for_company(company)
    if branch_ids is not None:
        rows = rows.filter(
            membership_id__in=hr_queries.people(
                company, branch_ids=branch_ids, statuses=hr_queries.EMPLOYED
            ).values("pk")
        )
    return rows


def active(rows: QuerySet[DisciplinaryRecord], day: date) -> QuerySet[DisciplinaryRecord]:
    """Records that still count on `day`: not withdrawn, not past their expiry."""
    return rows.exclude(status=DisciplinaryRecord.Status.WITHDRAWN).filter(
        Q(expires_on__isnull=True) | Q(expires_on__gte=day)
    )


def suspended(company, *, branch_ids: list[int] | None) -> list[dict]:
    """Who is suspended now, in scope: {member, until, since, reason, by} (the reason and the
    day it started from the suspension's audit row), longest first."""
    people = list(
        hr_queries.people(
            company, branch_ids=branch_ids, statuses=(Membership.Status.SUSPENDED,)
        ).select_related("user", "position", "home_branch")
    )
    latest = {}
    rows = AuditLog.objects.filter(
        company=company,
        action=MemberAction.SUSPENDED,
        target_type="membership",
        target_id__in=[person.pk for person in people],
    ).order_by("target_id", "-created_at", "-pk")
    for row in rows.select_related("actor"):
        latest.setdefault(row.target_id, row)
    # Whoever suspended them, by the name the company knows them by.
    actors = {
        member.user_id: str(member)
        for member in Membership.objects.filter(
            company=company, user_id__in=[row.actor_id for row in latest.values() if row.actor_id]
        )
    }
    found = []
    for person in people:
        row = latest.get(person.pk)
        by = None
        if row is not None and row.actor is not None:
            by = actors.get(row.actor_id) or row.actor.get_full_name()
        found.append(
            {
                "member": person,
                "until": person.suspended_until,
                "since": row.created_at if row else None,
                "reason": (row.details or {}).get("reason", "") if row else "",
                "by": by,
            }
        )
    return sorted(found, key=lambda item: (item["since"] is None, item["since"]))


def overview(company, *, branch_ids: list[int] | None, day: date, days: int) -> dict:
    """Counts and dates for the AI tool and the dashboard: records given in the last `days`
    days by kind and category, those still counting, unread and unanswered ones, fines
    proposed, and who is suspended. Never a record's text or anyone's explanation."""
    rows = records(company, branch_ids=branch_ids)
    recent = list(
        rows.filter(issued_on__gt=day - timedelta(days=days))
        .exclude(status=DisciplinaryRecord.Status.WITHDRAWN)
        .select_related("membership")
        .order_by("-issued_on", "-pk")
    )
    standing = active(rows, day)
    return {
        "recent": recent,
        "by_kind": dict(Counter(record.kind for record in recent)),
        "by_category": dict(Counter(record.category for record in recent)),
        "active": standing.count(),
        "unacknowledged": standing.filter(acknowledged_at__isnull=True).count(),
        "explained": standing.exclude(employee_response="").count(),
        "with_fine": sum(1 for record in recent if record.fine_id),
        "suspended": suspended(company, branch_ids=branch_ids),
    }


# Leaving and job changes ---------------------------------------------------------------------


def _people_in(company, branch_ids: list[int] | None):
    return hr_queries.people(company, branch_ids=branch_ids, statuses=hr_queries.EMPLOYED).values(
        "pk"
    )


def terminations(company, *, branch_ids: list[int] | None) -> QuerySet[Termination]:
    """Leavings of people who work or worked here, inside the branch scope."""
    rows = Termination.objects.for_company(company)
    if branch_ids is not None:
        rows = rows.filter(membership_id__in=_people_in(company, branch_ids))
    return rows


def job_changes(company, *, branch_ids: list[int] | None) -> QuerySet[JobChange]:
    """Job changes of people who work or worked here, inside the branch scope."""
    rows = JobChange.objects.for_company(company)
    if branch_ids is not None:
        rows = rows.filter(membership_id__in=_people_in(company, branch_ids))
    return rows


def resignations_for(member: Membership, limit: int | None = None) -> list[Termination]:
    """Requests to leave that `member` may answer (Needs you), oldest first."""
    from apps.lifecycle.terminations import may_manage

    if not member.has_perm(Perm.HR_TERMINATE):
        return []
    rows = (
        terminations(member.company, branch_ids=scope.branch_ids(member))
        .filter(status=Termination.Status.REQUESTED)
        .exclude(membership=member)
        .select_related("membership__role", "membership__user", "membership__company")
        .order_by("requested_at", "pk")
    )
    found = [row for row in rows if may_manage(member, row.membership, in_scope=True)]
    return found[:limit] if limit is not None else found


def changes_to_decide(member: Membership, limit: int | None = None) -> list[JobChange]:
    """Proposed job changes `member` may approve (Needs you), oldest first; their own
    proposals stay on the Job changes page."""
    from apps.lifecycle.job_changes import may_decide

    if not member.has_perm(Perm.HR_MANAGE):
        return []
    rows = (
        job_changes(member.company, branch_ids=scope.branch_ids(member))
        .filter(status=JobChange.Status.PROPOSED)
        .exclude(membership=member)
        .exclude(proposed_by=member)
        .select_related(
            "membership__role", "membership__user", "membership__company", "position", "branch"
        )
        .order_by("created_at", "pk")
    )
    found = [row for row in rows if may_decide(member, row, in_scope=True)]
    return found[:limit] if limit is not None else found


def career(membership: Membership) -> dict:
    """The person's working life here for their history: when they were hired, their job
    changes that took effect or are approved to come, and their leaving."""
    from apps.lifecycle import integrations

    person = ("membership__user", "membership__position", "membership__home_branch")
    changes = list(
        JobChange.objects.filter(
            membership=membership,
            status__in=(JobChange.Status.APPLIED, JobChange.Status.APPROVED),
        )
        .select_related(*person, "proposed_by__user", "decided_by__user")
        .order_by("-effective_on", "-pk")
    )
    leaving = list(
        Termination.objects.filter(
            membership=membership,
            status__in=(
                Termination.Status.REQUESTED,
                Termination.Status.AGREED,
                Termination.Status.COMPLETED,
            ),
        )
        .select_related(*person, "membership__company")
        .prefetch_related("handover")
        .order_by("-requested_at", "-pk")
    )
    return {
        "hired_on": integrations.hired_on(membership),
        "changes": changes,
        "terminations": leaving,
    }


def leaving_overview(company, *, branch_ids: list[int] | None, day: date) -> dict:
    """Counts and days for the AI tool: requests waiting, last days to come, who left in the
    last 90 days, job changes waiting and to come. Never a reason or a note."""
    rows = terminations(company, branch_ids=branch_ids).select_related("membership")
    upcoming = list(
        rows.filter(status=Termination.Status.AGREED, last_day__gte=day).order_by("last_day")
    )
    left = list(
        rows.filter(
            status=Termination.Status.COMPLETED, left_on__gte=day - timedelta(days=90)
        ).order_by("-left_on")
    )
    changes = job_changes(company, branch_ids=branch_ids).select_related("membership")
    return {
        "requested": rows.filter(status=Termination.Status.REQUESTED).count(),
        "upcoming": upcoming,
        "left": left,
        "changes_waiting": changes.filter(status=JobChange.Status.PROPOSED).count(),
        "changes_coming": list(
            changes.filter(status=JobChange.Status.APPROVED).order_by("effective_on")
        ),
    }
