"""Telegram profile photos as avatars (`accounts.tasks.refresh_telegram_photos`, weekly).

Everyone who works in an active company gets their current Telegram photo cached on
`User.photo`, re-encoded on the server like every other picture (`sanitize_image`), at a small
size. Someone without a photo (or who hides it) loses the old one. People who blocked the bot,
and any Telegram error, are skipped and tried again next week.
"""

import asyncio
import logging
from datetime import timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import User
from apps.core.uploads import InvalidUpload, sanitize_image

logger = logging.getLogger(__name__)

# A run looks at this many people, the longest unchecked first; the rest wait a week.
BATCH = 1000
STALE_AFTER = timedelta(days=6)
AVATAR_SIDE = 256
# Telegram offers several sizes; take the smallest one at least this wide.
WANTED_WIDTH = 320
NO_PHOTO = b""


def due(now) -> list[User]:
    """People to refresh: in an active company, not checked for `STALE_AFTER`."""
    from apps.members.models import Membership

    return list(
        User.objects.filter(
            telegram_id__isnull=False,
            memberships__status__in=(Membership.Status.APPROVED, Membership.Status.SUSPENDED),
            memberships__company__is_active=True,
        )
        .filter(Q(photo_checked_at__isnull=True) | Q(photo_checked_at__lt=now - STALE_AFTER))
        .distinct()
        .order_by("photo_checked_at", "pk")[:BATCH]
    )


async def download(bot: Bot, telegram_id: int) -> bytes:
    """The person's current profile photo, or NO_PHOTO. Raises TelegramAPIError."""
    found = await bot.get_user_profile_photos(telegram_id, limit=1)
    if not found.photos:
        return NO_PHOTO
    sizes = sorted(found.photos[0], key=lambda size: size.width)
    size = next((s for s in sizes if s.width >= WANTED_WIDTH), sizes[-1])
    buffer = await bot.download(size.file_id)
    return buffer.read() if buffer else NO_PHOTO


async def download_all(token: str, telegram_ids: list[int]) -> dict[int, bytes]:
    """{telegram id: photo bytes or NO_PHOTO}; people Telegram refused are left out."""
    found: dict[int, bytes] = {}
    async with Bot(token=token) as bot:
        for telegram_id in telegram_ids:
            try:
                found[telegram_id] = await download(bot, telegram_id)
            except TelegramAPIError as exc:
                logger.info("No profile photo for %s: %s", telegram_id, exc)
    return found


def save(user: User, data: bytes, now) -> None:
    """Store `data` (NO_PHOTO clears the avatar) and remember when we looked."""
    old = user.photo.name if user.photo else ""
    if data:
        try:
            clean = sanitize_image(data, max_side=AVATAR_SIDE)
        except InvalidUpload:
            logger.warning("Telegram sent user %s a photo that isn't a picture", user.pk)
            clean = None
        if clean is not None:
            user.photo.save(clean.name, clean, save=False)
    else:
        user.photo = ""
    user.photo_checked_at = now
    user.save(update_fields=["photo", "photo_checked_at"])
    new = user.photo.name if user.photo else ""
    if old and old != new:
        storage = user.photo.storage
        transaction.on_commit(lambda: storage.delete(old))


def refresh(now=None) -> int:
    """Refresh one batch; returns how many people were looked at."""
    if settings.TELEGRAM_DRY_RUN:
        return 0
    token = settings.EMPLOYEE_BOT_TOKEN or settings.OWNER_BOT_TOKEN
    if not token:
        return 0
    now = now or timezone.now()
    users = due(now)
    if not users:
        return 0
    pictures = asyncio.run(download_all(token, [user.telegram_id for user in users]))
    for user in users:
        if user.telegram_id in pictures:
            save(user, pictures[user.telegram_id], now)
    return len(users)
