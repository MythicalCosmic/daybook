"""Builders for the Telegram updates the tests feed into the dispatcher."""

from datetime import datetime
from itertools import count

from aiogram.types import CallbackQuery, Chat, Message, Update, User

_ids = count(1)


def tg_user(user_id: int, first_name: str = "Ali", username: str | None = "ali") -> User:
    return User(
        id=user_id, is_bot=False, first_name=first_name, username=username, language_code="en"
    )


def message(from_user: User, text: str, chat_type: str = "private") -> Update:
    chat_id = from_user.id if chat_type == "private" else -100_000
    return Update(
        update_id=next(_ids),
        message=Message(
            message_id=next(_ids),
            date=datetime.now(),
            chat=Chat(id=chat_id, type=chat_type),
            from_user=from_user,
            text=text,
        ),
    )


def callback(from_user: User, data: str) -> Update:
    return Update(
        update_id=next(_ids),
        callback_query=CallbackQuery(
            id=str(next(_ids)),
            from_user=from_user,
            chat_instance="test",
            data=data,
            message=Message(
                message_id=next(_ids),
                date=datetime.now(),
                chat=Chat(id=from_user.id, type="private"),
                text="Join request",
            ),
        ),
    )
