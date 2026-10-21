"""Demo data of the inbox: a few messages from the product, so the dashboard's Inbox has
something to show, each in its reader's language. After every other demo, `finish` settles the
inbox: what the others sent more than a day and a half ago has been read by now."""

from datetime import timedelta

from django.db.models import F
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.inbox.models import Notification
from apps.inbox.services import NotificationAction, notify

GOT_IT = NotificationAction("got_it", _("Got it"), "primary")


def seed(company, people, now) -> None:
    """Add demo rows to `company`. `people` maps owner, manager, worker, madina, jasur
    and nigora to their memberships."""
    leaders = [people["owner"], people["manager"]]
    notify(
        leaders,
        "inbox.system",
        title=_("Welcome to your dashboard"),
        body=_(
            "Everything your team does in Telegram shows up here: tasks, people, approvals "
            "and reports."
        ),
        url=f"/c/{company.pk}/",
        actions=[GOT_IT],
        dedupe_key="demo:welcome",
    )
    notify(
        [people["owner"]],
        "inbox.system",
        title=_("Invite your team"),
        body=_("Share the invite link so staff can join from the employee bot."),
        url=f"/c/{company.pk}/settings/invite",
        severity="warning",
        dedupe_key="demo:invite",
    )
    [tip] = notify(
        [people["owner"]],
        "inbox.system",
        title=_("Press Ctrl+K to find anything"),
        body=_("Search people, tasks and records from any page."),
        dedupe_key="demo:search",
    ) or [None]
    if tip is not None:
        Notification.objects.filter(pk=tip.pk).update(read_at=now or timezone.now())


def finish(company, people, now) -> None:
    """Messages the other demos sent more than 36 hours ago were read two hours after they came
    (what waits for a decision keeps its buttons until someone acts)."""
    Notification.objects.filter(
        company=company, read_at__isnull=True, created_at__lt=now - timedelta(hours=36)
    ).update(read_at=F("created_at") + timedelta(hours=2))
