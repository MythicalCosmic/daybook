"""The job that sends one task message (`apps.tasks.tasks.send_task_message`)."""

import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage

from apps.tasks import notifications, tasks


def test_a_chat_telegram_doesnt_know_is_a_warning_not_a_failure(monkeypatch, caplog):
    def unknown_chat(task_id, member_id, kind, chat_id, text, reply_markup=None, photo=None):
        raise TelegramBadRequest(SendMessage(chat_id=chat_id, text=text), "chat not found")

    monkeypatch.setattr(notifications, "deliver", unknown_chat)

    with caplog.at_level(logging.WARNING, logger="apps.tasks.tasks"):
        result = tasks.send_task_message.apply(args=(1, 2, "card", 4242, "Salom"))

    assert result.successful()
    assert "not delivered" in caplog.text
