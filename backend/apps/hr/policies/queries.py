"""Read functions of policies: who a policy applies to, where each person stands on it, and what
the dashboard and the mini app list.

A policy applies to the approved people in its positions (any position when it names none) who
work in one of its branches (any branch when it names none). Owners set the rules and are never
asked to sign them. Signatures are owed for the policy's `ack_version`, the newest published
version that asked everyone again; one `PolicyAcknowledgement` row per person who owes (or gave)
one, kept in step with who the policy applies to by `services.sync`.

Policies are company documents: everyone with `hr.view` sees the company-wide ones, and those of
a branch in their scope. The people behind the numbers are branch-scoped (§2.6).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.db.models import Count, Exists, F, OuterRef, Q, QuerySet
from django.utils.translation import gettext as _

from apps.console.registry import SearchHit
from apps.hr import queries as hr_queries
from apps.hr.models import Policy, PolicyAcknowledgement, PolicyCategory, PolicyVersion
from apps.members import scope
from apps.members.models import Membership

APPROVED = Membership.Status.APPROVED
# Where a person stands on the current request for signatures.
SIGNED, WAITING, LATE = "signed", "waiting", "late"
STATES = (SIGNED, WAITING, LATE)
# A policy that asks no signature is only to read.
TO_READ = "to_read"
MY_STATES = (WAITING, LATE, SIGNED, TO_READ)
# The lists of the policies page.
ACTIVE, DRAFTS, ARCHIVED = "active", "drafts", "archived"
VIEWS = (ACTIVE, DRAFTS, ARCHIVED)


def today(company, now: datetime | None = None) -> date:
    return hr_queries.today(company, now)


def due_from(policy: Policy, asked_on: date) -> date:
    """The last day to sign for someone asked on `asked_on`."""
    return asked_on + timedelta(days=policy.ack_within_days)


def _ids(related) -> list[int]:
    """The ids behind a many-to-many manager (prefetched or not)."""
    return [row.pk for row in related.all()]


# Who a policy applies to ---------------------------------------------------------------------


def audience_of(
    company_id: int, *, position_ids: Iterable[int], branch_ids: Iterable[int]
) -> QuerySet[Membership]:
    """The approved people (owners aside) in `position_ids` (any when empty) who work in one of
    `branch_ids` (any when empty)."""
    rows = Membership.objects.filter(company_id=company_id, status=APPROVED).exclude(
        role__is_owner=True
    )
    position_ids, branch_ids = list(position_ids), list(branch_ids)
    if position_ids:
        rows = rows.filter(position_id__in=position_ids)
    if branch_ids:
        rows = rows.filter(pk__in=Membership.objects.filter(branches__in=branch_ids).values("pk"))
    return rows


def audience(policy: Policy) -> QuerySet[Membership]:
    """Who `policy` applies to now."""
    return audience_of(
        policy.company_id, position_ids=_ids(policy.positions), branch_ids=_ids(policy.branches)
    )


def applies_to(policy: Policy, member: Membership, member_branches: set[int] | None = None) -> bool:
    """Whether the policy is one `member` reads (approved or suspended: they keep reading).
    Uses the prefetched positions and branches when there are some; `member_branches` saves
    asking for the member's own once per policy."""
    if member.company_id != policy.company_id or member.status not in hr_queries.CURRENT:
        return False
    positions = set(_ids(policy.positions))
    if positions and member.position_id not in positions:
        return False
    branches = set(_ids(policy.branches))
    if not branches:
        return True
    if member_branches is None:
        member_branches = set(_ids(member.branches))
    return bool(branches & member_branches)


def is_owner(member: Membership) -> bool:
    return member.role_id is not None and member.role.is_owner


# Which policies a viewer sees and may change -------------------------------------------------


def policies(company, *, branch_ids: list[int] | None) -> QuerySet[Policy]:
    """The policies a viewer with `branch_ids` sees: the company-wide ones, and those of one of
    their branches (all of them when None)."""
    rows = Policy.objects.for_company(company)
    if branch_ids is None:
        return rows
    links = Policy.branches.through.objects.filter(policy_id=OuterRef("pk"))
    return rows.filter(~Exists(links) | Exists(links.filter(branch_id__in=branch_ids)))


def covers(branch_ids: list[int] | None, policy_branch_ids: Iterable[int]) -> bool:
    """Whether a scope covers everything a policy reaches: every branch does; a branch-bound
    manager only a policy of their own branches (a company-wide one reaches others too)."""
    if branch_ids is None:
        return True
    wanted = set(policy_branch_ids)
    return bool(wanted) and wanted <= set(branch_ids)


def may_change(member: Membership, policy: Policy) -> bool:
    return covers(scope.branch_ids(member), _ids(policy.branches))


