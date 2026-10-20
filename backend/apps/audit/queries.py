"""Reading the audit log, for the dashboard's History tab, the log page, exports and the AI.

Every read goes through `events()`, which keeps a viewer to their company and drops rows
stamped with a permission they don't hold (`AuditLog.required_perm`: salaries, IDs). Callers
check the entry permission themselves (`audit.view`, or a record's history permission from
`apps.audit.registry.register_target`).
"""

from datetime import datetime

from django.db.models import Q, QuerySet

from apps.audit.models import AuditLog
from apps.members.models import Membership
from apps.members.permissions import Perm


def visible_to(member: Membership) -> Q:
    """Rows `member` may read: unstamped ones and those stamped with a permission they hold."""
    held = [perm.value for perm in Perm if member.has_perm(perm)]
    return Q(required_perm="") | Q(required_perm__in=held)


def events(
    member: Membership,
    *,
    target_type: str | None = None,
    target_id: int | None = None,
    actions: list[str] | None = None,
    actor_ids: list[int] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> QuerySet[AuditLog]:
    """The member's company's audit rows they may read, newest first, optionally narrowed to
    one record, some action codes, some actors (user ids) or a time window."""
    rows = AuditLog.objects.filter(company_id=member.company_id).filter(visible_to(member))
    if target_type is not None:
        rows = rows.filter(target_type=target_type)
    if target_id is not None:
        rows = rows.filter(target_id=target_id)
    if actions:
        rows = rows.filter(action__in=actions)
    if actor_ids:
        rows = rows.filter(actor_id__in=actor_ids)
    if since is not None:
        rows = rows.filter(created_at__gte=since)
    if until is not None:
        rows = rows.filter(created_at__lt=until)
    return rows.select_related("actor").order_by("-created_at", "-pk")
