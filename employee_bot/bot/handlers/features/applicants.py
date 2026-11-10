"""Employee bot, Package G. Vacancy applicants, who are not members of the company: the
conversation after `/start job_<code>` (also `job_<code>-q`, the vacancy's QR code).

    the vacancy ("Apply", and the other two languages) → the name (or the one Telegram knows)
    → each question in turn (buttons for a choice or a yes-or-no, typed text or a number, "Skip"
    for an optional one) → the phone number, shared with the button → a photo of a diploma or a
    certificate when the vacancy asks → the summary → "Send application"

Someone who already applied sees where their application stands instead; a vacancy that is
closed, paused or not open yet says so. "Cancel" (or /cancel, "bekor", "отмена") stops at any
step. The texts are `apps.hr.hiring.bot`'s, the rules `apps.hr.hiring.services`'s.

Registered outside the member gate, right after the start router and before the contact router,
so an applicant's answers and contact reach the application instead of the join flow. Handlers
here are bound to the applicant's conversation states (or to its own buttons), so they never
take members' messages.
"""

from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from asgiref.sync import sync_to_async
from django.utils import translation

from apps.accounts.models import User
from apps.accounts.services import save_verified_phone, set_language
from apps.core.exceptions import DomainError
from apps.core.uploads import sanitize_image
from apps.hr.hiring import bot as texts
from apps.hr.hiring import questions, services
from apps.hr.hiring.callbacks import ApplyButton, ApplyStep
from apps.hr.models import QuestionKind, Vacancy
from bot.deeplinks import register_start_param

router = Router(name="feature_applicants")
router.message.filter(F.chat.type == ChatType.PRIVATE)
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)


class ApplyFlow(StatesGroup):
    intro = State()  # the vacancy, waiting for "Apply"
    name = State()
    question = State()  # data["index"] is the question being answered
    contact = State()
    document = State()
    confirm = State()


# Opening the link -------------------------------------------------------------------------


async def open_vacancy(message: Message, payload: str, *, user: User, state: FSMContext) -> None:
    """`/start job_<code>`: the vacancy with "Apply", or where the person's application stands,
    or why it takes no applications now. A conversation in progress ends only when a new
    application starts."""
    opened = await sync_to_async(services.open_link)(user, payload)
    if opened.state == services.LinkState.APPLIED:
        await message.answer(await sync_to_async(texts.status)(opened.applicant))
        return
    if opened.state != services.LinkState.OK:
        await message.answer(texts.unavailable(opened.state, opened.vacancy))
        return
    vacancy = opened.vacancy
    await state.set_state(ApplyFlow.intro)
    await state.set_data({"vacancy": vacancy.pk, "source": opened.source, "answers": []})
    text, markup = await sync_to_async(texts.vacancy_card)(vacancy, user.language)
    await message.answer(text, reply_markup=markup)


register_start_param("job_", open_vacancy)


# The vacancy card -------------------------------------------------------------------------


@router.callback_query(ApplyFlow.intro, ApplyButton.filter(F.step == ApplyStep.LANGUAGE))
async def change_language(
    query: CallbackQuery, callback_data: ApplyButton, user: User, state: FSMContext
) -> None:
    vacancy = await _vacancy(query, callback_data, state)
    if vacancy is None:
        return
    code = texts.LANGUAGES[callback_data.pick] if callback_data.pick < 3 else "uz"
    await sync_to_async(set_language)(user, code)
    await query.answer(texts.LANGUAGE_NAMES[code])
    with translation.override(code):
        text, markup = await sync_to_async(texts.vacancy_card)(vacancy, code)
    with suppress(TelegramBadRequest):
        await query.message.edit_text(text, reply_markup=markup)


