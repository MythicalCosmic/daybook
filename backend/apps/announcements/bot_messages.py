"""Announcements in the bot: drafting, the copies people get, and the read receipts."""

from aiogram import html
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from django.utils.translation import gettext as _

from apps.announcements.callbacks import AnnounceAction, AnnounceCallback
from apps.announcements.models import Announcement
from apps.members.bot_messages import BotMessage
from apps.members.models import Membership, Position

NAMES_LIMIT = 30


def ask_text() -> BotMessage:
    text = _("Send the announcement as one message. Bold, italics and links are kept.")
    return text, InlineKeyboardMarkup(inline_keyboard=[[_cancel()]])


def preview(text: str, positions: list[Position], chosen: set[int]) -> BotMessage:
    # A chosen position is a green button, and the text lists the choice (no tick marks).
    rows = [
        [
            _button(
                position.name,
                AnnounceAction.PICK,
                style="success" if position.pk in chosen else None,
                position_id=position.pk,
            )
        ]
        for position in positions
    ]
    send = _("Send to the chosen positions") if chosen else _("Send to everyone")
    rows.append([_button(send, AnnounceAction.SEND)])
    rows.append([_cancel()])
    hint = _("Who should get it? Tap positions, or send it to everyone.") if positions else ""
    lines = [_("<b>Preview</b>"), "", text]
    if hint:
        lines += ["", hint]
    if names := [position.name for position in positions if position.pk in chosen]:
        lines.append(_("Chosen positions: %(names)s") % {"names": html.quote(", ".join(names))})
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def sent(announcement: Announcement, recipients: int) -> BotMessage:
    text = _("Sent. Recipients: %(count)d. Tap below to see who has read it.") % {
        "count": recipients
    }
    return text, InlineKeyboardMarkup(inline_keyboard=[[_who(announcement)]])


def copy(announcement: Announcement, *, reminder: bool = False) -> BotMessage:
    """What a recipient gets, with the button to say they've read it."""
    author = html.quote(str(announcement.author)) if announcement.author else "—"
    if reminder:
        header = _("<b>Reminder</b>: please read this announcement from %(name)s.")
    else:
        header = _("<b>Announcement</b> · %(name)s")
    text = f"{header % {'name': author}}\n\n{announcement.text}"
    button = _button(_("I've read it"), AnnounceAction.READ, announcement_id=announcement.pk)
    return text, InlineKeyboardMarkup(inline_keyboard=[[button]])


def read_copy(announcement: Announcement) -> BotMessage:
    text, _markup = copy(announcement)
    return f"{text}\n\n{_('You have read this.')}", None


def who(read: list[Membership], unread: list[Membership]) -> BotMessage:
    total = len(read) + len(unread)
    lines = [_("Read by %(read)d of %(total)d.") % {"read": len(read), "total": total}]
    if unread:
        lines.append(_("Not yet: %(names)s") % {"names": _names(unread)})
    return "\n".join(lines), None


def summary(announcement: Announcement, unread: list[Membership], total: int) -> BotMessage:
    text = _(
        "A day later, %(unread)d of %(total)d people still haven't read your announcement "
        "“%(title)s”: %(names)s"
    ) % {
        "unread": len(unread),
        "total": total,
        "title": html.quote(str(announcement)),
        "names": _names(unread),
    }
    return text, InlineKeyboardMarkup(inline_keyboard=[[_who(announcement)]])


def _names(people: list[Membership]) -> str:
    names = ", ".join(html.quote(str(person)) for person in people[:NAMES_LIMIT])
    if (more := len(people) - NAMES_LIMIT) > 0:
        names += " " + _("…and %(count)d more") % {"count": more}
    return names


def _who(announcement: Announcement) -> InlineKeyboardButton:
    return _button(_("Who has read it?"), AnnounceAction.WHO, announcement_id=announcement.pk)


def _cancel() -> InlineKeyboardButton:
    return _button(_("Cancel"), AnnounceAction.CANCEL)


def _button(
    text: str, action: AnnounceAction, *, style: str | None = None, **fields
) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text, callback_data=AnnounceCallback(action=action, **fields).pack(), style=style
    )
