"""Demo data of the inbox: a few messages, so the dashboard's Inbox has something to show."""

from django.utils import timezone

from apps.inbox.models import Notification
from apps.inbox.services import NotificationAction, notify

GOT_IT = NotificationAction("got_it", "Got it", "primary")


def seed(company, people, now) -> None:
    """Add demo rows to `company`. `people` maps owner, manager, worker, madina, jasur
    and nigora to their memberships."""
    leaders = [people["owner"], people["manager"]]
    notify(
        leaders,
        "inbox.system",
        title="Welcome to your dashboard",
        body="Everything your team does in Telegram shows up here: tasks, people, "
        "approvals and reports.",
        url=f"/c/{company.pk}/",
        actions=[GOT_IT],
        dedupe_key="demo:welcome",
    )
    notify(
        [people["owner"]],
        "inbox.system",
        title="Invite your team",
        body="Share the invite link so staff can join from the employee bot.",
        url=f"/c/{company.pk}/settings/invite",
        severity="warning",
        dedupe_key="demo:invite",
    )
    [tip] = notify(
        [people["owner"]],
        "inbox.system",
        title="Press Ctrl+K to find anything",
        body="Search people, tasks and records from any page.",
        dedupe_key="demo:search",
    ) or [None]
    if tip is not None:
        Notification.objects.filter(pk=tip.pk).update(read_at=now or timezone.now())
