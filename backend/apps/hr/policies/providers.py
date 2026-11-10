"""What policies give the shared registries: who may open a version's file, and who may read a
policy's history."""

from apps.hr.models import Policy, PolicyVersion
from apps.hr.policies import queries
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm


def _viewer(user, company_id: int) -> Membership | None:
    return (
        Membership.objects.filter(company_id=company_id, user=user)
        .select_related("company", "role")
        .first()
    )


def may_open_file(user, company_id: int, version_id: int) -> bool:
    """`hr.policy` files (checked when the signed link is used): HR in scope opens any version's
    (drafts too); a person the policy applies to, the file of the version in force (also while
    their access is paused: they keep reading)."""
    version = (
        PolicyVersion.objects.for_company(company_id)
        .filter(pk=version_id)
        .select_related("policy")
        .first()
    )
    viewer = _viewer(user, company_id)
    if version is None or viewer is None:
        return False
    policy = version.policy
    if viewer.status == Membership.Status.APPROVED and viewer.has_perm(Perm.HR_VIEW):
        visible = queries.policies(viewer.company, branch_ids=scope.branch_ids(viewer))
        if visible.filter(pk=policy.pk).exists():
            return True
    return (
        policy.is_active
        and policy.current_version_id == version.pk
        and queries.applies_to(policy, viewer)
    )


def may_see_history(member: Membership, policy_id: int) -> bool:
    """A policy's History tab: `hr.view` holders who see the policy."""
    return (
        queries.policies(member.company, branch_ids=scope.branch_ids(member))
        .filter(pk=policy_id)
        .exists()
    )


def policy_link(policy: Policy) -> str:
    return f"/c/{policy.company_id}/hr/policies/{policy.pk}"
