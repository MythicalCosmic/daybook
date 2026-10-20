"""A Bot whose session records every Bot API call instead of sending it."""

from datetime import datetime
from typing import Any

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import AnswerCallbackQuery, GetMe, SendMessage, TelegramMethod
from aiogram.types import Chat, Message, User

BOT_USERNAME = "owner_test_bot"


class MockedSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,  # noqa: ASYNC109 (aiogram's signature)
    ) -> Any:
        self.requests.append(method)
        if isinstance(method, SendMessage):
            return Message(
                message_id=len(self.requests),
                date=datetime.now(),
                chat=Chat(id=int(method.chat_id), type="private"),
                text=method.text,
            )
        if isinstance(method, GetMe):
            return User(id=bot.id, is_bot=True, first_name="Owner", username=BOT_USERNAME)
        return True

    async def close(self) -> None:
        pass

    async def stream_content(self, *args, **kwargs):  # pragma: no cover - not used
        yield b""


class MockedBot(Bot):
    def __init__(self) -> None:
        super().__init__(
            "43:OWNER-TEST",
            session=MockedSession(),
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )

    @property
    def requests(self) -> list[TelegramMethod[Any]]:
        return self.session.requests

    def sent(self) -> list[SendMessage]:
        return [request for request in self.requests if isinstance(request, SendMessage)]

    def answers(self) -> list[AnswerCallbackQuery]:
        return [request for request in self.requests if isinstance(request, AnswerCallbackQuery)]