@router.callback_query(ApplyFlow.intro, ApplyButton.filter(F.step == ApplyStep.APPLY))
async def start_applying(
    query: CallbackQuery, callback_data: ApplyButton, user: User, state: FSMContext
) -> None:
    vacancy = await _vacancy(query, callback_data, state)
    if vacancy is None:
        return
    await query.answer()
    await _drop_buttons(query)
    await state.set_state(ApplyFlow.name)
    text, markup = texts.ask_name(vacancy, services.suggested_name(user))
    await query.message.answer(text, reply_markup=markup)


# The name ---------------------------------------------------------------------------------


@router.callback_query(ApplyFlow.name, ApplyButton.filter(F.step == ApplyStep.NAME))
async def name_from_telegram(
    query: CallbackQuery, callback_data: ApplyButton, user: User, state: FSMContext
) -> None:
    vacancy = await _vacancy(query, callback_data, state)
    if vacancy is None:
        return
    name = services.suggested_name(user)
    if not name:
        await query.answer(texts.bad_name(), show_alert=True)
        return
    await query.answer()
    await _drop_buttons(query)
    await state.update_data(name=name)
    await _next_question(query.message, vacancy, state, 0)


@router.message(ApplyFlow.name, F.text)
async def typed_name(message: Message, user: User, state: FSMContext) -> None:
    if texts.is_cancel(message.text):
        await _cancel(message, state)
        return
    vacancy = await _flow_vacancy(message, state)
    if vacancy is None:
        return
    name = services.clean_name(message.text)
    if name is None:
        await message.answer(texts.bad_name())
        return
    await state.update_data(name=name)
    await _next_question(message, vacancy, state, 0)


# The questions ----------------------------------------------------------------------------


@router.callback_query(ApplyFlow.question, ApplyButton.filter(F.step == ApplyStep.ANSWER))
async def picked_answer(
    query: CallbackQuery, callback_data: ApplyButton, state: FSMContext
) -> None:
    vacancy = await _vacancy(query, callback_data, state, question=True)
    if vacancy is None:
        return
    question = vacancy.questions[callback_data.q]
    if question["kind"] == QuestionKind.YES_NO:
        answer = questions.YES if callback_data.pick else questions.NO
    else:
        answer = questions.choice_answer(question, callback_data.pick)
    if answer is None:
        await query.answer(texts.stale_button())
        return
    await query.answer()
    await _answered(query.message, vacancy, state, callback_data.q, answer, edit=True)


@router.callback_query(ApplyFlow.question, ApplyButton.filter(F.step == ApplyStep.SKIP))
async def skipped_question(
    query: CallbackQuery, callback_data: ApplyButton, state: FSMContext
) -> None:
    vacancy = await _vacancy(query, callback_data, state, question=True)
    if vacancy is None:
        return
    if vacancy.questions[callback_data.q].get("required", True):
        await query.answer(texts.stale_button())
        return
    await query.answer()
    await _answered(query.message, vacancy, state, callback_data.q, "", edit=True)


@router.message(ApplyFlow.question)
async def typed_answer(message: Message, state: FSMContext) -> None:
    if texts.is_cancel(message.text):
        await _cancel(message, state)
        return
    vacancy = await _flow_vacancy(message, state)
    if vacancy is None:
        return
    index = (await state.get_data()).get("index", 0)
    if index >= len(vacancy.questions):  # the vacancy lost questions meanwhile
        await _next_question(message, vacancy, state, index)
        return
    question = vacancy.questions[index]
    kind = question["kind"]
    if kind in (QuestionKind.CHOICE, QuestionKind.YES_NO):
        await message.answer(texts.use_buttons())
        return
    if kind == QuestionKind.NUMBER:
        answer = questions.number_answer(message.text)
        if answer is None:
            await message.answer(texts.bad_number())
            return
    else:
        answer = questions.text_answer(message.text)
        if answer is None:
            await message.answer(texts.bad_text())
            return
    await _answered(message, vacancy, state, index, answer, edit=False)


