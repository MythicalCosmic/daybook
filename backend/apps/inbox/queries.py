"""Read functions of the inbox, for other apps, the dashboard and the AI tools."""

from django.db.models import Count, Q, QuerySet

from apps.inbox import registry
from apps.inbox.models import Notification, NotificationPreference
from apps.members.models import Membership

TABS = ("unread", "all")


def inbox(member: Membership, *, tab: str = "all") -> QuerySet[Notification]:
    """The member's in-app notifications, newest first, archived ones left out."""
    items = Notification.objects.filter(recipient=member, in_app=True, archived_at__isnull=True)
    if tab == "unread":
        items = items.filter(read_at__isnull=True)
    return items.select_related(*SERIALIZER_RELATIONS).order_by("-created_at", "-pk")


# What NotificationSerializer reads (a member without a name shows their user's name).
SERIALIZER_RELATIONS = ("actor__user", "acted_by")


def _unread(member: Membership) -> QuerySet[Notification]:
    return Notification.objects.filter(
        recipient=member, in_app=True, archived_at__isnull=True, read_at__isnull=True
    )


def unread_count(member: Membership) -> int:
    return _unread(member).count()


def unread_counts(member: Membership) -> dict[str, int]:
    """`{count, critical}`: unread in-app notifications, and how many of them are critical
    (the shell's toast and favicon badge)."""
    return _unread(member).aggregate(
        count=Count("pk"),
        critical=Count("pk", filter=Q(severity=Notification.Severity.CRITICAL)),
    )


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