def draft_of(policy: Policy) -> PolicyVersion | None:
    return policy.versions.filter(published_at__isnull=True).first()


def view_filter(rows: QuerySet[Policy], view: str) -> QuerySet[Policy]:
    """Active: in force (published or not yet); drafts: never published; archived: retired."""
    if view == DRAFTS:
        return rows.filter(is_active=True, current_version__isnull=True)
    if view == ARCHIVED:
        return rows.filter(is_active=False)
    return rows.filter(is_active=True, current_version__isnull=False)


# Who owes a signature ------------------------------------------------------------------------


def requests(policy: Policy) -> QuerySet[PolicyAcknowledgement]:
    """The current request: the rows of the version that asked last, of the people the policy
    applies to now (someone who moved on keeps their signature in their own history)."""
    if not policy.requires_ack or policy.ack_version_id is None:
        return PolicyAcknowledgement.objects.none()
    return PolicyAcknowledgement.objects.filter(
        version_id=policy.ack_version_id, membership__in=audience(policy)
    )


def in_scope(
    rows: QuerySet[PolicyAcknowledgement], branch_ids: list[int] | None
) -> QuerySet[PolicyAcknowledgement]:
    """The rows of people who work in one of `branch_ids` (everyone's when None)."""
    if branch_ids is None:
        return rows
    return rows.filter(
        membership__in=Membership.objects.filter(branches__in=branch_ids).values("pk")
    )


def state(row: PolicyAcknowledgement, day: date) -> str:
    if row.acknowledged_at is not None:
        return SIGNED
    return LATE if day > row.due_on else WAITING


def with_state(rows: QuerySet[PolicyAcknowledgement], wanted: str | None, day: date):
    if wanted == SIGNED:
        return rows.filter(acknowledged_at__isnull=False)
    if wanted == WAITING:
        return rows.filter(acknowledged_at__isnull=True, due_on__gte=day)
    if wanted == LATE:
        return rows.filter(acknowledged_at__isnull=True, due_on__lt=day)
    return rows


@dataclass(frozen=True)
class Tally:
    total: int = 0
    signed: int = 0
    waiting: int = 0
    late: int = 0


def tally(policy: Policy, *, branch_ids: list[int] | None, day: date) -> Tally:
    """Signed, waiting and late on the current request, among the people in scope."""
    rows = in_scope(requests(policy), branch_ids)
    counts = rows.aggregate(
        total=Count("pk"),
        signed=Count("pk", filter=Q(acknowledged_at__isnull=False)),
        late=Count("pk", filter=Q(acknowledged_at__isnull=True, due_on__lt=day)),
    )
    return Tally(
        total=counts["total"],
        signed=counts["signed"],
        waiting=counts["total"] - counts["signed"] - counts["late"],
        late=counts["late"],
    )


def late_count(member: Membership) -> int:
    """The sidebar badge: people in the viewer's scope late with a signature."""
    company = member.company
    if not company.has_feature("hr"):
        return 0
    rows = PolicyAcknowledgement.objects.filter(
        version__company_id=company.pk,
        version_id=F("version__policy__ack_version_id"),
        version__policy__is_active=True,
        version__policy__requires_ack=True,
        membership__status=APPROVED,
        acknowledged_at__isnull=True,
        due_on__lt=today(company),
    )
    branch_ids = scope.branch_ids(member)
    if branch_ids is not None:
        visible = policies(company, branch_ids=branch_ids).values("pk")
        rows = in_scope(rows.filter(version__policy__in=visible), branch_ids)
    return rows.count()


# What a person reads -------------------------------------------------------------------------


@dataclass
class Standing:
    """Where one person stands on one policy."""

    policy: Policy
    state: str
    due_on: date | None = None
    asked_at: datetime | None = None
    signed_at: datetime | None = None
    signed_number: int | None = None


def standing(policy: Policy, member: Membership, row: PolicyAcknowledgement | None, day: date):
    if not policy.requires_ack or is_owner(member):
        return Standing(policy, TO_READ)
    if row is None:
        # Not asked yet (they joined minutes ago): owed from today.
        return Standing(policy, WAITING, due_on=due_from(policy, day))
    signed = row.signed_version.number if row.signed_version_id else None
    return Standing(
        policy,
        state(row, day),
        due_on=row.due_on,
        asked_at=row.asked_at,
        signed_at=row.acknowledged_at,
        signed_number=signed,
    )


ORDER = {LATE: 0, WAITING: 1, SIGNED: 2, TO_READ: 3}


