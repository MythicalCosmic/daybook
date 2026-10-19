from aiogram.filters import Filter
from aiogram.types import TelegramObject

from apps.members.models import Membership


class IsRegistered(Filter):
    """Members who finished registration. The access gate has already checked approval."""

    async def __call__(self, event: TelegramObject, membership: Membership | None = None) -> bool:
        return membership is not None and membership.is_onboarded
