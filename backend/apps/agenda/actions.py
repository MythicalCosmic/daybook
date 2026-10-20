"""Handlers of the calendar's notification buttons (`inbox.registry.register_action`)."""

from apps.agenda import bot_messages, services
from apps.agenda.models import Event, EventAttendee
from apps.core.exceptions import DomainError
from apps.members.models import Membership


def _event(notification) -> Event:
    event = Event.objects.filter(
        company_id=notification.company_id, pk=notification.target_id
    ).first()
    if event is None:
        raise DomainError(bot_messages.cancelled_title_generic())
    return event


def going(notification, by: Membership, reason: str) -> str:
    services.respond(_event(notification), by=by, response=EventAttendee.Response.GOING)
    return bot_messages.answered(EventAttendee.Response.GOING)


def decline(notification, by: Membership, reason: str) -> str:
    services.respond(_event(notification), by=by, response=EventAttendee.Response.DECLINED)
    return bot_messages.answered(EventAttendee.Response.DECLINED)
