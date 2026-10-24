from aiogram.fsm.state import State, StatesGroup


class NewTask(StatesGroup):
    title = State()
    assignee = State()  # managers: who it's for (audit X-7)
    due = State()
    confirm = State()  # "what I understood" before saving (research R2 T2)


class CompleteTask(StatesGroup):
    proof = State()  # the card waits for a photo or a report


class ProofFirst(StatesGroup):
    pick = State()  # a photo came first: which task is it for? (R1 C4)


class ReturnTask(StatesGroup):
    reason = State()


class CommentTask(StatesGroup):
    text = State()


class TaskTime(StatesGroup):
    typed = State()  # a typed time: more time asked, or a manager's new deadline


class BlockTask(StatesGroup):
    note = State()  # "can't do it" for another reason: what's in the way


class PickLanguage(StatesGroup):
    first = State()  # first contact: the /start parameter waits for the language


class Announce(StatesGroup):
    text = State()
    audience = State()
