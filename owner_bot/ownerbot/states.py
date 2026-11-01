"""Conversation states of the owner bot."""

from aiogram.fsm.state import State, StatesGroup


class NewCompany(StatesGroup):
    """`/new`: (signup code) → name → timezone → confirm."""

    code = State()
    name = State()
    timezone = State()
    confirm = State()


class VoiceNote(StatesGroup):
    """A voice note waits for the owner to say which company it is for."""

    company = State()
