"""`/report`: the attendance report by person as Excel or PDF, this month or last, sent to the
chat, the same file the web app's export gives (apps.attendance.reports), in the person's
branches. It needs `attendance.view` and `data.export`, and every file sent is audited.
"""

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from asgiref.sync import sync_to_async
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from apps.attendance import reports
from apps.attendance.audit_actions import AttendanceAction
from apps.audit import services as audit
from apps.console.ranges import parse_range
from apps.members import scope
from apps.members.models import Membership
from davomat_bot import bot_messages
from davomat_bot.callbacks import ReportFile
from davomat_bot.middlewares.person import Person

router = Router(name="report")
router.message.filter(F.chat.type == ChatType.PRIVATE)
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)

KIND = bot_messages.REPORT_KIND
PERIODS = ("month", "last_month")
FORMATS = ("xlsx", "pdf")


def keyboard() -> InlineKeyboardMarkup:
    labels = {"month": _("This month"), "last_month": _("Last month")}
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{labels[period]} · {'Excel' if kind == 'xlsx' else 'PDF'}",
                    callback_data=ReportFile(period=period, format=kind).pack(),
                )
                for kind in FORMATS
            ]
            for period in PERIODS
        ]
    )


@router.message(Command("report"))
async def cmd_report(message: Message, person: Person, state: FSMContext) -> None:
    await state.clear()
    if person.member is None:
        await message.answer(bot_messages.not_linked())
        return
    if not bot_messages.may_download(person.member):
        await message.answer(no_export())
        return
    await message.answer(
        _("<b>Attendance report</b>\nBy person, in your branches. Which one?"),
        reply_markup=keyboard(),
    )


def no_export() -> str:
    return _("Downloading reports needs the export permission. Your own month: /me")


@router.callback_query(ReportFile.filter())
async def send_report(callback: CallbackQuery, callback_data: ReportFile, person: Person) -> None:
    if person.member is None:
        await callback.answer(bot_messages.not_linked()[:200], show_alert=True)
        return
    period = callback_data.period if callback_data.period in PERIODS else "month"
    kind = callback_data.format if callback_data.format in FORMATS else "xlsx"
    made = await sync_to_async(_file)(person.member, period, kind, person.language)
    if made is None:
        await callback.answer(no_export()[:200], show_alert=True)
        return
    content, name, caption = made
    await callback.answer(_("Here it is"))
    await callback.message.answer_document(
        BufferedInputFile(content, filename=name), caption=caption
    )


def _file(member: Membership, period: str, kind: str, language: str):
    """(bytes, file name, caption) of the report, or None without the right to it."""
    if not bot_messages.may_download(member):
        return None
    company = member.company
    with translation.override(language):
        days = parse_range({"preset": period}, company, timezone.now())
        ask = reports.Ask(
            days.start,
            days.end,
            scope.branch_ids(member),
            None,
            [],
            [],
        )
        data = reports.build(company, KIND, ask)
        if kind == "xlsx":
            content = reports.xlsx(KIND, data, company=company, ask=ask)
        else:
            content = reports.pdf(KIND, data, company=company, ask=ask, language=language)
        caption = f"{reports.LABELS[KIND]} · {days.start:%d.%m}–{days.end:%d.%m.%Y}"
    audit.record(
        AttendanceAction.REPORT_EXPORTED,
        company_id=company.pk,
        actor=member.user,
        target=company,
        report=KIND,
        format=kind,
        start=days.start.isoformat(),
        end=days.end.isoformat(),
        branches=[],
        departments=[],
        via="telegram",
    )
    return content, reports.filename(KIND, company, ask, kind), caption
