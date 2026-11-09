"""`/report`: the month's attendance report as Excel or PDF in the chat, for people who may
export, audited like the web app's download."""

import pytest
from aiogram.methods import SendDocument
from asgiref.sync import sync_to_async

from apps.audit.models import AuditLog
from davomat_bot.callbacks import ReportFile
from davomat_bot.tests import updates

pytestmark = pytest.mark.django_db(transaction=True)


def documents(bot) -> list[SendDocument]:
    return [request for request in bot.requests if isinstance(request, SendDocument)]


async def test_the_owner_gets_the_report_as_a_file(dp, bot, linked):
    await sync_to_async(linked)("Owner", 8501, first_name="Dilnoza")
    person = updates.tg_user(8501)

    await dp.feed_update(bot, updates.message(person, "/report"))

    [question] = bot.sent()
    assert question.text.startswith("<b>Attendance report</b>")
    labels = [[button.text for button in row] for row in question.reply_markup.inline_keyboard]
    assert labels == [
        ["This month · Excel", "This month · PDF"],
        ["Last month · Excel", "Last month · PDF"],
    ]

    await dp.feed_update(
        bot, updates.callback(person, ReportFile(period="month", format="xlsx").pack())
    )
    await dp.feed_update(
        bot, updates.callback(person, ReportFile(period="last_month", format="pdf").pack())
    )

    excel, pdf = documents(bot)
    assert excel.document.filename.startswith("attendance-by-person-")
    assert excel.document.filename.endswith(".xlsx")
    assert excel.document.data.startswith(b"PK")  # a zip: the workbook
    assert excel.caption.startswith("Attendance by person · ")
    assert pdf.document.filename.endswith(".pdf") and pdf.document.data.startswith(b"%PDF")
    logs = [
        log.details
        async for log in AuditLog.objects.filter(action="attendance.report_exported").order_by("pk")
    ]
    assert [(log["format"], log["via"]) for log in logs] == [
        ("xlsx", "telegram"),
        ("pdf", "telegram"),
    ]


async def test_without_the_export_permission_it_says_so(dp, bot, linked):
    await sync_to_async(linked)("Manager", 8502)  # sees attendance, may not export
    await sync_to_async(linked)("Employee", 8503)

    await dp.feed_update(bot, updates.message(updates.tg_user(8502), "/report"))
    await dp.feed_update(bot, updates.message(updates.tg_user(8503), "/report"))
    await dp.feed_update(
        bot,
        updates.callback(updates.tg_user(8503), ReportFile(period="month", format="xlsx").pack()),
    )

    manager, employee = bot.sent()
    assert manager.text == employee.text
    assert "export permission" in manager.text
    assert bot.answers()[-1].show_alert is True
    assert documents(bot) == []
    assert not await AuditLog.objects.filter(action="attendance.report_exported").aexists()


async def test_the_help_lists_report_for_those_who_may(dp, bot, linked):
    await sync_to_async(linked)("Owner", 8504)
    await sync_to_async(linked)("Manager", 8505)

    await dp.feed_update(bot, updates.message(updates.tg_user(8504), "/help"))
    await dp.feed_update(bot, updates.message(updates.tg_user(8505), "/help"))

    owner, manager = bot.sent()
    assert "/report" in owner.text
    assert "/report" not in manager.text and "/today" in manager.text
