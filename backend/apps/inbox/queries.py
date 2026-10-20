"""Read functions of the inbox, for other apps, the dashboard and the AI tools."""

from django.db.models import QuerySet

from apps.inbox import registry
from apps.inbox.models import Notification, NotificationPreference
from apps.members.models import Membership

TABS = ("unread", "all")


def inbox(member: Membership, *, tab: str = "all") -> QuerySet[Notification]:
    """The member's in-app notifications, newest first, archived ones left out."""
    items = Notification.objects.filter(recipient=member, in_app=True, archived_at__isnull=True)
    if tab == "unread":
        items = items.filter(read_at__isnull=True)
    return items.select_related("actor", "acted_by").order_by("-created_at", "-pk")


def unread_count(member: Membership) -> int:
    return Notification.objects.filter(
        recipient=member, in_app=True, archived_at__isnull=True, read_at__isnull=True
    ).count()


def preferences(member: Membership) -> list[dict]:
    """Every registered kind with the member's choice (or the kind's defaults)."""
    chosen = {
        preference.kind: preference
        for preference in NotificationPreference.objects.filter(membership=member)
    }
    rows = []
    for kind in sorted(registry.KINDS, key=lambda k: k.key):
        preference = chosen.get(kind.key)
        rows.append(
            {
                "kind": kind.key,
                "label": str(kind.label),
                "audience": kind.audience,
                "severity": kind.severity,
                # Kinds that live in Needs you have no in-app row to switch off.
                "in_app_available": kind.queue_kind is None,
                "in_app": kind.queue_kind is None and (preference is None or preference.in_app),
                "telegram": kind.default_telegram if preference is None else preference.telegram,
            }
        )
    return rows
