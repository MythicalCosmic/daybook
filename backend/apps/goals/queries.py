"""Read functions of business goals, for the dashboard, other apps and the AI.

Who sees a goal: `reports.view`, the permission of its metric's numbers (a profit goal needs
`finance.view`, an average-check goal `sales.view` …) and the branch: a goal for one branch to
those who see that branch, a company-wide goal to those who see every branch (§2.6).

Contract for other packages:

    goals_for(company, *, branch_ids, statuses=("active",))   goals in scope (queryset)
    summary(goal, today=None)                                 the goal with its live evaluation
    progress.evaluate(goal, today)                            value, forecast, progress, state
"""

from datetime import date

from django.core.cache import cache
from django.db.models import QuerySet

from apps.goals import progress
from apps.goals.metrics import METRICS
from apps.goals.models import Goal, GoalPoint
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm

SERIES_POINTS = 26
LIVE_TTL = 300


def goals_for(company, *, branch_ids: list[int] | None, statuses=(Goal.Status.ACTIVE,)):
    """The company's goals with one of `statuses` within `branch_ids` (None: every goal; a
    list: only goals of those branches)."""
    rows = Goal.objects.for_company(company).filter(status__in=list(statuses))
    if branch_ids is not None:
        rows = rows.filter(branch_id__in=branch_ids)
    return rows.select_related("company", "branch", "owner")


def can_view(member: Membership) -> bool:
    return member.has_perm(Perm.REPORTS_VIEW)


def can_manage(member: Membership) -> bool:
    """Setting the company's goals is the owners' (and whoever may change company settings)."""
    return can_view(member) and member.has_perm(Perm.COMPANY_SETTINGS)


def can_see(member: Membership, goal: Goal) -> bool:
    if member.company_id != goal.company_id or not can_view(member):
        return False
    if not METRICS[goal.metric].visible_to(member):
        return False
    member_scope = scope.branch_ids(member)
    if member_scope is None:
        return True
    return goal.branch_id is not None and goal.branch_id in member_scope


def visible(member: Membership, statuses=None) -> QuerySet[Goal]:
    """The goals `member` may see (every status unless `statuses` narrows them)."""
    rows = Goal.objects.for_company(member.company).select_related("company", "branch", "owner")
    if statuses:
        rows = rows.filter(status__in=list(statuses))
    member_scope = scope.branch_ids(member)
    if member_scope is not None:
        rows = rows.filter(branch_id__in=member_scope)
    hidden = [key for key, metric in METRICS.items() if not metric.visible_to(member)]
    if hidden:
        rows = rows.exclude(metric__in=hidden)
    if not can_view(member):
        return rows.none()
    return rows


def live(goal: Goal, today: date) -> progress.Evaluation:
    """The goal's evaluation now, cached a few minutes (the metrics read other modules' data;
    a change to the goal itself changes the key)."""
    key = f"goals:live:{goal.pk}:{goal.updated_at.timestamp()}:{today.isoformat()}"
    found = cache.get(key)
    if found is None:
        found = progress.evaluate(goal, today)
        cache.set(key, found, LIVE_TTL)
    return found


def series(goal: Goal, now: progress.Evaluation | None = None, limit: int = SERIES_POINTS):
    """The weekly points (the latest `limit`), with today's evaluation as the last point."""
    points = list(GoalPoint.objects.filter(goal=goal).order_by("-on")[:limit])
    rows = [
        {"on": point.on, "value": point.value, "forecast": point.forecast, "state": point.state}
        for point in reversed(points)
    ]
    if now is not None and now.value is not None and (not rows or rows[-1]["on"] < now.as_of):
        rows.append(
            {"on": now.as_of, "value": now.value, "forecast": now.forecast, "state": now.state}
        )
    return rows


def summary(goal: Goal, today: date | None = None) -> dict:
    """The goal with its live evaluation (money and values as Decimal)."""
    from apps.goals.services import local_today

    today = today or local_today(goal.company)
    metric = METRICS[goal.metric]
    now = live(goal, today)
    return {
        "id": goal.pk,
        "title": goal.title,
        "metric": goal.metric,
        "unit": metric.unit,
        "better": metric.better,
        "kind": metric.kind,
        "target": goal.target,
        "starts_on": goal.starts_on,
        "ends_on": goal.ends_on,
        "branch": {"id": goal.branch_id, "name": goal.branch.name} if goal.branch_id else None,
        "owner": {"id": goal.owner_id, "name": str(goal.owner)} if goal.owner_id else None,
        "note": goal.note,
        "status": goal.status,
        "state": now.state,
        "value": now.value,
        "forecast": now.forecast,
        "baseline": now.baseline,
        "progress": now.progress,
        "days_left": now.days_left,
        "time_share": now.time_share,
        "available": metric.available(goal.company),
        "series": series(goal, now),
    }
