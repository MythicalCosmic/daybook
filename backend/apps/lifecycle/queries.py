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
from apps.lifecycle.models import DisciplinaryRecord
from apps.members.audit_actions import MemberAction
from apps.members.models import Membership


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
