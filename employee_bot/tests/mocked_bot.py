from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import GetFile, GetMe, SendMessage, TelegramMethod
from aiogram.types import Chat, File, Message, User

# What every downloaded file contains, e.g. a proof photo.
FILE_CONTENT = b"fake-jpeg"
BOT_USERNAME = "daybook_test_bot"


class MockedSession(BaseSession):
    """Records every Bot API call instead of sending it."""

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
            return User(id=bot.id, is_bot=True, first_name="Daybook", username=BOT_USERNAME)
        if isinstance(method, GetFile):
            return File(
                file_id=method.file_id,
                file_unique_id=f"unique-{method.file_id}",
                file_path=f"photos/{method.file_id}.jpg",
            )
        return True

    async def close(self) -> None:
        pass

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,  # noqa: ASYNC109 (aiogram's signature)
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes]:
        yield FILE_CONTENT


class MockedBot(Bot):
    def __init__(self) -> None:
        super().__init__(
            "42:TEST",
            session=MockedSession(),
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )

    @property
    def requests(self) -> list[TelegramMethod[Any]]:
        return self.session.requests

    def sent_texts(self) -> list[str]:
        return [request.text for request in self.requests if isinstance(request, SendMessage)]
