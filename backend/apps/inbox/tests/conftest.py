from itertools import count

import pytest
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage

from apps.core.exceptions import DomainError
from apps.inbox.registry import register_action, register_kind


class Handlers:
    """Action handlers that record what they were asked to do."""

    def __init__(self):
        self.calls = []

    def approve(self, notification, by, reason):
        self.calls.append(("approve", notification.pk, by.pk, reason))
        return "Claim approved"

    def reject(self, notification, by, reason):
        self.calls.append(("reject", notification.pk, by.pk, reason))
        return None

    def refuse(self, notification, by, reason):
        raise DomainError("This claim was already paid.")


@pytest.fixture
def handlers(isolated_registries):
    """Kinds of every flavour, registered as apps.inbox would."""
    handlers = Handlers()
    register_kind("inbox.claim", label="Expense claim", audience="owner", default_telegram=True)
    register_action("inbox.claim", "approve", handlers.approve)
    register_action("inbox.claim", "reject", handlers.reject)
    register_action("inbox.claim", "pay", handlers.refuse)
    register_kind("inbox.digest", label="Digest", audience="employee", default_telegram=False)
    register_kind(
        "inbox.request",
        label="Time off request",
        audience="owner",
        default_telegram=True,
        severity="warning",
        queue_kind="inbox.requests",
    )
    register_action("inbox.request", "approve", handlers.approve)
    return handlers


class Telegram:
    """Stands in for apps.notifications.telegram: records sends and edits, hands out ids."""

    def __init__(self):
        self.sent = []
        self.edited = []
        self.ids = count(100)
        self.refuse = set()  # bots that answer "Forbidden: bot was blocked by the user"

    def send_message(
        self, bot, chat_id, text, reply_markup=None, photo=None, photo_storage="default"
    ):
        if bot in self.refuse:
            raise TelegramForbiddenError(SendMessage(chat_id=chat_id, text=text), "blocked")
        message_id = next(self.ids)
        self.sent.append(
            {
                "bot": bot,
                "chat_id": chat_id,
                "text": text,
                "markup": reply_markup,
                "photo": photo,
                "photo_storage": photo_storage,
                "message_id": message_id,
            }
        )
        return message_id

    def edit_message(self, bot, chat_id, message_id, text, reply_markup=None):
        self.edited.append(
            {
                "bot": bot,
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "markup": reply_markup,
            }
        )


@pytest.fixture
def telegram(monkeypatch):
    fake = Telegram()
    monkeypatch.setattr("apps.notifications.telegram.send_message", fake.send_message)
    monkeypatch.setattr("apps.notifications.telegram.edit_message", fake.edit_message)
    return fake
