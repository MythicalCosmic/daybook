"""The calendar's bot texts: words instead of icons, and the attendee's answers in their own
words (the bots send no emoji)."""

import pytest
from django.utils import translation

from apps.agenda import bot_messages
from apps.agenda.models import Event, EventAttendee
from apps.agenda.tests.factories import AttendeeFactory, EventFactory
from apps.notifications.emoji import has_emoji

pytestmark = pytest.mark.django_db


def test_an_event_card_reads_without_icons(company, member):
    worker = member.registered(company)
    event = EventFactory(company=company, title="Kassa trening", kind=Event.Kind.TRAINING)
    invite = AttendeeFactory(event=event, membership=worker)

    with translation.override("uz"):
        text, markup = bot_messages.event_card(event, invite=invite)
        title = bot_messages.invite_title(event)
        status = str(EventAttendee.Response.DECLINED.label)

    first, when = text.splitlines()[:2]
    assert first == "<b>Kassa trening</b>"
    assert when.startswith("Ertaga ")  # the line starts with a capital
    assert not has_emoji(text)
    # The buttons are what the attendee says; the status keeps its third-person words.
    assert [button.text for button in markup.inline_keyboard[0]] == ["Boraman", "Bora olmayman"]
    assert status == "Bora olmaydi"
    assert title == "Siz taklif qilindingiz: Kassa trening"
