"""Who may download an export file: re-checked every time a signed link is used."""

from apps.accounts.models import User
from apps.exports.models import Export
from apps.exports.registry import get_exporter, may_export
from apps.members.models import Membership


def can_download(user: User, company_id: int, object_id) -> bool:
    """Only the person who asked for it, while they still may run that export."""
    try:
        export_id = int(object_id)
    except TypeError, ValueError:
        return False
    export = (
        Export.objects.select_related("requested_by__role", "requested_by__company")
        .filter(pk=export_id, company_id=company_id, status=Export.Status.READY)
        .first()
    )
    if export is None or export.requested_by.user_id != user.pk:
        return False
    member = export.requested_by
    exporter = get_exporter(export.kind)
    return (
        member.status == Membership.Status.APPROVED
        and member.company.is_active
        and exporter is not None
        and may_export(member, exporter)
    )
