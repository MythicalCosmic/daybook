from functools import cache

from aiogram.filters import Filter
from aiogram.types import Message
from django.conf import settings
from django.utils import translation
from django.utils.translation import gettext


@cache
def translations(msgid: str) -> frozenset[str]:
    """`msgid` in every language the bot speaks."""
    texts = set()
    for code, _name in settings.LANGUAGES:
        with translation.override(code):
            texts.add(gettext(msgid))
    return frozenset(texts)


class MenuButton(Filter):
    """Matches a main-menu button in whichever language the person sees it."""

    def __init__(self, msgid: str) -> None:
        self.msgid = msgid

    async def __call__(self, message: Message) -> bool:
        return message.text in translations(self.msgid)
