"""Business logic of exports: requesting one (audited) and who may export what."""

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.exports import build, tasks
from apps.exports.audit_actions import ExportAction
from apps.exports.models import Export
from apps.exports.registry import EXPORTERS, Exporter, get_exporter, may_export
from apps.members.models import Membership

EXPORTS_PULSE = build.EXPORTS_PULSE


def available(member: Membership) -> list[Exporter]:
    return [exporter for exporter in EXPORTERS if may_export(member, exporter)]


@transaction.atomic
def request_export(
    member: Membership,
    kind: str,
    *,
    format: str,
    params: dict | None = None,
    deliver_telegram: bool = False,
) -> Export:
    """Queue an export as `member`. Raises `PermissionDenied`, `DomainError`, or DRF's
    `ValidationError` from the exporter's params serializer."""
    exporter = get_exporter(kind)
    if exporter is None:
        raise DomainError(_("This export doesn't exist."))
    if not may_export(member, exporter):
        raise PermissionDenied(_("You don't have permission to export this."))
    if format not in exporter.formats:
        raise DomainError(_("This export can't be made in that format."))
    params = params or {}
    build.validated_params(exporter, params)
    export = Export.objects.create(
        company_id=member.company_id,
        kind=kind,
        format=format,
        params=params,
        requested_by=member,
        deliver_telegram=deliver_telegram,
        sensitive=exporter.sensitive,
    )
    audit.record(
        ExportAction.DATA_EXPORTED,
        company_id=member.company_id,
        actor=member.user,
        target=export,
        kind=kind,
        format=format,
        params=params,
        sensitive=exporter.sensitive,
        deliver_telegram=deliver_telegram,
    )
    transaction.on_commit(lambda: tasks.build_export.delay(export.pk))
    transaction.on_commit(lambda: pulse.bump(member.company_id, EXPORTS_PULSE))
    return export
