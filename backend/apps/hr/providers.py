"""What HR hands the shared registries: file checks, badge counts, inbox actions."""

from apps.hr import services
from apps.hr.models import EmployeeDocument
from apps.members.models import Membership


def may_open_document(user, company_id: int, document_id: int) -> bool:
    """`hr.document` files: the person's own (when shown to them, also while suspended), or
    anyone's for `hr.view` in scope (`hr.sensitive` for an ID). Every opening is audited."""
    document = (
        EmployeeDocument.objects.filter(company_id=company_id, pk=document_id)
        .select_related("membership__company")
        .first()
    )
    viewer = (
        Membership.objects.filter(company_id=company_id, user=user)
        .select_related("company", "role")
        .first()
    )
    if document is None or viewer is None:
        return False
    own = document.membership_id == viewer.pk
    if not own and viewer.status != Membership.Status.APPROVED:
        return False
    if not services.may_see_document(viewer, document):
        return False
    services.document_opened(document, user)
    return True
