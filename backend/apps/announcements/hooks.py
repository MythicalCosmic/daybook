"""Registrations of announcements with the shared registries. Imported by AppConfig.ready()."""

from datetime import datetime

from django.utils.translation import gettext as _

from apps.announcements import queries
from apps.announcements.audit_actions import AnnouncementAction
from apps.announcements.models import Announcement
from apps.audit import registry as audit_registry
from apps.console import registry
from apps.console.registry import SearchHit, StreamItem
from apps.members.models import Membership
from apps.members.permissions import Perm


def _search(member: Membership, q: str, limit: int) -> list[SearchHit]:
    return [
        SearchHit(
            type="announcements.announcement",
            id=row.pk,
            title=queries.title(row),
            subtitle=_("%(status)s · %(read)d of %(total)d read")
            % {
                "status": row.get_status_display(),
                "read": row.read_count,
                "total": row.recipients_count,
            },
            url=f"announcements/{row.pk}",
        )
        for row in queries.search(member, q, limit)
    ]


def _stream(member: Membership, since: datetime | None, limit: int) -> list[StreamItem]:
    rows = queries.for_console(member).filter(status=Announcement.Status.SENT)
    if since is not None:
        rows = rows.filter(sent_at__gt=since)
    return [
        StreamItem(
            at=row.sent_at,
            kind="announcements.sent",
            actor={"id": row.author.pk, "name": str(row.author)} if row.author else None,
            title=_("Announcement: %(title)s · %(read)d of %(total)d read")
            % {
                "title": queries.title(row, 60),
                "read": row.read_count,
                "total": row.recipients_count,
            },
            url=f"announcements/{row.pk}",
        )
        for row in rows.order_by("-sent_at")[:limit]
        if row.sent_at is not None
    ]


def _history_check(member: Membership, target_id: int) -> bool:
    return queries.for_console(member).filter(pk=target_id).exists()


audit_registry.register(AnnouncementAction)
audit_registry.register_target("announcement", Perm.ANNOUNCE, check=_history_check)

registry.register_search("announcements.announcement", perm=Perm.ANNOUNCE, search=_search)
registry.register_stream("announcements.sent", perm=Perm.ANNOUNCE, fetch=_stream)
registry.register_pulse("announcements.announcements", perm=Perm.ANNOUNCE, count=None)
