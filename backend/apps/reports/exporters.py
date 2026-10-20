"""Rows of the `reports.team` exporter: the team report for the request's range and grouping,
in the requester's branch scope."""

from django.utils import timezone

from apps.members.models import Membership
from apps.members.scope import branch_ids
from apps.reports import kpis
from apps.reports.periods import RangeError, parse_range

COLUMNS = (
    "total",
    "on_time",
    "late",
    "missed",
    "on_time_percent",
    "avg_delay_minutes",
    "late_now",
    "reminders",
)


def team_rows(member: Membership, params: dict):
    company = member.company
    now = timezone.now()
    flat = {
        key: (value[0] if isinstance(value, list) and value else value)
        for key, value in (params or {}).items()
    }
    try:
        period = parse_range(flat, company, now)
    except RangeError:
        period = parse_range({}, company, now)
    group_by = flat.get("group_by") or "member"
    if group_by not in kpis.GROUPS:
        group_by = "member"
    rows = kpis.team_grouped(
        company, period.start, period.end, now, group_by, branch_ids=branch_ids(member)
    )
    for row in rows:
        data = row.score.as_dict()
        yield {
            "label": row.label,
            "position": row.extra.get("position") or "",
            **{key: data[key] for key in COLUMNS},
        }