async def _answered(
    message: Message, vacancy: Vacancy, state: FSMContext, index: int, answer: str, *, edit: bool
) -> None:
    row = questions.answer_row(vacancy.questions[index], answer)
    data = await state.get_data()
    answers = [item for item in data.get("answers", []) if item.get("id") != row["id"]]
    await state.update_data(answers=[*answers, row])
    if edit:
        with suppress(TelegramBadRequest):
            await message.edit_text(texts.answered(vacancy, index, row), reply_markup=None)
    await _next_question(message, vacancy, state, index + 1)


async def _next_question(message: Message, vacancy: Vacancy, state: FSMContext, index: int):
    if index < len(vacancy.questions):
        await state.set_state(ApplyFlow.question)
        await state.update_data(index=index)
        text, markup = texts.ask_question(vacancy, index)
        await message.answer(text, reply_markup=markup)
        return
    await state.set_state(ApplyFlow.contact)
    text, markup = texts.ask_contact()
    await message.answer(text, reply_markup=markup)


# The phone number and the document --------------------------------------------------------


@router.message(ApplyFlow.contact, F.contact)
async def shared_contact(message: Message, user: User, state: FSMContext) -> None:
    vacancy = await _flow_vacancy(message, state)
    if vacancy is None:
        return
    contact = message.contact
    saved = await sync_to_async(save_verified_phone)(
        user, contact_user_id=contact.user_id, phone_number=contact.phone_number
    )
    if not saved:
        text, markup = texts.foreign_contact()
        await message.answer(text, reply_markup=markup)
        return
    await state.update_data(phone=user.phone)
    text, markup = texts.phone_saved()
    await message.answer(text, reply_markup=markup)
    if vacancy.asks_document:
        await state.set_state(ApplyFlow.document)
        text, markup = texts.ask_document(vacancy)
        await message.answer(text, reply_markup=markup)
        return
    await _confirm(message, vacancy, state)


@router.message(ApplyFlow.contact)
async def no_contact(message: Message, state: FSMContext) -> None:
    if texts.is_cancel(message.text):
        await _cancel(message, state)
        return
    text, markup = texts.contact_needed()
    await message.answer(text, reply_markup=markup)


@router.message(ApplyFlow.document, F.photo)
async def document_photo(message: Message, bot: Bot, state: FSMContext) -> None:
    await _take_document(message, bot, state, message.photo[-1].file_id)


@router.message(ApplyFlow.document, F.document)
async def document_file(message: Message, bot: Bot, state: FSMContext) -> None:
    if not (message.document.mime_type or "").startswith("image/"):
        await message.answer(texts.photo_needed())
        return
    await _take_document(message, bot, state, message.document.file_id)


async def _take_document(message: Message, bot: Bot, state: FSMContext, file_id: str) -> None:
    vacancy = await _flow_vacancy(message, state)
    if vacancy is None:
        return
    downloaded = await bot.download(file_id)
    try:
        await sync_to_async(sanitize_image)(downloaded.getvalue(), max_side=2048)
    except DomainError as exc:
        await message.answer(str(exc))
        return
    await state.update_data(document=file_id)
    await _confirm(message, vacancy, state)


@router.callback_query(ApplyFlow.document, ApplyButton.filter(F.step == ApplyStep.SKIP))
async def skipped_document(
    query: CallbackQuery, callback_data: ApplyButton, state: FSMContext
) -> None:
    vacancy = await _vacancy(query, callback_data, state)
    if vacancy is None:
        return
    await query.answer()
    await _drop_buttons(query)
    await state.update_data(document="")
    await _confirm(query.message, vacancy, state)


@router.message(ApplyFlow.document)
async def no_document(message: Message, state: FSMContext) -> None:
    if texts.is_cancel(message.text):
        await _cancel(message, state)
        return
    await message.answer(texts.photo_needed())


# Sending ----------------------------------------------------------------------------------


