"""Who reads what: the reading scope of a review (docs/PLAN-OWNER.md §3.15, §2.6).

A reader's scope is the domains they may see (their permissions and the company's modules)
and their branches (`members.scope.branch_ids`). Readers with the same scope share one review
per language; `scope_key` names the scope, so the dashboard only ever lists the reviews of the
caller's own scope and a manager never reads the owner's finance review.

    domains_for(member)   ["finance", "people", "sales"]
    of(member)            Scope(domains=(…), branch_ids=None | [ids], key="3f9a…")
    recipients(company)   the approved people the reviews go to (owners, or everyone with
                          reports.view), each once
"""

import hashlib
import json
from dataclasses import dataclass

from apps.briefings import conf
from apps.briefings.models import BriefingSettings
from apps.companies.models import Feature
from apps.members import scope as member_scope
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import members_with_perm

# The domains a review may speak about, each with what it needs: a module (None: always there)
# and a permission.
DOMAINS = {
    "finance": (Feature.FINANCE, Perm.FINANCE_VIEW),
    "sales": (Feature.SALES, Perm.SALES_VIEW),
    "stock": (Feature.STOCK, Perm.SALES_VIEW),
    "attendance": (Feature.ATTENDANCE, Perm.ATTENDANCE_VIEW),
    "people": (None, Perm.MEMBERS_VIEW),
    "insights": (None, Perm.REPORTS_VIEW),
}
# A review needs numbers: someone who sees only people and insights gets none.
DATA_DOMAINS = frozenset({"finance", "sales", "stock", "attendance"})


@dataclass(frozen=True)
class Scope:
    domains: tuple[str, ...]
    branch_ids: list[int] | None
    key: str

    @property
    def has_data(self) -> bool:
        return bool(DATA_DOMAINS & set(self.domains))


def domains_for(member: Membership) -> list[str]:
    """The domains `member` may read about, sorted."""
    company = member.company
    return sorted(
        domain
        for domain, (feature, perm) in DOMAINS.items()
        if (feature is None or company.has_feature(feature)) and member.has_perm(perm)
    )


def key_of(domains, branch_ids: list[int] | None) -> str:
    """sha256 of the sorted domains and branch ids (None: every branch), 16 hex digits."""
    shape = {"d": sorted(domains), "b": None if branch_ids is None else sorted(branch_ids)}
    digest = hashlib.sha256(json.dumps(shape, separators=(",", ":")).encode()).hexdigest()
    return digest[:16]


def of(member: Membership) -> Scope:
    domains = tuple(domains_for(member))
    branch_ids = member_scope.branch_ids(member)
    return Scope(domains, branch_ids, key_of(domains, branch_ids))


def recipients(company, settings: BriefingSettings | None = None) -> list[Membership]:
    """The approved people the reviews go to: the owners, or everyone with reports.view."""
    settings = settings or conf.get_settings(company)
    if settings.recipients == BriefingSettings.Recipients.REPORTS:
        people = members_with_perm(company, Perm.REPORTS_VIEW)
    else:
        people = Membership.objects.for_company(company).filter(
            status=Membership.Status.APPROVED, role__is_owner=True
        )
    return list(people.select_related("user", "role", "company").order_by("pk"))
