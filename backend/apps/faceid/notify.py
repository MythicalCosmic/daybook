"""Messages Face ID sends once a scan has committed: "who came" with the snapshot, a new number
nobody is linked to, an unknown face, and the branch group's line. Called from
`transaction.on_commit`, by id; each renders in the recipient's language. Nothing here writes
Face ID rows."""

from __future__ import annotations

from django.utils import translation

from apps.attendance import clock
from apps.faceid import bot_messages, conf
from apps.faceid.models import FaceEvent
from apps.groups import services as groups
from apps.groups.models import GroupEvent
from apps.inbox import services as inbox
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import members_with_perm


def _event(event_id: int) -> FaceEvent | None:
    return (
        FaceEvent.objects.select_related("company", "device__branch", "membership__user")
        .filter(pk=event_id)
        .first()
    )


def _seeing(company, branch_id: int, perm: Perm) -> list[Membership]:
    """Approved holders of `perm` who see `branch_id`."""
    holders = (
        members_with_perm(company, perm)
        .select_related("role", "user", "company")
        .prefetch_related("branches")
    )
    return [holder for holder in holders if scope.allows(scope.branch_ids(holder), branch_id)]


def _url(event: FaceEvent, query: str = "") -> str:
    return f"/c/{event.company_id}/faceid{query}"


def _record(event: FaceEvent):
    if not event.record_id:
        return None
    from apps.attendance.models import AttendanceRecord

    return AttendanceRecord.objects.filter(pk=event.record_id).first()


def scan(event_id: int, *, arrival: bool) -> None:
    """ "Mushtariy · 08:00 · Kirish" with the snapshot, to those who see the branch's attendance;
    an arrival also goes to the branch's attendance groups when the settings say so."""
    event = _event(event_id)
    if event is None:
        return
    settings = conf.get_settings(event.company)
    record = _record(event)
    recipients = _seeing(event.company, event.device.branch_id, Perm.ATTENDANCE_VIEW)
    inbox.notify(
        recipients,
        "faceid.scan",
        title=lambda _person: bot_messages.scan_title(event),
        body=lambda _person: bot_messages.scan_body(event, record),
        url=_url(event, f"?event={event.pk}"),
        target=event,
        actor=event.membership,
        photo=event.photo.name or None,
        photo_storage="private",
        dedupe_key=f"faceid.scan:{event.pk}",
    )
    if arrival and settings.group_posts:
        with translation.override(event.company.default_language):
            text = bot_messages.arrival_post(event)
        member = event.membership
        groups.broadcast(
            event.company_id,
            GroupEvent.ATTENDANCE,
            text,
            position_ids=[member.position_id] if member and member.position_id else (),
            branch_id=event.device.branch_id,
            photo=event.photo.name if settings.group_photos and event.photo else None,
            photo_storage="private",
            channel="faceid",
        )


def unlinked(event_id: int) -> None:
    """Managers who see the terminal's branch: a number nobody is linked to (once a day), when
    "who came" messages are off."""
    event = _event(event_id)
    if event is None:
        return
    from django.utils.translation import gettext as _

    recipients = _seeing(event.company, event.device.branch_id, Perm.ATTENDANCE_MANAGE)
    day = clock.today(event.company, event.event_at)

    def title(_person):
        if event.name_on_device:
            return _(
                "Face ID: number %(number)s (%(name)s on the terminal) isn't linked to anyone"
            ) % {
                "number": event.employee_no,
                "name": event.name_on_device,
            }
        return _("Face ID: number %(number)s isn't linked to anyone") % {
            "number": event.employee_no
        }

    def body(_person):
        return _("Terminal: %(device)s. Link the number to a person to count their scans.") % {
            "device": event.device.name
        }

    inbox.notify(
        recipients,
        "faceid.unlinked",
        title=title,
        body=body,
        url=_url(event, f"?tab=people&number={event.employee_no}"),
        target=event,
        photo=event.photo.name or None,
        photo_storage="private",
        dedupe_key=f"faceid.unlinked:{event.number_key}:{day}",
    )


def stranger(event_id: int) -> None:
    """Managers who see the terminal's branch: an unknown face, with the snapshot."""
    event = _event(event_id)
    if event is None:
        return
    from django.utils.translation import gettext as _

    recipients = _seeing(event.company, event.device.branch_id, Perm.ATTENDANCE_MANAGE)

    def title(_person):
        return _("Unknown face at %(device)s, %(time)s") % {
            "device": event.device.name,
            "time": clock.hhmm(event.company, event.event_at),
        }

    inbox.notify(
        recipients,
        "faceid.stranger",
        title=title,
        body=lambda _person: event.device.branch.name,
        url=_url(event, f"?event={event.pk}"),
        target=event,
        photo=event.photo.name or None,
        photo_storage="private",
        dedupe_key=f"faceid.stranger:{event.pk}",
    )
