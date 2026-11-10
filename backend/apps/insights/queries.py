"""Read functions of insights, for other apps, the dashboard and the AI tools.

A function returning branch-bound data takes the required keyword
`branch_ids: list[int] | None` (callers pass `apps.members.scope.branch_ids(member)`).

Contract for other packages:

    open(company, *, branch_ids, domain=None, severity=None)   live insights (a queryset)
    open_for(company, branch_ids)                              live insights as plain dicts,
                                                               words in the active language
                                                               (the briefings' facts, U)
    open_count(member)                                         the `insights.open` badge
"""

from django.db.models import Case, IntegerField, QuerySet, Value, When

from apps.insights import access, texts
from apps.insights.models import Insight
from apps.members import scope
from apps.members.models import Membership

SEVERITY_ORDER = Case(
    When(severity=Insight.Severity.CRITICAL, then=Value(0)),
    When(severity=Insight.Severity.WARNING, then=Value(1)),
    default=Value(2),
    output_field=IntegerField(),
)
# Within a severity, what an owner weighs first: cash, then a branch's profit, then the rest.
KIND_ORDER = Case(
    *(
        When(kind=kind, then=Value(index))
        for index, kind in enumerate(
            (
                Insight.Kind.CASH_LOW,
                Insight.Kind.BRANCH_MARGIN,
                Insight.Kind.OVERDUE_PAYABLES,
                Insight.Kind.EXPENSE_SPIKE,
                Insight.Kind.OVERDUE_RECEIVABLES,
                Insight.Kind.STAFF_COST,
                Insight.Kind.STOCK_BUILD,
            )
        )
    ),
    default=Value(9),
    output_field=IntegerField(),
)
STATUS_ORDER = Case(
    When(status=Insight.Status.OPEN, then=Value(0)),
    When(status=Insight.Status.ACKNOWLEDGED, then=Value(1)),
    default=Value(2),
    output_field=IntegerField(),
)


def ordered(rows: QuerySet[Insight]) -> QuerySet[Insight]:
    """Open before seen, urgent first, cash and profit before the rest, newest first."""
    return rows.annotate(_status=STATUS_ORDER, _severity=SEVERITY_ORDER, _kind=KIND_ORDER).order_by(
        "_status", "_severity", "_kind", "-detected_at", "-pk"
    )


# The plan's contract name (PLAN-OWNER §11.5, Package N); it shadows the builtin in this module.
def open(
    company, *, branch_ids, domain: str | None = None, severity: str | None = None
) -> QuerySet[Insight]:
    """Live insights (open or seen) of `company` inside `branch_ids`, urgent first."""
    rows = Insight.objects.filter(company=company, status__in=Insight.LIVE).filter(
        kind__in=access.kinds_on(company)
    )
    if domain:
        rows = rows.filter(domain=domain)
    if severity:
        rows = rows.filter(severity=severity)
    return ordered(scope.restrict(rows, branch_ids)).select_related("branch", "task")


def as_dict(insight: Insight) -> dict:
    """An insight as plain JSON (money as strings), its words in the active language."""
    words = texts.of(insight)
    return {
        "id": insight.pk,
        "kind": insight.kind,
        "domain": insight.domain,
        "severity": insight.severity,
        "status": insight.status,
        "branch": (
            {"id": insight.branch_id, "name": insight.branch.name} if insight.branch_id else None
        ),
        "subject": (
            {
                "type": insight.subject_type,
                "id": insight.subject_id,
                "label": insight.subject_label,
            }
            if insight.subject_type
            else None
        ),
        "title": words.title,
        "explanation": words.explanation,
        "suggested_action": words.action,
        "metrics": insight.metrics,
        "window": {
            "from": insight.window_start.isoformat() if insight.window_start else None,
            "to": insight.window_end.isoformat() if insight.window_end else None,
        },
        "detected_at": insight.detected_at.isoformat(),
        "last_seen_at": insight.last_seen_at.isoformat(),
        "acknowledged_at": insight.acknowledged_at.isoformat() if insight.acknowledged_at else None,
        "task": (
            {"id": insight.task_id, "title": insight.task.title, "status": insight.task.status}
            if insight.task_id
            else None
        ),
    }


def open_for(
    company, branch_ids: list[int] | None, *, domains: list[str] | None = None, limit: int = 20
) -> list[dict]:
    """The live insights of `company` inside `branch_ids` (None: every branch) as plain dicts,
    urgent first; `domains` narrows them to what a reader may see (finance, payroll…)."""
    rows = open(company, branch_ids=branch_ids)
    if domains is not None:
        rows = rows.filter(domain__in=domains)
    return [as_dict(insight) for insight in rows[:limit]]


def visible(member: Membership, filters: dict | None = None) -> QuerySet[Insight]:
    """What `member` may see, filtered by `status`, `kind`, `severity`, `domain` and `branch`
    (`status` "live" is open and seen; default: live)."""
    filters = filters or {}
    rows = access.visible(member)
    status = filters.get("status") or "live"
    if status == "live":
        rows = rows.filter(status__in=Insight.LIVE)
    elif status != "all":
        rows = rows.filter(status=status)
    for name in ("kind", "severity", "domain"):
        if filters.get(name):
            rows = rows.filter(**{name: filters[name]})
    if filters.get("branch"):
        rows = rows.filter(branch_id=filters["branch"])
    return ordered(rows).select_related("branch", "task")


def open_count(member: Membership) -> int:
    """Open (not yet seen) insights `member` may see."""
    return access.visible(member).filter(status=Insight.Status.OPEN).count()


def summary(member: Membership, *, limit: int = 6) -> dict:
    """The cockpit's insights: counts and the first `limit` live ones."""
    rows = visible(member)
    live = list(rows[:limit])
    counts = {
        "live": rows.count(),
        "open": access.visible(member).filter(status=Insight.Status.OPEN).count(),
        "critical": access.visible(member)
        .filter(status__in=Insight.LIVE, severity=Insight.Severity.CRITICAL)
        .count(),
    }
    return {**counts, "items": [as_dict(insight) for insight in live]}
