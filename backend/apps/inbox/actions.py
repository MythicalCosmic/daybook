"""Action handlers of the inbox's own notification kinds."""

from apps.inbox.models import Notification
from apps.members.models import Membership


def got_it(notification: Notification, by: Membership, reason: str) -> str | None:
    """Acknowledge a message: acting on it is all there is to do."""
    return None