def mine(member: Membership, day: date) -> list[Standing]:
    """The policies `member` reads in the app (active, published, applying to them) and where
    they stand: late first, then what waits by its deadline, then the rest by title."""
    candidates = (
        Policy.objects.for_company(member.company_id)
        .filter(is_active=True, current_version__isnull=False)
        .select_related("current_version__published_by", "ack_version")
        .prefetch_related("positions", "branches")
    )
    branches = set(_ids(member.branches))
    found = [policy for policy in candidates if applies_to(policy, member, branches)]
    rows = {
        row.version_id: row
        for row in PolicyAcknowledgement.objects.filter(
            membership=member,
            version_id__in=[policy.ack_version_id for policy in found if policy.ack_version_id],
        ).select_related("signed_version")
    }
    standings = [standing(policy, member, rows.get(policy.ack_version_id), day) for policy in found]
    standings.sort(
        key=lambda item: (
            ORDER[item.state],
            item.due_on or date.max,
            item.policy.title.casefold(),
        )
    )
    return standings


def my_policy(member: Membership, policy_id) -> Policy | None:
    """One policy the person reads, or None (another company's, a draft, archived, or not
    theirs)."""
    try:
        policy_id = int(policy_id)
    except TypeError, ValueError:
        return None
    policy = (
        Policy.objects.for_company(member.company_id)
        .filter(pk=policy_id, is_active=True, current_version__isnull=False)
        .select_related("current_version__published_by", "ack_version")
        .prefetch_related("positions", "branches")
        .first()
    )
    return policy if policy is not None and applies_to(policy, member) else None


def my_row(member: Membership, policy: Policy) -> PolicyAcknowledgement | None:
    if policy.ack_version_id is None:
        return None
    return (
        PolicyAcknowledgement.objects.filter(version_id=policy.ack_version_id, membership=member)
        .select_related("signed_version")
        .first()
    )


def to_sign_count(member: Membership, day: date) -> int:
    return sum(1 for item in mine(member, day) if item.state in (WAITING, LATE))


def history(member: Membership) -> list[PolicyAcknowledgement]:
    """Every signature the person gave, newest first (of earlier versions too)."""
    return list(
        PolicyAcknowledgement.objects.filter(membership=member, acknowledged_at__isnull=False)
        .select_related("version__policy", "signed_version")
        .order_by("-acknowledged_at", "-pk")
    )


# Search and the export -----------------------------------------------------------------------


def search(member: Membership, q: str, limit: int) -> list[SearchHit]:
    """Policies by title or by a word of their text (the command palette)."""
    words = q.split()[:4]
    if not words:
        return []
    rows = policies(member.company, branch_ids=scope.branch_ids(member)).select_related(
        "current_version"
    )
    for word in words:
        rows = rows.filter(Q(title__icontains=word) | Q(current_version__body_text__icontains=word))
    labels = dict(PolicyCategory.choices)
    hits = []
    for policy in rows.order_by("-is_active", "title")[:limit]:
        version = policy.current_version
        parts = [str(labels.get(policy.category, ""))]
        parts.append(
            _("Version %(number)d") % {"number": version.number} if version else _("Draft")
        )
        if not policy.is_active:
            parts.append(_("Archived"))
        hits.append(
            SearchHit(
                type="hr.policy",
                id=policy.pk,
                title=policy.title,
                subtitle=" · ".join(part for part in parts if part),
                url=f"/c/{policy.company_id}/hr/policies/{policy.pk}",
            )
        )
    return hits


def grid(policy: Policy, *, branch_ids: list[int] | None) -> QuerySet[PolicyAcknowledgement]:
    """The people grid's rows: the current request in scope, with what each row shows."""
    return (
        in_scope(requests(policy), branch_ids)
        .select_related(
            "membership__user",
            "membership__position",
            "membership__home_branch",
            "membership__company",
            "signed_version",
        )
        .order_by("membership__first_name", "membership__last_name", "pk")
    )


def earlier_signatures(policy: Policy, member_ids: Iterable[int]) -> dict[int, datetime]:
    """When each person last signed an earlier version of the policy (shown next to "waiting":
    they had signed the version before)."""
    rows = PolicyAcknowledgement.objects.filter(
        version__policy=policy, membership_id__in=list(member_ids), acknowledged_at__isnull=False
    )
    if policy.ack_version_id:
        rows = rows.exclude(version_id=policy.ack_version_id)
    found: dict[int, datetime] = {}
    for member_id, at in rows.values_list("membership_id", "acknowledged_at"):
        if member_id not in found or at > found[member_id]:
            found[member_id] = at
    return found


def tallies(rows: Iterable[Policy], *, branch_ids: list[int] | None, day: date) -> dict[int, Tally]:
    return {policy.pk: tally(policy, branch_ids=branch_ids, day=day) for policy in rows}
