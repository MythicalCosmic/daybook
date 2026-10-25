"""Relabel every employee bot chat after a deploy that changed the chat's own labels (on
25.10.2026 they lost their emoji): its command menu and its menu button, in each person's
language. By default nothing is sent to anyone: old reply keyboards keep working and are replaced
at the person's next tap (bot.middlewares.access).

    manage.py relabel_bot_chats [--send-menu] [--dry-run]

--send-menu also gives every registered member today's keyboard at once, with one silent
message ("Menyu yangilandi."), so no old keyboard stays on a phone.

About 20 calls a second, under Telegram's limit of 30 a second per bot.
"""

import asyncio
from dataclasses import replace

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import translation
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.accounts.services import bot_membership
from apps.accounts.telegram_chat import ChatLabels, chat_labels, send_labels
from apps.members import bot_messages
from apps.members.models import Membership

PAUSE = 0.15  # up to three calls per chat


class Command(BaseCommand):
    help = "Relabel the command menu and menu button of every employee bot chat."

    def add_arguments(self, parser):
        parser.add_argument(
            "--send-menu",
            action="store_true",
            help="Also send registered members today's keyboard, silently.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Only count the chats.")

    def handle(self, *args, send_menu=False, dry_run=False, **options):
        users = User.objects.filter(telegram_id__isnull=False, memberships__isnull=False).distinct()
        chats = [(user.telegram_id, labels_for(user, send_menu=send_menu)) for user in users]
        token = settings.EMPLOYEE_BOT_TOKEN
        if dry_run or settings.TELEGRAM_DRY_RUN or not token:
            menus = sum(labels.message is not None for _chat, labels in chats)
            self.stdout.write(f"{len(chats)} chats to relabel, {menus} new keyboards (not sent).")
            return
        asyncio.run(relabel_all(token, chats))
        self.stdout.write(f"Relabelled {len(chats)} chats.")


def labels_for(user: User, *, send_menu: bool) -> ChatLabels:
    membership = bot_membership(user)
    labels = chat_labels(user, membership, confirm=False)
    registered = (
        membership is not None
        and membership.status == Membership.Status.APPROVED
        and membership.is_onboarded
    )
    if send_menu and registered:
        with translation.override(user.language):
            message = (_("The menu is updated."), bot_messages.main_menu(membership))
        labels = replace(labels, message=message)
    return labels


async def relabel_all(token: str, chats: list[tuple[int, ChatLabels]]) -> None:
    async with Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML)) as bot:
        for chat_id, labels in chats:
            await send_labels(bot, chat_id, labels, silent=True)
            await asyncio.sleep(PAUSE)
