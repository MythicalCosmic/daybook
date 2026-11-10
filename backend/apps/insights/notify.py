"""Urgent insights in the owner bot (and the dashboard's bell): one message per occurrence to
everyone who may see it, in their own language, with "Got it" and "Make it a task" buttons and
an Open button to the cockpit. Plain text, no emoji."""

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.insights import access, texts
from apps.insights.models import Insight

KIND = "insights.critical"
SEEN = ("seen", gettext_lazy("Got it"), "default")
TASK = ("task", gettext_lazy("Make it a task"), "primary")


def cockpit_url(insight: Insight) -> str:
    return f"/c/{insight.company_id}/owner?insight={insight.pk}"


def body(insight: Insight) -> str:
    words = texts.of(insight)
    return "\n".join(part for part in (words.explanation, words.action) if part)


def critical(insight: Insight) -> int:
    """Tell everyone who may see `insight`; returns how many notifications were made."""
    from apps.inbox.services import NotificationAction, notify

    people = access.recipients(insight)
    if not people:
        return 0
    made = notify(
        people,
        KIND,
        title=lambda person: texts.of(insight).title,
        body=lambda person: body(insight),
        url=cockpit_url(insight),
        target=insight,
        severity=Insight.Severity.CRITICAL,
        actions=[NotificationAction(*SEEN), NotificationAction(*TASK)],
        dedupe_key=f"insights:{insight.pk}:{int(insight.detected_at.timestamp())}",
    )
    return len(made)


# Inbox buttons (apps.inbox.registry.register_action) ---------------------------------------


def _target(notification) -> Insight:
    from apps.core.exceptions import DomainError

    insight = (
        Insight.objects.select_related("company", "branch")
        .filter(company_id=notification.company_id, pk=notification.target_id)
        .first()
    )
    if insight is None:
        raise DomainError(_("This isn't available any more."))
    return insight


def seen_action(notification, by, reason: str) -> str:
    from apps.insights import services

    services.acknowledge(_target(notification), by=by)
    return _("Marked as seen.")


def task_action(notification, by, reason: str) -> str:
    from apps.insights import services

    task = services.make_task(_target(notification), by=by)
    return _("Task added: %(title)s") % {"title": task.title}
