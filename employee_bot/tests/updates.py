"""Builders for the Telegram updates the tests feed into the dispatcher."""

from datetime import datetime
from itertools import count

from aiogram.types import CallbackQuery, Chat, Contact, Message, PhotoSize, Update, User

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


def contact(from_user: User, phone_number: str, owner_id: int | None = None) -> Update:
    """A shared contact; it belongs to the sender unless `owner_id` says otherwise."""
    return Update(
        update_id=next(_ids),
        message=Message(
            message_id=next(_ids),
            date=datetime.now(),
            chat=Chat(id=from_user.id, type="private"),
            from_user=from_user,
            contact=Contact(
                phone_number=phone_number,
                first_name=from_user.first_name,
                user_id=owner_id or from_user.id,
            ),
        ),
    )


def photo(from_user: User, caption: str | None = None) -> Update:
    return Update(
        update_id=next(_ids),
        message=Message(
            message_id=next(_ids),
            date=datetime.now(),
            chat=Chat(id=from_user.id, type="private"),
            from_user=from_user,
            caption=caption,
            photo=[
                PhotoSize(file_id="small", file_unique_id="s", width=90, height=90),
                PhotoSize(file_id="large", file_unique_id="l", width=1280, height=1280),
            ],
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
