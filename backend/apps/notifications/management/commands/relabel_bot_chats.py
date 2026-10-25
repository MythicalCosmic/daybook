"""Relabel every employee bot chat after a deploy that changed the chat's own labels (on
25.10.2026 they lost their emoji): its command menu and its menu button, in each person's
language. Nothing is sent to anyone: old reply keyboards keep working and are replaced at the
person's next tap (bot.middlewares.access).

    manage.py relabel_bot_chats [--dry-run]

About 20 calls a second, under Telegram's limit of 30 a second per bot.
"""

import asyncio

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.accounts.services import bot_membership
from apps.accounts.telegram_chat import ChatLabels, chat_labels, send_labels

PAUSE = 0.1  # two calls per chat


class Command(BaseCommand):
    help = "Relabel the command menu and menu button of every employee bot chat."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Only count the chats.")

    def handle(self, *args, dry_run=False, **options):
        users = User.objects.filter(telegram_id__isnull=False, memberships__isnull=False).distinct()
        chats = [
            (user.telegram_id, chat_labels(user, bot_membership(user), confirm=False))
            for user in users
        ]
        token = settings.EMPLOYEE_BOT_TOKEN
        if dry_run or settings.TELEGRAM_DRY_RUN or not token:
            self.stdout.write(f"{len(chats)} chats to relabel (not sent).")
            return
        asyncio.run(relabel_all(token, chats))
        self.stdout.write(f"Relabelled {len(chats)} chats.")


async def relabel_all(token: str, chats: list[tuple[int, ChatLabels]]) -> None:
    async with Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML)) as bot:
        for chat_id, labels in chats:
            await send_labels(bot, chat_id, labels, silent=True)
            await asyncio.sleep(PAUSE)
