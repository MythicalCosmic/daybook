from functools import cache

from aiogram.filters import Filter
from aiogram.types import Message
from django.conf import settings
from django.utils import translation
from django.utils.translation import gettext

from apps.notifications.emoji import has_emoji, plain_label

# Labels whose words changed after keyboards carrying them went out: what those keyboards still
# send, by msgid. The Russian check-in button said "Пришёл / Ушёл" (masculine) until 26.10.2026.
OLD_LABELS = {"Check in / out": ("Пришёл / Ушёл",)}


@cache
def translations(msgid: str) -> frozenset[str]:
    """`msgid` in every language the bot speaks, as `plain_label` writes it, and what older
    keyboards said for it."""
    texts = {plain_label(msgid), *(plain_label(old) for old in OLD_LABELS.get(msgid, ()))}
    for code, _name in settings.LANGUAGES:
        with translation.override(code):
            texts.add(plain_label(gettext(msgid)))
    return frozenset(texts)


def is_label(text: str | None, msgid: str) -> bool:
    """Whether `text` is the button `msgid` in any language. Labels lost their emoji on
    25.10.2026 and the keyboards people have on their phones keep the old ones until the bot
    sends a new one, so "📋 Vazifalarim" and "Vazifalarim" are the same button."""
    return bool(text) and plain_label(text) in translations(msgid)


def is_old_label(text: str | None) -> bool:
    """A button text from a keyboard drawn before labels lost their emoji."""
    return has_emoji(text)


class MenuButton(Filter):
    """Matches a main-menu button in whichever language the person sees it, old or new."""

    def __init__(self, msgid: str) -> None:
        self.msgid = msgid

    async def __call__(self, message: Message) -> bool:
        return is_label(message.text, self.msgid)
