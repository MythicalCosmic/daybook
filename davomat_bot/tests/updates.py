"""Builders for the Telegram updates the bot's tests feed into the dispatcher."""

from datetime import datetime
from itertools import count

from aiogram.types import (
    CallbackQuery,
    Chat,
    ChatMemberBanned,
    ChatMemberMember,
    ChatMemberUpdated,
    InlineKeyboardMarkup,
    Message,
    Update,
    User,
)

from davomat_bot.tests.mocked_bot import BOT_USERNAME

_ids = count(1)
BOT = User(id=44, is_bot=True, first_name="Davomat", username=BOT_USERNAME)


def tg_user(user_id: int, first_name: str = "Dilnoza", language_code: str = "en") -> User:
    return User(
        id=user_id,
        is_bot=False,
        first_name=first_name,
        username=f"user{user_id}",
        language_code=language_code,
    )


def message(from_user: User, text: str) -> Update:
    return Update(
        update_id=next(_ids),
        message=Message(
            message_id=next(_ids),
            date=datetime.now(),
            chat=Chat(id=from_user.id, type="private"),
            from_user=from_user,
            text=text,
        ),
    )


def callback(
    from_user: User, data: str, *, text: str = "Davomat", markup: InlineKeyboardMarkup | None = None
) -> Update:
    return Update(
        update_id=next(_ids),
        callback_query=CallbackQuery(
            id=str(next(_ids)),
            from_user=from_user,
            chat_instance="davomat",
            data=data,
            message=Message(
                message_id=next(_ids),
                date=datetime.now(),
                chat=Chat(id=from_user.id, type="private"),
                text=text,
                reply_markup=markup,
            ),
        ),
    )


def blocked(by: User) -> Update:
    return _membership(by, ChatMemberMember(user=BOT), ChatMemberBanned(user=BOT, until_date=0))


def unblocked(by: User) -> Update:
    return _membership(by, ChatMemberBanned(user=BOT, until_date=0), ChatMemberMember(user=BOT))


def _membership(by: User, old, new) -> Update:
    return Update(
        update_id=next(_ids),
        my_chat_member=ChatMemberUpdated(
            chat=Chat(id=by.id, type="private"),
            from_user=by,
            date=datetime.now(),
            old_chat_member=old,
            new_chat_member=new,
        ),
    )
