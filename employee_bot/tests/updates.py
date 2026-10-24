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
    Document,
    InlineKeyboardMarkup,
    Message,
    PhotoSize,
    Sticker,
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


def photo(from_user: User, caption: str | None = None, media_group_id: str | None = None) -> Update:
    return Update(
        update_id=next(_ids),
        message=Message(
            message_id=next(_ids),
            date=datetime.now(),
            chat=Chat(id=from_user.id, type="private"),
            from_user=from_user,
            caption=caption,
            media_group_id=media_group_id,
            photo=[
                PhotoSize(file_id="small", file_unique_id="s", width=90, height=90),
                PhotoSize(file_id="large", file_unique_id="l", width=1280, height=1280),
            ],
        ),
    )


def image_file(from_user: User, mime_type: str = "image/jpeg") -> Update:
    """A photo sent as a file, to keep its quality."""
    return Update(
        update_id=next(_ids),
        message=Message(
            message_id=next(_ids),
            date=datetime.now(),
            chat=Chat(id=from_user.id, type="private"),
            from_user=from_user,
            document=Document(
                file_id="doc", file_unique_id="d", file_name="IMG_1.jpg", mime_type=mime_type
            ),
        ),
    )


def sticker(from_user: User) -> Update:
    return Update(
        update_id=next(_ids),
        message=Message(
            message_id=next(_ids),
            date=datetime.now(),
            chat=Chat(id=from_user.id, type="private"),
            from_user=from_user,
            sticker=Sticker(
                file_id="st",
                file_unique_id="st",
                type="regular",
                width=512,
                height=512,
                is_animated=False,
                is_video=False,
            ),
        ),
    )


def reply(from_user: User, text: str, to_markup: InlineKeyboardMarkup) -> Update:
    """A text sent as a reply to one of the bot's messages carrying `to_markup`."""
    replied = Message(
        message_id=next(_ids),
        date=datetime.now(),
        chat=Chat(id=from_user.id, type="private"),
        from_user=BOT,
        text="card",
        reply_markup=to_markup,
    )
    return Update(
        update_id=next(_ids),
        message=Message(
            message_id=next(_ids),
            date=datetime.now(),
            chat=Chat(id=from_user.id, type="private"),
            from_user=from_user,
            text=text,
            reply_to_message=replied,
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


def pick_language(from_user: User, code: str = "en", mode: str = "first") -> Update:
    """A tap on the language picker a brand-new person gets first (research R1 L2)."""
    from bot.callbacks import LangCallback

    return callback(from_user, LangCallback(code=code, mode=mode).pack())
