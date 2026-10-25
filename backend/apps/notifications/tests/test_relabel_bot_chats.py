"""After the deploy that took the emoji out of the labels, one command relabels every chat's menu
button and command menu, in each person's language, without sending anyone a message."""

from io import StringIO

import pytest
from aiogram.types import MenuButtonWebApp
from django.core.management import call_command

from apps.accounts.models import User
from apps.notifications.emoji import has_emoji
from apps.notifications.management.commands import relabel_bot_chats

pytestmark = pytest.mark.django_db


def test_every_chat_gets_its_labels_in_its_language(company, member, settings, monkeypatch):
    settings.EMPLOYEE_BOT_TOKEN = "42:TEST"
    settings.TELEGRAM_DRY_RUN = False
    settings.EMPLOYEE_MINIAPP_URL = "https://app.example.uz/app/"
    uz = member.registered(company)
    ru = member.registered(company)
    User.objects.filter(pk=uz.user_id).update(language="uz")
    User.objects.filter(pk=ru.user_id).update(language="ru")
    sent = []

    async def record(bot, chat_id, labels, *, silent):
        sent.append((chat_id, labels, silent))

    monkeypatch.setattr(relabel_bot_chats, "send_labels", record)
    monkeypatch.setattr(relabel_bot_chats, "PAUSE", 0)

    call_command("relabel_bot_chats", stdout=StringIO())

    by_chat = {chat_id: labels for chat_id, labels, _silent in sent}
    assert set(by_chat) == {uz.user.telegram_id, ru.user.telegram_id}
    for labels in by_chat.values():
        assert labels.message is None  # nothing is sent to anyone
        assert isinstance(labels.button, MenuButtonWebApp)
        assert not has_emoji(labels.button.text)
        assert not any(has_emoji(command.description) for command in labels.commands)
    assert by_chat[uz.user.telegram_id].button.text == "Ilovani ochish"
    assert by_chat[ru.user.telegram_id].button.text == "Открыть приложение"


def test_without_a_bot_it_only_counts(company, member, settings):
    settings.EMPLOYEE_BOT_TOKEN = ""
    member.registered(company)
    out = StringIO()

    call_command("relabel_bot_chats", stdout=out)

    assert "1 chats to relabel" in out.getvalue()
