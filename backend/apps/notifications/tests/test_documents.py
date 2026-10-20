"""Sending documents, private photos and edits through the bots (no network: a fake session)."""

from datetime import datetime

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import (
    EditMessageCaption,
    EditMessageText,
    SendDocument,
    SendMessage,
    SendPhoto,
)
from aiogram.types import Chat, InlineKeyboardButton, InlineKeyboardMarkup, Message
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from apps.core.storage import private_storage
from apps.notifications import telegram
from apps.notifications.tasks import (
    edit_telegram_message,
    send_telegram_document,
    send_telegram_message,
)


class RecordingSession(BaseSession):
    def __init__(self, fail_with: Exception | None = None):
        super().__init__()
        self.requests = []
        self.fail_with = fail_with
        self.fail_only = None  # a method type: only those requests fail

    async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109
        self.requests.append(method)
        if self.fail_with is not None and (
            self.fail_only is None or isinstance(method, self.fail_only)
        ):
            raise self.fail_with
        if isinstance(method, SendMessage | SendPhoto | SendDocument):
            return Message(
                message_id=len(self.requests) + 100,
                date=datetime.now(),
                chat=Chat(id=int(method.chat_id), type="private"),
            )
        return True

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        yield b""


@pytest.fixture
def session(settings, monkeypatch, tmp_path):
    settings.TELEGRAM_DRY_RUN = False
    settings.EMPLOYEE_BOT_TOKEN = "42:TEST"
    settings.OWNER_BOT_TOKEN = "43:TEST"
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.PRIVATE_MEDIA_ROOT = tmp_path / "private"
    recording = RecordingSession()
    tokens = []

    def bot(token):
        tokens.append(token)
        return Bot(
            token, session=recording, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )

    monkeypatch.setattr(telegram, "_bot", bot)
    recording.tokens = tokens
    return recording


MARKUP = telegram.serialize_markup(
    InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Approve", callback_data="x:1")]]
    )
)


def test_a_private_document_is_sent_with_its_caption(session):
    path = private_storage.save("payslips/1/abc.pdf", ContentFile(b"%PDF-1.7"))

    message_id = telegram.send_document(
        telegram.BotName.EMPLOYEE,
        77,
        path,
        caption="Your October payslip",
        filename="Payslip-2026-10.pdf",
        reply_markup=MARKUP,
    )

    [request] = session.requests
    assert isinstance(request, SendDocument)
    assert request.chat_id == 77
    assert request.caption == "Your October payslip"
    assert request.document.filename == "Payslip-2026-10.pdf"
    assert request.document.data == b"%PDF-1.7"
    assert request.reply_markup.inline_keyboard[0][0].text == "Approve"
    assert message_id == 101


def test_a_long_caption_follows_the_document(session):
    path = private_storage.save("exports/1/a.xlsx", ContentFile(b"PK"))

    telegram.send_document(telegram.BotName.OWNER, 5, path, caption="x" * 2000)

    assert [type(r) for r in session.requests] == [SendDocument, SendMessage]
    assert session.tokens == ["43:TEST"]


def test_a_photo_can_come_from_private_storage(session):
    path = private_storage.save("receipts/1/r.jpg", ContentFile(b"\xff\xd8\xff"))

    telegram.send_message(
        telegram.BotName.EMPLOYEE, 9, "Claim to approve", photo=path, photo_storage="private"
    )

    [request] = session.requests
    assert isinstance(request, SendPhoto)
    assert request.photo.data == b"\xff\xd8\xff"
    assert request.caption == "Claim to approve"


def test_public_photos_still_come_from_media(session):
    path = default_storage.save("proofs/1/p.jpg", ContentFile(b"\xff\xd8"))

    telegram.send_message(telegram.BotName.EMPLOYEE, 9, "Done", photo=path)

    assert session.requests[0].photo.data == b"\xff\xd8"


def test_unknown_storages_are_refused(session):
    with pytest.raises(ValueError):
        telegram.send_document(telegram.BotName.EMPLOYEE, 1, "a.pdf", storage="s3")


def test_editing_replaces_text_and_keyboard(session):
    telegram.edit_message(telegram.BotName.OWNER, 5, 321, "✅ Approved by Olim", MARKUP)

    [request] = session.requests
    assert isinstance(request, EditMessageText)
    assert (request.chat_id, request.message_id, request.text) == (5, 321, "✅ Approved by Olim")


def test_editing_a_photo_message_edits_its_caption(session):
    session.fail_with = TelegramBadRequest(
        EditMessageText(chat_id=5, message_id=1, text="x"),
        "Bad Request: there is no text in the message to edit",
    )
    session.fail_only = EditMessageText

    telegram.edit_message(telegram.BotName.EMPLOYEE, 5, 321, "✅ Approved", MARKUP)

    first, second = session.requests
    assert isinstance(first, EditMessageText)
    assert isinstance(second, EditMessageCaption)
    assert (second.chat_id, second.message_id, second.caption) == (5, 321, "✅ Approved")
    assert second.reply_markup.inline_keyboard[0][0].text == "Approve"


def test_editing_a_message_that_is_gone_is_fine(session):
    session.fail_with = TelegramBadRequest(
        EditMessageText(chat_id=5, message_id=1, text="x"), "message to edit not found"
    )

    telegram.edit_message(telegram.BotName.OWNER, 5, 1, "x")  # no exception


def test_dry_run_and_missing_tokens_send_nothing(session, settings):
    path = private_storage.save("payslips/1/abc.pdf", ContentFile(b"%PDF-1.7"))
    settings.TELEGRAM_DRY_RUN = True
    assert telegram.send_document(telegram.BotName.EMPLOYEE, 1, path) is None
    telegram.edit_message(telegram.BotName.EMPLOYEE, 1, 2, "x")
    settings.TELEGRAM_DRY_RUN = False
    settings.EMPLOYEE_BOT_TOKEN = ""
    assert telegram.send_document(telegram.BotName.EMPLOYEE, 1, path) is None

    assert session.requests == []


def test_the_celery_wrappers_pass_everything_on(session):
    path = private_storage.save("payslips/1/abc.pdf", ContentFile(b"%PDF-1.7"))
    photo = private_storage.save("receipts/1/r.jpg", ContentFile(b"\xff\xd8\xff"))

    send_telegram_document.delay(
        telegram.BotName.EMPLOYEE, 1, path, caption="Payslip", filename="p.pdf"
    )
    send_telegram_message.delay(
        telegram.BotName.EMPLOYEE, 1, "Receipt", None, photo, photo_storage="private"
    )
    edit_telegram_message.delay(telegram.BotName.EMPLOYEE, 1, 5, "Done", MARKUP)

    assert [type(r) for r in session.requests] == [SendDocument, SendPhoto, EditMessageText]


def test_the_wrappers_give_up_quietly_on_blocked_chats(session):
    session.fail_with = TelegramForbiddenError(SendMessage(chat_id=1, text="x"), "blocked")
    path = private_storage.save("payslips/1/abc.pdf", ContentFile(b"%PDF-1.7"))

    send_telegram_document.delay(telegram.BotName.EMPLOYEE, 1, path)
    edit_telegram_message.delay(telegram.BotName.EMPLOYEE, 1, 5, "Done")
