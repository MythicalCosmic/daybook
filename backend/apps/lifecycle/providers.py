"""What the people lifecycle hands the shared registries: the evidence file check."""

from apps.hr import queries as hr_queries
from apps.lifecycle.models import DisciplinaryRecord
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm


def may_open_evidence(user, company_id: int, record_id: int) -> bool:
    """`lifecycle.evidence` files: for hr.discipline or hr.view, the person in their branch
    scope (the person themselves reads the record, not the evidence)."""
    record = DisciplinaryRecord.objects.filter(company_id=company_id, pk=record_id).first()
    viewer = (
        Membership.objects.filter(
            company_id=company_id, user=user, status=Membership.Status.APPROVED
        )
        .select_related("company", "role")
        .first()
    )
    if record is None or viewer is None:
        return False
    if not (viewer.has_perm(Perm.HR_DISCIPLINE) or viewer.has_perm(Perm.HR_VIEW)):
        return False
    return (
        hr_queries.person(viewer.company, record.membership_id, branch_ids=scope.branch_ids(viewer))
        is not None
    )
