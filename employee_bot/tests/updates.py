"""Builders for the Telegram updates the tests feed into the dispatcher."""

from datetime import datetime
from itertools import count

from aiogram.types import (
    CallbackQuery,
    Chat,
    ChatMemberLeft,
    ChatMemberMember,
    ChatMemberUpdated,
    Contact,
    Message,
    PhotoSize,
    Update,
    User,
)

from tests.mocked_bot import BOT_USERNAME

_ids = count(1)

GROUP_ID = -1_001_555
BOT = User(id=42, is_bot=True, first_name="Daybook", username=BOT_USERNAME)
# Who a message seems to come from when an admin posts anonymously, as the group.
ANONYMOUS_ADMIN = User(
    id=1_087_968_824, is_bot=True, first_name="Group", username="GroupAnonymousBot"
)


def tg_user(
    user_id: int, first_name: str = "Ali", username: str | None = "ali", language_code: str = "en"
) -> User:
    return User(
        id=user_id,
        is_bot=False,
        first_name=first_name,
        username=username,
        language_code=language_code,
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


def group_chat(chat_id: int = GROUP_ID, chat_type: str = "supergroup") -> Chat:
    return Chat(id=chat_id, type=chat_type, title="Shop team")


def group_message(
    from_user: User, text: str | None = None, chat: Chat | None = None, **fields
) -> Update:
    return Update(
        update_id=next(_ids),
        message=Message(
            message_id=next(_ids),
            date=datetime.now(),
            chat=chat or group_chat(),
            from_user=from_user,
            text=text,
            **fields,
        ),
    )


def bot_added(by: User, chat_id: int = GROUP_ID) -> Update:
    return _bot_membership(by, ChatMemberLeft(user=BOT), ChatMemberMember(user=BOT), chat_id)


def bot_removed(by: User, chat_id: int = GROUP_ID) -> Update:
    return _bot_membership(by, ChatMemberMember(user=BOT), ChatMemberLeft(user=BOT), chat_id)


def _bot_membership(by: User, old, new, chat_id: int) -> Update:
    return Update(
        update_id=next(_ids),
        my_chat_member=ChatMemberUpdated(
            chat=group_chat(chat_id),
            from_user=by,
            date=datetime.now(),
            old_chat_member=old,
            new_chat_member=new,
        ),
    )


def group_callback(from_user: User, data: str, chat_id: int = GROUP_ID) -> Update:
    return Update(
        update_id=next(_ids),
        callback_query=CallbackQuery(
            id=str(next(_ids)),
            from_user=from_user,
            chat_instance="group",
            data=data,
            message=Message(
                message_id=next(_ids),
                date=datetime.now(),
                chat=group_chat(chat_id),
                text="What should I post here?",
            ),
        ),
    )
