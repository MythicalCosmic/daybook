"""Conversation states of the owner bot."""

from aiogram.fsm.state import State, StatesGroup


class NewCompany(StatesGroup):
    """`/new`: (signup code) → name → timezone → confirm."""

    code = State()
    name = State()
    timezone = State()
    confirm = State()