async def _confirm(message: Message, vacancy: Vacancy, state: FSMContext) -> None:
    await state.set_state(ApplyFlow.confirm)
    text, markup = texts.summary(vacancy, await state.get_data())
    await message.answer(text, reply_markup=markup)


@router.callback_query(ApplyFlow.confirm, ApplyButton.filter(F.step == ApplyStep.SEND))
async def send_application(
    query: CallbackQuery, callback_data: ApplyButton, user: User, state: FSMContext, bot: Bot
) -> None:
    vacancy = await _vacancy(query, callback_data, state)
    if vacancy is None:
        return
    data = await state.get_data()
    document = None
    if data.get("document"):
        document = (await bot.download(data["document"])).getvalue()
    try:
        await sync_to_async(services.apply)(
            vacancy.pk,
            user,
            name=data.get("name", ""),
            phone=data.get("phone", ""),
            answers=data.get("answers", []),
            source=data.get("source", ""),
            document=document,
        )
    except DomainError as exc:
        await state.clear()
        await query.answer()
        await _drop_buttons(query)
        await query.message.answer(str(exc))
        return
    await state.clear()
    await query.answer()
    await _drop_buttons(query)
    await query.message.answer(await sync_to_async(texts.applied)(vacancy))


@router.message(ApplyFlow.confirm)
async def waiting_for_send(message: Message, state: FSMContext) -> None:
    if texts.is_cancel(message.text):
        await _cancel(message, state)
        return
    await message.answer(texts.use_buttons())


@router.message(ApplyFlow.intro)
async def waiting_for_apply(message: Message, state: FSMContext) -> None:
    if texts.is_cancel(message.text):
        await _cancel(message, state)
        return
    await message.answer(texts.use_buttons())


# Cancelling, and buttons that no longer belong to anything --------------------------------


@router.callback_query(ApplyButton.filter(F.step == ApplyStep.CANCEL))
async def cancel_button(query: CallbackQuery, callback_data: ApplyButton, state: FSMContext):
    data = await state.get_data()
    await query.answer()
    await _drop_buttons(query)
    if await state.get_state() is None or data.get("vacancy") != callback_data.v:
        return
    await _cancel(query.message, state)


@router.callback_query(ApplyButton.filter())
async def stale_button(query: CallbackQuery) -> None:
    """A button of a question already answered, a finished application or another vacancy."""
    await query.answer(texts.stale_button())


async def _cancel(message: Message, state: FSMContext) -> None:
    """Stop, and take the phone button away if it was showing."""
    await state.clear()
    await message.answer(texts.cancelled(), reply_markup=ReplyKeyboardRemove())


# Helpers ----------------------------------------------------------------------------------


async def _vacancy(
    query: CallbackQuery, button: ApplyButton, state: FSMContext, *, question: bool = False
) -> Vacancy | None:
    """The vacancy a tap belongs to, when it belongs to the application in progress (and, for
    `question`, to the question being asked); else the tap is answered as stale."""
    data = await state.get_data()
    vacancy = None
    if data.get("vacancy") == button.v:
        vacancy = await sync_to_async(services.vacancy_for_flow)(button.v)
    stale = vacancy is None or (
        question and (button.q != data.get("index") or button.q >= len(vacancy.questions or []))
    )
    if stale:
        await query.answer(texts.stale_button())
        return None
    return vacancy


async def _flow_vacancy(message: Message, state: FSMContext) -> Vacancy | None:
    """The vacancy of the application in progress; a vacancy that's gone ends it."""
    data = await state.get_data()
    vacancy = await sync_to_async(services.vacancy_for_flow)(data.get("vacancy") or 0)
    if vacancy is None:
        await state.clear()
        await message.answer(
            texts.unavailable(services.LinkState.GONE), reply_markup=ReplyKeyboardRemove()
        )
    return vacancy


async def _drop_buttons(query: CallbackQuery) -> None:
    with suppress(TelegramBadRequest):
        await query.message.edit_reply_markup(reply_markup=None)
