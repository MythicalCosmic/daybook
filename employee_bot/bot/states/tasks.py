from aiogram.fsm.state import State, StatesGroup


class NewTask(StatesGroup):
    title = State()
    due = State()


class CompleteTask(StatesGroup):
    proof = State()


class ReturnTask(StatesGroup):
    reason = State()
