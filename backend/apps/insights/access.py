"""Who sees which insight (docs/PLAN-OWNER.md §4.13, §2.6): `reports.view` and the permission of
the insight's domain (finance numbers need `finance.view`, staff costs `payroll.view`), inside
the branch scope (an insight without a branch only for those who see every branch), while the
module its rule reads is switched on."""

from django.db.models import QuerySet

from apps.insights import detectors
from apps.insights.models import Insight
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm

BASE = Perm.REPORTS_VIEW
Domain = Insight.Domain
DOMAIN_PERMS = {
    Domain.FINANCE: Perm.FINANCE_VIEW,
    Domain.SALES: Perm.SALES_VIEW,
    Domain.PAYROLL: Perm.PAYROLL_VIEW,
    Domain.HR: Perm.HR_VIEW,
    Domain.PEOPLE: Perm.MEMBERS_VIEW,
    Domain.TASKS: Perm.TASKS_VIEW_ALL,
}


def domains_for(member: Membership) -> list[str]:
    """The domains whose insights `member` may read."""
    if not member.has_perm(BASE):
        return []
    return [str(domain) for domain, perm in DOMAIN_PERMS.items() if member.has_perm(perm)]


def kinds_on(company) -> list[str]:
    """Kinds whose rule's module is on (a module switched off hides what it found)."""
    return [
        kind
        for kind, rule in detectors.DETECTORS.items()
        if rule.feature is None or company.has_feature(rule.feature)
    ]


def restrict(rows: QuerySet[Insight], member: Membership) -> QuerySet[Insight]:
    """`rows` narrowed to what `member` may see."""
    domains = domains_for(member)
    if not domains:
        return rows.none()
    rows = rows.filter(
        company_id=member.company_id, domain__in=domains, kind__in=kinds_on(member.company)
    )
    return scope.restrict(rows, scope.branch_ids(member))


def visible(member: Membership) -> QuerySet[Insight]:
    return restrict(Insight.objects.all(), member)


def can_see(member: Membership, insight: Insight) -> bool:
    return (
        insight.company_id == member.company_id
        and insight.domain in domains_for(member)
        and insight.kind in kinds_on(member.company)
        and scope.allows(scope.branch_ids(member), insight.branch_id)
    )


def recipients(insight: Insight) -> list[Membership]:
    """Approved members who may see `insight`: who hears about an urgent one."""
    from apps.members.queries import members_with_perm

    people = (
        members_with_perm(insight.company, BASE)
        .select_related("user", "role", "company")
        .prefetch_related("branches")
    )
    return [person for person in people if can_see(person, insight)]
