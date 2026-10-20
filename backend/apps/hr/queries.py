"""Read functions of HR records, for other apps, the dashboard and the AI tools.

A function returning branch-bound data takes the required keyword
`branch_ids: list[int] | None` (callers pass `apps.members.scope.branch_ids(member)`).
"""

from collections.abc import Iterable
from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.utils import timezone

from apps.audit.models import AuditLog
from apps.members.models import Membership


def employment_dates(company, member_ids: Iterable[int]) -> dict[int, tuple[date, date | None]]:
    """membership id -> (first day, last day or None while employed), in company-local dates.
    Payroll prorates pay with it. People who never joined (pending, rejected) are left out.

    This version reads the membership itself: the start is their latest approval (from the
    audit log, else the approval on the record), the end the last day recorded when they were
    last offboarded or blocked (else the day that happened). Package G replaces it with the
    profile's hire_date and terminated_on.
    """
    tz = ZoneInfo(company.timezone)
    members = (
        Membership.objects.for_company(company)
        .filter(pk__in=list(member_ids))
        .exclude(status__in=(Membership.Status.PENDING, Membership.Status.REJECTED))
    )
    ids = [member.pk for member in members]
    approved_at = _latest(company, ids, (AuditLog.Action.MEMBER_APPROVED,))
    # The latest departure only: someone who left, came back and was blocked ended on the block.
    departures = _latest_rows(
        company, ids, (AuditLog.Action.MEMBER_LEFT, AuditLog.Action.MEMBER_BLOCKED)
    )
    gone = (Membership.Status.LEFT, Membership.Status.BLOCKED)
    dates = {}
    for member in members:
        started = approved_at.get(member.pk)
        if started is None and member.status not in gone:
            started = member.decided_at
        started = started or member.onboarded_at or member.created_at
        end = None
        if member.status in gone:
            departure = departures.get(member.pk)
            end = _terminated_on(departure) or _local(
                departure.created_at if departure else member.decided_at or member.updated_at, tz
            )
        dates[member.pk] = (_local(started, tz), end)
    return dates


def _latest(company, ids: list[int], actions: tuple[str, ...]) -> dict[int, datetime]:
    return {pk: row.created_at for pk, row in _latest_rows(company, ids, actions).items()}


def _latest_rows(company, ids: list[int], actions: tuple[str, ...]) -> dict[int, AuditLog]:
    rows = AuditLog.objects.filter(
        company=company, action__in=actions, target_type="membership", target_id__in=ids
    ).order_by("target_id", "-created_at", "-pk")
    latest: dict[int, AuditLog] = {}
    for row in rows:
        latest.setdefault(row.target_id, row)
    return latest


def _terminated_on(row: AuditLog | None) -> date | None:
    value = row.details.get("terminated_on") if row is not None else None
    try:
        return date.fromisoformat(value) if value else None
    except TypeError, ValueError:
        return None


def _local(moment: datetime, tz: ZoneInfo) -> date:
    return timezone.localtime(moment, tz).date()
