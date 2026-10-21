"""Who hears about time off, through the inbox (apps.inbox.services.notify).

Requests go to the approvers who manage the person's branch: in "Needs you" in the dashboard
and as a Telegram copy with Approve / Reject (kind `timeoff.request`, a queue kind, so no
in-app row). Decisions, time off recorded for someone and revoked time off go to the person
(employee kinds: the bot and the mini app's inbox).
"""

from django.utils.translation import gettext as _

from apps.inbox import services as inbox
from apps.inbox.services import NotificationAction
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import members_with_perm
from apps.timeoff import bot_messages
from apps.timeoff.models import TimeOff

REQUEST = "timeoff.request"
DECIDED = "timeoff.decided"
RECORDED = "timeoff.recorded"
REVOKED = "timeoff.revoked"
APP_SCREEN = "timeOff"


def approvers(time_off: TimeOff) -> list[Membership]:
    """Approved members who may decide this request: `time_off.approve`, not the person
    themselves, and seeing one of the person's branches (everyone with every branch)."""
    member = time_off.membership
    branch_ids = set(member.branches.values_list("pk", flat=True))
    found = []
    candidates = (
        members_with_perm(time_off.company, Perm.TIME_OFF_APPROVE)
        .exclude(pk=member.pk)
        .select_related("user", "role", "company")
        .prefetch_related("branches")
    )
    for candidate in candidates:
        seen = scope.branch_ids(candidate)
        if seen is None or branch_ids & set(seen):
            found.append(candidate)
    return found


def send_request(time_off_id: int) -> None:
    time_off = _load(time_off_id)
    if time_off is None or time_off.status != TimeOff.Status.PENDING:
        return
    inbox.notify(
        approvers(time_off),
        REQUEST,
        title=lambda person: bot_messages.request_title(time_off),
        body=lambda person: bot_messages.request_body(time_off),
        url=f"/c/{time_off.company_id}/time-off?request={time_off.pk}",
        target=time_off,
        actor=time_off.membership,
        actions=[
            NotificationAction("approve", lambda person: _("✅ Approve"), "primary"),
            NotificationAction("reject", lambda person: _("❌ Reject"), "danger"),
        ],
        dedupe_key=f"timeoff.request:{time_off.pk}",
    )


def send_decision(time_off_id: int) -> None:
    time_off = _load(time_off_id)
    if time_off is None or time_off.status not in (
        TimeOff.Status.APPROVED,
        TimeOff.Status.REJECTED,
    ):
        return
    _tell_member(
        time_off,
        DECIDED,
        title=lambda person: bot_messages.decision_title(time_off),
        body=lambda person: bot_messages.decision_body(time_off),
    )


def send_recorded(time_off_id: int) -> None:
    time_off = _load(time_off_id)
    if time_off is None or time_off.status != TimeOff.Status.APPROVED:
        return
    _tell_member(
        time_off,
        RECORDED,
        title=lambda person: bot_messages.recorded_title(time_off),
        body=lambda person: bot_messages.recorded_body(time_off),
    )


def send_revoked(time_off_id: int) -> None:
    time_off = _load(time_off_id)
    if time_off is None or time_off.revoked_at is None:
        return
    _tell_member(
        time_off,
        REVOKED,
        title=lambda person: bot_messages.revoked_title(time_off),
        body=lambda person: bot_messages.revoked_body(time_off),
        severity="warning",
    )


def _tell_member(time_off: TimeOff, kind: str, *, title, body, severity=None) -> None:
    member = time_off.membership
    if member.status != Membership.Status.APPROVED:
        return  # suspended or gone: the bot leaves them alone
    inbox.notify(
        [member],
        kind,
        title=title,
        body=body,
        app_screen=APP_SCREEN,
        target=time_off,
        severity=severity,
    )


def _load(time_off_id: int) -> TimeOff | None:
    return (
        TimeOff.objects.select_related(
            "company",
            "membership__user",
            "membership__company",
            "decided_by",
            "revoked_by",
            "recorded_by",
        )
        .filter(pk=time_off_id)
        .first()
    )
