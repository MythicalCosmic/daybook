"""Documents, private photos and message edits (docs/PLAN-OWNER.md §2.8, §3.2)."""

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from django.core.files.base import ContentFile

from apps.core.storage import private_storage
from apps.notifications import telegram
from apps.notifications.tasks import edit_telegram_message, send_telegram_document

BUTTONS = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="Open", callback_data="x")]]
)


@pytest.fixture
def bots(settings):
    settings.EMPLOYEE_BOT_TOKEN = "1:EMPLOYEE"
    settings.OWNER_BOT_TOKEN = "2:OWNER"
    settings.TELEGRAM_DRY_RUN = False


def test_storage_names():
    assert telegram.storage_named("private") is private_storage
    with pytest.raises(ValueError):
        telegram.storage_named("public")


def test_a_document_is_read_from_private_storage(bots, monkeypatch):
    path = private_storage.save("exports/1/abc.xlsx", ContentFile(b"PK-sheet"))
    calls = []

    async def fake_send(token, chat_id, document, caption, markup):
        calls.append((token, chat_id, document.data, document.filename, caption, markup))
        return 77

    monkeypatch.setattr(telegram, "_send_document", fake_send)

    message_id = telegram.send_document(
        telegram.BotName.OWNER,
        5,
        path,
        caption="Tasks · 12 rows",
        filename="tasks-2026-10-20.xlsx",
        reply_markup=telegram.serialize_markup(BUTTONS),
    )

    assert message_id == 77
    assert calls == [
        ("2:OWNER", 5, b"PK-sheet", "tasks-2026-10-20.xlsx", "Tasks · 12 rows", BUTTONS)
    ]


def test_nothing_is_sent_without_a_token_or_in_a_dry_run(settings, monkeypatch):
    calls = []
    monkeypatch.setattr(telegram, "_send_document", lambda *args: calls.append(args))
    settings.OWNER_BOT_TOKEN = ""

    assert telegram.send_document(telegram.BotName.OWNER, 5, "x.pdf") is None
    settings.OWNER_BOT_TOKEN = "2:OWNER"
    settings.TELEGRAM_DRY_RUN = True
    assert telegram.send_document(telegram.BotName.OWNER, 5, "x.pdf") is None
    assert calls == []


def test_a_photo_can_come_from_private_storage(bots, monkeypatch):
    path = private_storage.save("receipts/1/r.jpg", ContentFile(b"jpeg"))
    seen = []

    async def fake_send(token, chat_id, text, markup, image):
        seen.append((image.data, image.filename))
        return 5

    monkeypatch.setattr(telegram, "_send", fake_send)

    telegram.send_message(telegram.BotName.EMPLOYEE, 1, "Claim", None, path, "private")

    assert seen == [(b"jpeg", "r.jpg")]


class FakeBot:
    def __init__(self, text_error=None):
        self.text_error = text_error
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def edit_message_text(self, **kwargs):
        self.calls.append(("text", kwargs))
        if self.text_error:
            raise TelegramBadRequest(EditMessageText(text="x"), self.text_error)

    async def edit_message_caption(self, **kwargs):
        self.calls.append(("caption", kwargs))


def test_edit_replaces_the_text_and_keyboard(bots, monkeypatch):
    bot = FakeBot()
    monkeypatch.setattr(telegram, "_bot", lambda token: bot)

    telegram.edit_message(telegram.BotName.OWNER, 5, 9, "Approved", None)

    assert bot.calls == [
        ("text", {"text": "Approved", "chat_id": 5, "message_id": 9, "reply_markup": None})
    ]


def test_editing_a_photo_changes_its_caption(bots, monkeypatch):
    bot = FakeBot("Bad Request: there is no text in the message to edit")
    monkeypatch.setattr(telegram, "_bot", lambda token: bot)

    telegram.edit_message(telegram.BotName.EMPLOYEE, 5, 9, "x" * 2000, None)

    kind, kwargs = bot.calls[-1]
    assert kind == "caption" and len(kwargs["caption"]) == telegram.CAPTION_LIMIT


@pytest.mark.parametrize(
    "error", ["Bad Request: message is not modified", "Bad Request: message to edit not found"]
)
def test_harmless_edit_errors_are_ignored(bots, monkeypatch, error):
    monkeypatch.setattr(telegram, "_bot", lambda token: FakeBot(error))

    telegram.edit_message(telegram.BotName.EMPLOYEE, 5, 9, "Approved")


def test_other_edit_errors_are_raised_but_the_task_gives_up_quietly(bots, monkeypatch):
    monkeypatch.setattr(telegram, "_bot", lambda token: FakeBot("Bad Request: chat not found"))

    with pytest.raises(TelegramBadRequest):
        telegram.edit_message(telegram.BotName.EMPLOYEE, 5, 9, "Approved")
    edit_telegram_message.delay(telegram.BotName.EMPLOYEE, 5, 9, "Approved")


def test_only_inline_keyboards_can_be_edited_in(bots):
    reply = {"keyboard": [[{"text": "Menu"}]]}

    with pytest.raises(ValueError):
        telegram.edit_message(telegram.BotName.EMPLOYEE, 5, 9, "x", reply)


def test_the_document_task_passes_everything_on(monkeypatch):
    calls = []
    monkeypatch.setattr(
        telegram, "send_document", lambda *args, **kwargs: calls.append((args, kwargs))
    )

    send_telegram_document.delay("owner", 5, "exports/1/a.csv", caption="Rows", filename="a.csv")

    assert calls == [
        (
            ("owner", 5, "exports/1/a.csv"),
            {
                "storage": "private",
                "caption": "Rows",
                "filename": "a.csv",
                "reply_markup": None,
            },
        )
    ]
