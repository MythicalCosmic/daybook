from aiogram import Router, html
from aiogram.filters import CommandStart
from aiogram.types import Message

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    # Placeholder until the access flow (M2) replaces it.
    await message.answer(f"Salom, <b>{html.quote(message.from_user.full_name)}</b>! The bot is up.")
