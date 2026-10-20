"""Branch scope: which branches' data a member may see (docs/PLAN-OWNER.md §2.6).

`branch_ids(member)` is `None` for every branch (an owner role, or `branches.all`), otherwise
the ids of the member's branches, **which may be empty: an empty list means no branch-bound
data at all**. Rows with no branch (company-level accounts, company-wide tasks, people without
branches) are visible only when the scope is `None`. A person always sees their own tasks,
records and requests; callers add that themselves. An id outside the scope answers 404, like
another company's id.

Query functions that return branch-bound data take `branch_ids: list[int] | None` as a required
keyword with no default, so "all branches" is never an accident:

    shifts(company, start, end, branch_ids=scope.branch_ids(member))
"""

from django.db.models import QuerySet

from apps.members.models import Membership
from apps.members.permissions import Perm

BranchScope = list[int] | None


def branch_ids(membership: Membership) -> BranchScope:
    if membership.has_perm(Perm.BRANCHES_ALL):  # owners hold every permission
        return None
    if membership.status != Membership.Status.APPROVED:
        return []
    prefetched = getattr(membership, "_prefetched_objects_cache", {}).get("branches")
    if prefetched is not None:
        return sorted(branch.pk for branch in prefetched)
    return list(membership.branches.order_by("pk").values_list("pk", flat=True))


def allows(scope: BranchScope, branch_id: int | None) -> bool:
    """Whether a row bound to `branch_id` (None: no branch) is inside `scope`."""
    if scope is None:
        return True
    return branch_id is not None and branch_id in scope


def restrict(queryset: QuerySet, scope: BranchScope, *, field: str = "branch") -> QuerySet:
    """Rows of `queryset` inside `scope`. `field` is the path to the branch: `"branch"`,
    `"assignee__home_branch"`, or a many-to-many such as `"branches"` for people, where any
    shared branch counts. Rows without a branch are left out unless the scope is None."""
    if scope is None:
        return queryset
    rows = queryset.filter(**{f"{field}__in": scope})
    return rows.distinct() if _spans_many(queryset.model, field) else rows


def _spans_many(model, path: str) -> bool:
    for name in path.split("__"):
        field = model._meta.get_field(name)
        if field.many_to_many or field.one_to_many:
            return True
        model = field.related_model
    return False
