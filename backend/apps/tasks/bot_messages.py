"""Telegram texts and keyboards about tasks, used by the bot and by backend notifications.

Cards follow research R1 C1, C2, C3 and F3, without emoji (the owner's rule, 25.10.2026): the
bold title first, then short "Label: value" lines with the status and priority in words, at most
two buttons a row, and "Open in app" for what the chat can't do (comments, photos, "How to do
this"). Times are the company's, as R3 §1.7 writes them ("bugun, 18:30").
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import html
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from django.conf import settings
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.utils.translation import pgettext

from apps.companies.models import Company
from apps.core.money import format_money
from apps.members.bot_messages import BotMessage, miniapp_url, several_companies
from apps.members.models import Membership
from apps.reminders.policies import policy_for
from apps.tasks import dates, rules
from apps.tasks.callbacks import (
    DueCallback,
    DuePreset,
    ListCallback,
    PhotoCallback,
    PickCallback,
    QuickAddCallback,
    ReasonCallback,
    SnoozeCallback,
    StepCallback,
    TaskAction,
    TaskCallback,
    WhenCallback,
)
from apps.tasks.dates import EVENING
from apps.tasks.models import Proof, Task

LIST_LIMIT = 30  # one-off lists (onboarding, work handed back)
PAGE_SIZE = 8  # /tasks pages (research R1 C10)
TITLE_IN_LIST = 30
DESCRIPTION_SHORT = 200
DESCRIPTION_MAX = 700  # the rest is in the app; a photo caption holds 1024 characters in all
STEPS_ON_CARD = 6
STEP_LABEL = 34
NBSP = " "
PRIORITY_RANK = {"urgent": 0, "high": 1, "normal": 2, "low": 3}


# Lists -------------------------------------------------------------------------------------


def task_list(tasks: list[Task], now: datetime, *, page: int = 0, reviews: int = 0) -> BotMessage:
    """Everything still open for the person (audit B-1): sent back first, then late, today,
    later and without a deadline, urgent work first in each, and their work waiting for a check
    last. Eight a page, turned in place; "To check (3)" for reviewers (B-2)."""
    ordered = sorted(tasks, key=lambda task: _sort_key(task, now))
    footer = []
    if reviews:
        footer.append(_reviews_button(reviews))
    footer.append(_button(_("New task"), TaskAction.NEW))
    if not ordered:
        text = _("Nothing on your list. To add a task, tap «New task» or just type it.")
        return text, InlineKeyboardMarkup(inline_keyboard=[footer])
    counts = _counts(ordered, now)
    lines = [_("<b>Your tasks</b>: %(count)d") % {"count": len(ordered)}]
    parts = []
    if counts["late"]:
        parts.append(_("late: %(count)d") % {"count": counts["late"]})
    if counts["today"]:
        parts.append(_("today: %(count)d") % {"count": counts["today"]})
    if counts["later"]:
        parts.append(_("later: %(count)d") % {"count": counts["later"]})
    if counts["review"]:
        parts.append(_("being checked: %(count)d") % {"count": counts["review"]})
    if parts:
        lines.append(" · ".join(parts))
    lines.append(_("Tap a task to open it."))
    rows = _page_rows(ordered, now, "mine", page)
    rows.append(footer)
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def review_list(tasks: list[Task], now: datetime, *, page: int = 0) -> BotMessage:
    """Work waiting for my check, oldest first (audit B-2)."""
    if not tasks:
        return _("Nothing is waiting for your check."), InlineKeyboardMarkup(
            inline_keyboard=[[_button(_("My tasks"), TaskAction.LIST)]]
        )
    ordered = sorted(tasks, key=lambda task: (task.completed_at or task.created_at, task.pk))
    text = "\n".join(
        [
            _("<b>To check</b>: %(count)d") % {"count": len(ordered)},
            _("Tap one to see it, then confirm it or send it back."),
        ]
    )
    rows = _page_rows(ordered, now, "check", page, review=True)
    rows.append([_button(_("My tasks"), TaskAction.LIST)])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def work_came_back(name: str, tasks: list[Task], now: datetime) -> BotMessage:
    text = _("%(name)s has left the team. These tasks they had came back to you:") % {
        "name": html.quote(name)
    }
    rows = [[task_button(task, now)] for task in tasks[:LIST_LIMIT]]
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def task_button(task: Task, now: datetime, *, review: bool = False) -> InlineKeyboardButton:
    """A list entry that opens the task's card."""
    return _button(_list_label(task, now, review=review), TaskAction.OPEN, task.pk)


def list_button(label: str) -> InlineKeyboardButton:
    """Shows the person's task list."""
    return _button(label, TaskAction.LIST)


def display_title(task: Task) -> str:
    """The title as messages show it: with the card's key in front when the task is on a
    project's board ("RENO-14 · Paint the wall"), the project's key until it has a card."""
    if not task.project_id:
        return task.title
    card = getattr(task, "card", None)  # apps.projects' Card, one per task on a board
    key = f"{task.project.key}-{card.number}" if card is not None else task.project.key
    return f"{key} · {task.title}"


# The card ----------------------------------------------------------------------------------


def task_card(task: Task, member: Membership, now: datetime, header: str = "") -> BotMessage:
    return card_text(task, member, now, header), card_keyboard(task, member, now)


def card_text(task: Task, member: Membership, now: datetime, header: str = "") -> str:
    lines = [header, ""] if header else []
    lines.append(f"<b>{html.quote(display_title(task))}</b>")
    if task.description:
        lines.append(_description(task.description))
    lines.append("")
    lines.append(_("Status: %(status)s") % {"status": status_label(task)})
    if task.priority in (Task.Priority.URGENT, Task.Priority.HIGH):
        lines.append(_priority_line(task.get_priority_display()))
    if several_companies(member):
        lines.append(_("Company: %(company)s") % {"company": html.quote(task.company.name)})
    if task.due_at:
        lines.append(_("Due: %(when)s") % {"when": format_due(task, now)})
    if task.is_open and task.snoozed_until and task.snoozed_until > now:
        lines.append(_("Next reminder: %(time)s") % {"time": _clock(task, task.snoozed_until)})
    if task.reward:
        reward = format_money(task.reward, task.company.base_currency, translation.get_language())
        lines.append(_("Reward: +%(amount)s") % {"amount": reward.replace(" ", NBSP)})
    if task.kind == Task.Kind.ASSIGNED and task.created_by:
        lines.append(_("From: %(name)s") % {"name": html.quote(str(task.created_by))})
    if not rules.is_assignee(task, member):
        lines.append(_("For: %(name)s") % {"name": html.quote(str(task.assignee))})
    checklist = list(task.checklist.all())
    if checklist:
        done = sum(item.is_done for item in checklist)
        lines.append(
            _("Checklist: %(done)d of %(total)d") % {"done": done, "total": len(checklist)}
        )
    if task.proof != Proof.NONE and task.is_open:
        lines.append(_("Proof needed: %(proof)s") % {"proof": task.get_proof_display().lower()})
    if task.proof_text:
        lines.append(_("Report: %(text)s") % {"text": html.quote(task.proof_text)})
    if task.blocked_at:
        reason = Task.Blocker(task.blocker).label if task.blocker else ""
        note = f" · {html.quote(task.blocker_note)}" if task.blocker_note else ""
        lines.append(_("Can't do it: %(reason)s") % {"reason": reason} + note)
    if task.extension_until and task.is_open:
        lines.append(
            _("More time asked: %(when)s") % {"when": _short(task, task.extension_until, now)}
        )
    return "\n".join(lines)


def card_keyboard(task: Task, member: Membership, now: datetime) -> InlineKeyboardMarkup | None:
    """What this person can do from the card, two buttons a row at most (research R1 C2)."""
    actions = rules.allowed_actions(task, member)
    mine = rules.is_assignee(task, member)
    rows: list[list[InlineKeyboardButton]] = []
    if mine and task.is_open:
        rows += _step_rows(task)
        first = []
        if rules.Action.START in actions:
            first.append(_button(_("Start"), TaskAction.START, task.pk))
        if rules.Action.COMPLETE in actions:
            first.append(_button(_("Done"), TaskAction.DONE, task.pk, style="success"))
        rows.append(first)
        second = []
        if _may_snooze(task):
            second.append(_button(_("Snooze"), TaskAction.SNOOZE_MENU, task.pk))
        second.append(_button(_("Comment"), TaskAction.COMMENT, task.pk))
        rows.append(second)
        if task.kind != Task.Kind.PERSONAL and task.blocked_at is None:
            extra = []
            if task.due_at is not None and task.extension_until is None:
                extra.append(_button(_("More time"), TaskAction.MORE_TIME, task.pk))
            extra.append(_button(pgettext("task button", "Can't do it"), TaskAction.BLOCK, task.pk))
            rows.append(extra)
    elif mine and rules.can_undo(task, member, now):
        rows.append([_button(_("Undo"), TaskAction.UNDO, task.pk)])
    if rules.Action.CONFIRM in actions:
        rows.append(
            [
                _button(_("Confirm"), TaskAction.CONFIRM, task.pk, style="success"),
                _button(_("Send back"), TaskAction.RETURN, task.pk),
            ]
        )
    elif not mine and task.is_open:
        manager = []
        if rules.can_nudge(task, member):
            manager.append(_button(_("Remind now"), TaskAction.NUDGE, task.pk))
        if rules.can_reassign(task, member):
            manager.append(_button(_("Someone else"), TaskAction.REASSIGN, task.pk))
        if manager:
            rows.append(manager)
        more = []
        if rules.can_manage(task, member):
            more.append(_button(_("New time"), TaskAction.NEW_DUE, task.pk))
        if rules.can_manage(task, member) or task.created_by_id == member.pk:
            more.append(_button(_("Comment"), TaskAction.COMMENT, task.pk))
        rows.append(more)
    last = []
    if app := app_button(task):
        last.append(app)
    if mine:
        last.append(_button(_("My tasks"), TaskAction.LIST))
    if last:
        rows.append(last)
    rows = [row for row in rows if row]
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def app_button(task: Task, label: str | None = None) -> InlineKeyboardButton | None:
    """Opens the task's own screen in the mini app (research R1 C1). Telegram takes Mini App
    buttons in private chats only, with an https address."""
    if not settings.EMPLOYEE_MINIAPP_URL.startswith("https://"):
        return None
    return InlineKeyboardButton(
        text=label or _("Open in app"), web_app=WebAppInfo(url=miniapp_url(f"task:{task.pk}"))
    )


def open_button(task: Task) -> InlineKeyboardButton:
    """The task in the app when there is one, else its card right here in the chat."""
    return app_button(task) or _button(_("Open"), TaskAction.OPEN, task.pk)


def snooze_keyboard(task: Task, member: Membership) -> InlineKeyboardMarkup:
    """The card's keyboard turned into the snooze choices, like BotFather's menus (R1 C2, N4):
    reminders pause for 15 minutes or an hour; one's own task can move to tomorrow morning."""
    rows = []
    if _snoozes_left(task) > 0:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_("15 min"),
                    callback_data=SnoozeCallback(task_id=task.pk, preset="15m").pack(),
                ),
                InlineKeyboardButton(
                    text=_("1 hour"),
                    callback_data=SnoozeCallback(task_id=task.pk, preset="1h").pack(),
                ),
            ]
        )
    if task.kind == Task.Kind.PERSONAL:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_("Tomorrow 09:00"),
                    callback_data=SnoozeCallback(task_id=task.pk, preset="tomorrow_morning").pack(),
                )
            ]
        )
    rows.append([_button(_("Back"), TaskAction.BACK, task.pk)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def snoozed_note(task: Task) -> str:
    """The toast after a snooze: the reminders wait, the deadline doesn't move (R2 T15)."""
    if task.kind == Task.Kind.PERSONAL and task.snoozed_until is None:
        return _("Moved to %(when)s.") % {"when": _short(task, task.due_at, timezone.now())}
    values = {"time": _clock(task, task.snoozed_until), "due": _clock(task, task.due_at)}
    if task.kind == Task.Kind.PERSONAL:
        return _("Snoozed. Next reminder at %(time)s.") % values
    # Translators: %(time)s is a clock time; %(due)s reads like "bugun, 18:00".
    return _("Snoozed. Next reminder at %(time)s; the deadline stays %(due)s.") % values


def proof_prompt(task: Task, member: Membership, now: datetime) -> BotMessage:
    """The card, waiting for the proof (R1 C3): the same message, a line saying what to send,
    and only "Cancel"."""
    if task.proof == Proof.PHOTO:
        line = _("Send a photo (you can add a note).")
    elif task.proof == Proof.TEXT:
        line = _("Send a short report.")
    else:
        line = _("Send a photo or a short report.")
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[_button(_("Cancel"), TaskAction.STOP, task.pk)]]
    )
    return f"{card_text(task, member, now)}\n\n<b>{line}</b>", keyboard


def proof_request(task: Task) -> BotMessage:
    """The proof prompt as a message of its own, for a card that can't be edited."""
    title = {"title": html.quote(display_title(task))}
    if task.proof == Proof.PHOTO:
        text = _("Send a photo to complete <b>%(title)s</b>.") % title
    elif task.proof == Proof.TEXT:
        text = _("Send a short report to complete <b>%(title)s</b>.") % title
    else:
        text = _("Send a photo or a short report to complete <b>%(title)s</b>.") % title
    return text, stop_keyboard()


def unticked_prompt(task: Task, member: Membership, now: datetime, left: int) -> BotMessage:
    """Done with steps not ticked (audit X-5): ask first."""
    line = _("Steps not ticked yet: %(count)d. Tick them all and finish?") % {"count": left}
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [_button(_("Tick all and finish"), TaskAction.TICK_ALL, task.pk, style="success")],
            [_button(_("Back"), TaskAction.BACK, task.pk)],
        ]
    )
    return f"{card_text(task, member, now)}\n\n<b>{line}</b>", keyboard


def which_photo_task(tasks: list[Task], now: datetime) -> BotMessage:
    """A photo sent with nothing waiting for one (R1 C4): which task is it proof for?"""
    rows = [
        [
            InlineKeyboardButton(
                text=_list_label(task, now), callback_data=PhotoCallback(task_id=task.pk).pack()
            )
        ]
        for task in tasks
    ]
    rows.append(
        [InlineKeyboardButton(text=_("None of them"), callback_data=PhotoCallback().pack())]
    )
    return _("Which task is this photo for?"), InlineKeyboardMarkup(inline_keyboard=rows)


def comment_prompt(task: Task) -> BotMessage:
    """Ask for a comment, with the reply field open and Cancel kept (Bot API 10.3)."""
    # Translators: %(title)s is the task's title: let a carrier word take any case ending.
    text = _("Write your comment on <b>%(title)s</b>:") % {"title": html.quote(display_title(task))}
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[_button(_("Cancel"), TaskAction.STOP)]], force_reply=True
    )
    return text, keyboard


def return_reason_request() -> BotMessage:
    return _("What needs to be fixed? Send a short comment."), stop_keyboard()


def return_reasons() -> list[tuple[str, str]]:
    """Ready-made reasons for sending work back (research R1 C8, R2 T30): one tap sends it."""
    return [
        ("photo", _("Photo is unclear")),
        ("unfinished", _("Not finished")),
        ("wrong", _("Wrong item")),
    ]


def return_prompt(task: Task, member: Membership, now: datetime) -> BotMessage:
    """The checker's card, asking what to fix: a ready reason, or their own words."""
    line = _("What needs to be fixed? Tap a reason or write your own.")
    rows = [
        [
            InlineKeyboardButton(
                text=label,
                callback_data=ReasonCallback(kind="return", task_id=task.pk, code=code).pack(),
            )
        ]
        for code, label in return_reasons()
    ]
    rows.append([_button(_("Back"), TaskAction.BACK, task.pk)])
    text = f"{card_text(task, member, now)}\n\n<b>{line}</b>"
    return text, InlineKeyboardMarkup(inline_keyboard=rows, force_reply=True)


def block_keyboard(task: Task) -> InlineKeyboardMarkup:
    """Why it can't be done (research R2 T57): chips first, words only for "another reason"."""
    rows = [
        [
            InlineKeyboardButton(
                text=str(label),
                callback_data=ReasonCallback(kind="block", task_id=task.pk, code=code).pack(),
            )
        ]
        for code, label in Task.Blocker.choices
    ]
    rows.append([_button(_("Back"), TaskAction.BACK, task.pk)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def when_keyboard(task: Task, kind: str, now: datetime) -> InlineKeyboardMarkup:
    """New deadlines to pick: more time asked by the assignee (`kind` "more"), or a deadline a
    manager sets (`kind` "due"). "Type" asks for one in words (R2 §6)."""

    def choice(label: str, value: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=label, callback_data=WhenCallback(kind=kind, task_id=task.pk, choice=value).pack()
        )

    local = timezone.localtime(now, ZoneInfo(task.company.timezone))
    if kind == "more":
        first = [choice(_("+30 min"), "30m"), choice(_("+1 hour"), "1h")]
    else:
        first = [choice(_("In 1 hour"), "1h")]
        if local.time() < EVENING:
            first.append(choice(_("Today 18:00"), "today"))
    rows = [
        first,
        [choice(_("Tomorrow 09:00"), "tomorrow"), choice(_("Type a time"), "type")],
        [_button(_("Back"), TaskAction.BACK, task.pk)],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ask_typed_time(kind: str) -> BotMessage:
    if kind == "more":
        text = _("Until when? Write it: 18:30, tomorrow 9:00, Friday.")
    else:
        text = _("The new deadline? Write it: 18:30, tomorrow 9:00, Friday.")
    return text, stop_keyboard(placeholder=True)


def cancel_keyboard(task: Task) -> InlineKeyboardMarkup:
    """Cancelling can't be undone, so it asks first (research R2 T39)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button(_("Yes, cancel the task"), TaskAction.CANCEL_YES, task.pk, style="danger")],
            [_button(_("Back"), TaskAction.BACK, task.pk)],
        ]
    )


def person_picker(
    people: list[Membership], *, task_id: int = 0, page: int = 0, me: bool = False
) -> InlineKeyboardMarkup:
    """People to give work to, eight a page: "Me" first for a new task (audit X-7)."""
    pages = max(1, -(-len(people) // PAGE_SIZE))
    page = min(max(page, 0), pages - 1)
    rows = []
    if me and page == 0:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_("Me"), callback_data=PickCallback(task_id=task_id, member_id=0).pack()
                )
            ]
        )
    for person in people[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]:
        name = str(person)
        label = name if len(name) <= TITLE_IN_LIST else f"{name[: TITLE_IN_LIST - 1]}…"
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=PickCallback(task_id=task_id, member_id=person.pk).pack(),
                )
            ]
        )
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(
                InlineKeyboardButton(
                    text=pgettext("page", "Previous"),
                    callback_data=PickCallback(task_id=task_id, member_id=-1, page=page - 1).pack(),
                )
            )
        nav.append(
            InlineKeyboardButton(
                text=f"{page + 1}/{pages}",
                callback_data=PickCallback(task_id=task_id, member_id=-1, page=page).pack(),
            )
        )
        if page < pages - 1:
            nav.append(
                InlineKeyboardButton(
                    text=pgettext("page", "Next"),
                    callback_data=PickCallback(task_id=task_id, member_id=-1, page=page + 1).pack(),
                )
            )
        rows.append(nav)
    if task_id:
        rows.append([_button(_("Back"), TaskAction.BACK, task_id)])
    else:
        rows.append([_button(_("Cancel"), TaskAction.STOP)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ask_assignee() -> str:
    return _("Who is it for?")


# Notifications -----------------------------------------------------------------------------


def task_assigned(task: Task, now: datetime) -> BotMessage:
    if task.kind == Task.Kind.DAILY:
        # Translators: %(name)s is a person's name, Latin or Cyrillic: no case endings on it.
        header = _("<b>Today's routine task</b> · %(name)s")
    else:
        # Translators: %(name)s is a person's name, Latin or Cyrillic: no case endings on it.
        header = _("<b>New task</b> · %(name)s")
    header %= {"name": html.quote(str(task.created_by or ""))}
    return task_card(task, task.assignee, now, header.rstrip(" ·"))


def review_request(task: Task, reviewer: Membership, now: datetime) -> BotMessage:
    # Translators: %(name)s is a person's name, Latin or Cyrillic: no case endings on it.
    header = _("%(name)s finished a task. Please check it.") % {
        "name": html.quote(str(task.assignee))
    }
    return task_card(task, reviewer, now, f"<b>{header}</b>")


def task_completed(task: Task, creator: Membership, now: datetime) -> BotMessage:
    """To whoever gave the task, once it's done (audit B-19): two or three short lines and the
    open button, not the whole card; the proof photo, if any, travels with it."""
    # Translators: %(name)s is a person's name, Latin or Cyrillic: no case endings on it.
    lines = [_("<b>Task done</b> · %(name)s") % {"name": html.quote(str(task.assignee))}]
    title = html.quote(display_title(task))
    if task.due_at and task.completed_at and task.completed_at > task.due_at:
        late = format_duration(task.completed_at - task.due_at)
        title += " · " + _("late by %(duration)s") % {"duration": late}
    lines.append(title)
    if task.proof_text:
        lines.append(_("Report: %(text)s") % {"text": html.quote(_cut(task.proof_text))})
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=[[open_button(task)]])


def task_confirmed(task: Task, now: datetime) -> BotMessage:
    """To the assignee, once their work is accepted (audit B-19): who accepted it, the title
    and the reward, with the open button; their card itself is redrawn in place (C5)."""
    # Translators: %(name)s is a person's name, Latin or Cyrillic: no case endings on it.
    header = _("<b>Your task was accepted</b> · %(name)s") % {
        "name": html.quote(str(task.confirmed_by or ""))
    }
    lines = [header.rstrip(" ·"), html.quote(display_title(task))]
    if task.reward:
        reward = format_money(task.reward, task.company.base_currency, translation.get_language())
        lines.append(_("Reward: +%(amount)s") % {"amount": reward.replace(" ", NBSP)})
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=[[open_button(task)]])


def task_returned(task: Task, reason: str, now: datetime) -> BotMessage:
    header = _("Your task was sent back: %(reason)s") % {"reason": html.quote(reason)}
    return task_card(task, task.assignee, now, header)


def nudge(task: Task, by: Membership, now: datetime) -> BotMessage:
    """The dashboard's "Nudge now": a friendly push from a named person."""
    # Translators: %(name)s is a person's name, Latin or Cyrillic: no case endings on it.
    header = _("%(name)s is waiting for this task.") % {"name": html.quote(str(by))}
    return task_card(task, task.assignee, now, header)


def comment_notice(
    task: Task, text: str, author: Membership | None, recipient: Membership, mentioned: bool
) -> BotMessage:
    """A comment reaches the people on the task (research R2 T33). Replying to this message
    adds a comment (R1 Q2); the reply button asks for one."""
    name = html.quote(str(author)) if author else "—"
    if mentioned:
        # Translators: %(name)s is a person's name, Latin or Cyrillic: no case endings on it.
        header = _("<b>%(name)s mentioned you</b>") % {"name": name}
    else:
        # Translators: %(name)s is a person's name, Latin or Cyrillic: no case endings on it.
        header = _("<b>New comment</b> · %(name)s") % {"name": name}
    lines = [header, f"<b>{html.quote(display_title(task))}</b>"]
    if several_companies(recipient):
        lines.append(_("Company: %(company)s") % {"company": html.quote(task.company.name)})
    lines.append(_quote(text))
    rows = [[_button(_("Reply"), TaskAction.COMMENT, task.pk), open_button(task)]]
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def due_changed(task: Task, old_due: datetime | None, by: Membership, now: datetime) -> BotMessage:
    """The deadline moved (audit X-6): the card, saying what it was."""
    # Translators: %(name)s is a person's name, Latin or Cyrillic: no case endings on it.
    header = _("<b>New deadline</b> · %(name)s") % {"name": html.quote(str(by))}
    if old_due is not None:
        # Translators: %(when)s reads like "bugun, 18:00" or "25-okt, 18:30".
        header += "\n" + _("It was: %(when)s") % {"when": _short(task, old_due, now)}
    return task_card(task, task.assignee, now, header)


def task_cancelled(task: Task, by: Membership) -> BotMessage:
    text = "\n".join(
        [
            # Translators: %(name)s is a person's name, Latin or Cyrillic: no case endings on it.
            _("<b>Task cancelled</b> · %(name)s") % {"name": html.quote(str(by))},
            f"<s>{html.quote(display_title(task))}</s>",
        ]
    )
    rows = [[_button(_("My tasks"), TaskAction.LIST)]]
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def task_taken_away(task: Task, by: Membership) -> BotMessage:
    text = "\n".join(
        [
            # Translators: %(name)s is a person's name, Latin or Cyrillic: no case endings on it.
            _("<b>Given to someone else</b> · %(name)s") % {"name": html.quote(str(by))},
            f"<s>{html.quote(display_title(task))}</s>",
            # Translators: %(name)s is a person's name, Latin or Cyrillic: no case endings on it.
            _("Now it's for: %(name)s") % {"name": html.quote(str(task.assignee))},
        ]
    )
    rows = [[_button(_("My tasks"), TaskAction.LIST)]]
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def blocked_notice(task: Task, giver: Membership, now: datetime) -> BotMessage:
    """Someone can't do a task (research R2 T57): the reason on its own line, and what to do."""
    # Translators: %(name)s is a person's name, Latin or Cyrillic: no case endings on it.
    header = _("<b>%(name)s can't do this task</b>") % {"name": html.quote(str(task.assignee))}
    text = card_text(task, giver, now, header)
    rows = [
        [
            _button(_("Someone else"), TaskAction.REASSIGN, task.pk),
            _button(_("New time"), TaskAction.NEW_DUE, task.pk),
        ],
        [_button(_("Cancel task"), TaskAction.CANCEL, task.pk, style="danger")],
    ]
    if app := app_button(task):
        rows[-1].append(app)
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def blocker_answer(task: Task, action: str, by: Membership, now: datetime) -> BotMessage:
    """What the person who couldn't do it hears back."""
    name = {"name": html.quote(str(by))}
    if action == "reassign":
        return task_taken_away(task, by)
    if action == "cancel":
        return task_cancelled(task, by)
    # Translators: %(name)s is a person's name, Latin or Cyrillic: no case endings on it.
    return task_card(task, task.assignee, now, _("<b>New deadline</b> · %(name)s") % name)


def extension_answer(task: Task, approved: bool, by: Membership, now: datetime) -> BotMessage:
    name = {"name": html.quote(str(by))}
    if approved:
        # Translators: %(name)s is a person's name, Latin or Cyrillic: no case endings on it.
        header = _("<b>More time given</b> · %(name)s") % name
    else:
        # Translators: %(name)s is a person's name, Latin or Cyrillic: no case endings on it.
        header = _("<b>The deadline stays</b> · %(name)s") % name
    return task_card(task, task.assignee, now, header)


def copy_of(task: Task, member: Membership, kind: str, now: datetime) -> BotMessage:
    """A task message in someone's chat, drawn again as the task is now (research R1 C5): its
    buttons are what this person may still do, and the first line says how it ended. Until
    then, a "can't do it" stays that question and a late alert stays an alert."""
    if task.is_open and kind == "blocked" and task.blocked_at:
        return blocked_notice(task, member, now)
    if task.is_open and kind == "escalation" and task.due_at and task.due_at < now:
        from apps.reminders.bot_messages import escalation  # it builds on this module

        return escalation(task, now, member)
    return task_card(task, member, now, _copy_header(task, member, kind, now))


def _copy_header(task: Task, member: Membership, kind: str, now: datetime) -> str:
    if task.status == Task.Status.CANCELLED:
        return _("<b>Task cancelled</b>")
    if kind == "card" and member.pk not in (task.assignee_id, task.created_by_id):
        return _("<b>Given to someone else</b>")
    if kind not in ("review", "escalation", "blocked"):
        return ""
    if task.status == Task.Status.DONE:
        if header := accepted_header(task):
            return header
        if task.confirmed_by_id:
            # Translators: %(name)s is a person's name, Latin or Cyrillic: no case endings on it.
            return _("<b>Accepted</b> · %(name)s") % {"name": html.quote(str(task.confirmed_by))}
        done = {"time": _clock(task, task.completed_at)}
        if task.due_at and task.completed_at > task.due_at:
            done["late"] = format_duration(task.completed_at - task.due_at)
            # Translators: %(time)s is a clock time (14:30); %(late)s a length (25 min, 1 h 5 min).
            return _("<b>Done</b> · %(time)s, %(late)s late") % done
        return _("<b>Done</b> · %(time)s") % done
    if kind == "review":
        if task.status == Task.Status.RETURNED:
            return _("<b>Sent back</b>")
        if task.status == Task.Status.REVIEW:
            # Translators: %(name)s is a person's name, Latin or Cyrillic: no case endings on it.
            header = _("%(name)s finished a task. Please check it.") % {
                "name": html.quote(str(task.assignee))
            }
            return f"<b>{header}</b>"
    return ""


def onboarding_welcome(member: Membership, tasks: list[Task], now: datetime) -> BotMessage:
    """A new person's first tasks, right after they were let in."""
    lines = [
        _("Welcome to %(company)s, %(name)s!")
        % {
            "company": html.quote(member.company.name),
            "name": html.quote(member.first_name or str(member)),
        },
        _("Here are your first tasks to get started. Tap one to open it."),
    ]
    rows = [[task_button(task, now)] for task in tasks[:LIST_LIMIT]]
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


# New tasks ---------------------------------------------------------------------------------


def ask_title() -> BotMessage:
    text = _("What needs to be done? You can say when too, e.g. «Order insulin tomorrow 18:00 !!».")
    return text, stop_keyboard(placeholder=True)


def ask_due(company: Company, now: datetime, *, error: bool = False) -> BotMessage:
    local_now = timezone.localtime(now, ZoneInfo(company.timezone))
    presets = [(_("In an hour"), DuePreset.IN_AN_HOUR)]
    if local_now.time() < EVENING:
        presets.append((_("Today 18:00"), DuePreset.TODAY_EVENING))
    presets += [
        (_("Tomorrow 09:00"), DuePreset.TOMORROW_MORNING),
        (_("No deadline"), DuePreset.NONE),
    ]
    buttons = [
        InlineKeyboardButton(text=label, callback_data=DueCallback(preset=preset).pack())
        for label, preset in presets
    ]
    rows = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
    rows.append([_button(_("Cancel"), TaskAction.STOP)])
    if error:
        text = _("I didn't catch the time. Try: 18:30, tomorrow 9:00, Friday, in 2 hours.")
    else:
        text = _("When is it due? Pick one or write it: 18:30, tomorrow 9:00, Friday.")
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def due_passed(when: str) -> BotMessage:
    """An explicit "today 18:00" typed at 19:10 (research R2 §6.1): offer tomorrow."""
    # Translators: %(when)s is a clock time such as 08:00.
    text = _("%(when)s has already passed today. Tomorrow at the same time?") % {"when": when}
    rows = [
        [
            InlineKeyboardButton(
                text=_("Tomorrow, %(when)s") % {"when": when},
                callback_data=QuickAddCallback(action="tomorrow").pack(),
            ),
            InlineKeyboardButton(
                text=_("Another time"), callback_data=QuickAddCallback(action="time").pack()
            ),
        ],
        [_button(_("Cancel"), TaskAction.STOP)],
    ]
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def quick_add_preview(
    title: str,
    due: str | None,
    *,
    found: bool,
    assignee: str | None = None,
    repeat: str | None = None,
    urgent: bool = False,
    note: str = "",
) -> BotMessage:
    """What the bot understood before it saves (research R2 T2): the title, the deadline with
    its weekday and date, and "Not a date" to keep the words as they were typed."""
    lines = [f"<b>{html.quote(title)}</b>"]
    if due:  # after "Muddat:", so lowercase (R3 §1.6): "Muddat: ertaga, 27-oktabr …"
        due = due[:1].lower() + due[1:]
    # Translators: %(when)s reads like "ertaga, 18:00 (juma, 26-okt)".
    lines.append(_("Due: %(when)s") % {"when": due} if due else _("No deadline"))
    if note:
        lines.append(note)
    if repeat:
        # Translators: %(repeat)s is how often, e.g. "Every day".
        lines.append(_("Repeats: %(repeat)s") % {"repeat": repeat})
    if urgent:
        lines.append(_priority_line(Task.Priority.URGENT.label))
    if assignee:
        # Translators: %(name)s is a person's name, Latin or Cyrillic: no case endings on it.
        lines.append(_("For: %(name)s") % {"name": html.quote(assignee)})
    first = [
        InlineKeyboardButton(
            text=_("Save"),
            callback_data=QuickAddCallback(action="save").pack(),
            style="success",
        ),
        InlineKeyboardButton(
            text=_("Change time"), callback_data=QuickAddCallback(action="time").pack()
        ),
    ]
    second = []
    if found:
        second.append(
            InlineKeyboardButton(
                text=_("Not a date"), callback_data=QuickAddCallback(action="literal").pack()
            )
        )
    second.append(_button(_("Cancel"), TaskAction.STOP))
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=[first, second])


def stop_keyboard(*, placeholder: bool = False) -> InlineKeyboardMarkup:
    """Just "Cancel"; with `placeholder` the reply field opens too (Bot API 10.3)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[_button(_("Cancel"), TaskAction.STOP)]],
        force_reply=True if placeholder else None,
    )


# Wording -----------------------------------------------------------------------------------


def format_due(task: Task, now: datetime) -> str:
    """The deadline for the middle of a line ("bugun, 18:30"), and how late it is."""
    text = _short(task, task.due_at, now)
    if task.is_overdue(now):
        text += " · " + _("late by %(duration)s") % {"duration": format_duration(now - task.due_at)}
    return text


def format_duration(delta: timedelta) -> str:
    """ "25 min", "1 h", "1 h 5 min", "2 d", "2 d 3 h": never "1 h 0 min" (audit B-14)."""
    minutes = max(0, int(delta.total_seconds() // 60))
    if minutes < 60:
        return _("%(minutes)d min") % {"minutes": minutes}
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        if not minutes:
            return _("%(hours)d h") % {"hours": hours}
        return _("%(hours)d h %(minutes)d min") % {"hours": hours, "minutes": minutes}
    days, hours = divmod(hours, 24)
    if not hours:
        return _("%(days)d d") % {"days": days}
    return _("%(days)d d %(hours)d h") % {"days": days, "hours": hours}


def _short(task: Task, moment: datetime, now: datetime) -> str:
    tz = ZoneInfo(task.company.timezone)
    return dates.short_due(
        timezone.localtime(moment, tz), timezone.localtime(now, tz), translation.get_language()
    )


def _clock(task: Task, moment: datetime) -> str:
    return timezone.localtime(moment, ZoneInfo(task.company.timezone)).strftime("%H:%M")


def _description(text: str) -> str:
    """The first ~200 characters; the rest folded away (Bot API 7.4) and capped, so a card
    stays short and fits a photo caption."""
    text = text.strip()
    if len(text) <= DESCRIPTION_SHORT:
        return html.quote(text)
    cut = text.rfind(" ", 0, DESCRIPTION_SHORT)
    cut = cut if cut > DESCRIPTION_SHORT // 2 else DESCRIPTION_SHORT
    rest = text[cut:].strip()
    if len(text) > DESCRIPTION_MAX:
        rest = rest[: DESCRIPTION_MAX - cut].rstrip() + "…"
    return f"{html.quote(text[:cut])}…\n<blockquote expandable>{html.quote(rest)}</blockquote>"


def _quote(text: str) -> str:
    text = text.strip()
    if len(text) > DESCRIPTION_MAX:
        text = text[:DESCRIPTION_MAX].rstrip() + "…"
    expandable = " expandable" if len(text) > DESCRIPTION_SHORT else ""
    return f"<blockquote{expandable}>{html.quote(text)}</blockquote>"


def _step_rows(task: Task) -> list[list[InlineKeyboardButton]]:
    """The checklist on the card (audit X-5): one tap ticks a step, in place. A ticked step
    says so in words ("Bajarildi: …") and is green where Telegram colours buttons."""
    rows = []
    for item in list(task.checklist.all())[:STEPS_ON_CARD]:
        text = item.text if len(item.text) <= STEP_LABEL else f"{item.text[: STEP_LABEL - 1]}…"
        if item.is_done:
            # Translators: on a checklist button; %(step)s is the step's own text.
            text = pgettext("checklist step", "Done: %(step)s") % {"step": text}
        rows.append(
            [
                InlineKeyboardButton(
                    text=text,
                    callback_data=StepCallback(task_id=task.pk, item_id=item.pk).pack(),
                    style="success" if item.is_done else None,
                )
            ]
        )
    return rows


def _may_snooze(task: Task) -> bool:
    if task.due_at is None or task.blocked_at is not None:
        return False
    return task.kind == Task.Kind.PERSONAL or _snoozes_left(task) > 0


def _snoozes_left(task: Task) -> int:
    return max(0, policy_for(task).max_snoozes - task.snooze_count)


def _counts(tasks: list[Task], now: datetime) -> dict[str, int]:
    """For the list's header: late, due today, later (or no deadline), being checked."""
    counts = dict.fromkeys(("late", "today", "later", "review"), 0)
    tz = ZoneInfo(tasks[0].company.timezone) if tasks else None
    today = timezone.localtime(now, tz).date() if tz else None
    for task in tasks:
        if task.status == Task.Status.REVIEW:
            counts["review"] += 1
        elif task.is_overdue(now):
            counts["late"] += 1
        elif task.due_at is not None and timezone.localtime(task.due_at, tz).date() == today:
            counts["today"] += 1
        else:
            counts["later"] += 1
    return counts


def _group(task: Task, now: datetime) -> str:
    if task.status == Task.Status.REVIEW:
        return "review"
    if task.status == Task.Status.RETURNED:
        return "returned"
    if task.due_at is None:
        return "none"
    if task.due_at < now:
        return "late"
    tz = ZoneInfo(task.company.timezone)
    if timezone.localtime(task.due_at, tz).date() == timezone.localtime(now, tz).date():
        return "today"
    return "later"


_ORDER = {"returned": 0, "late": 1, "today": 2, "later": 3, "none": 4, "review": 5}


def _sort_key(task: Task, now: datetime) -> tuple:
    due = task.due_at.timestamp() if task.due_at else float("inf")
    return (_ORDER[_group(task, now)], PRIORITY_RANK.get(task.priority, 2), due, task.pk)


def _page_rows(
    tasks: list[Task], now: datetime, view: str, page: int, *, review: bool = False
) -> list[list[InlineKeyboardButton]]:
    pages = max(1, -(-len(tasks) // PAGE_SIZE))
    page = min(max(page, 0), pages - 1)
    chunk = tasks[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    rows = [[task_button(task, now, review=review)] for task in chunk]
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(
                InlineKeyboardButton(
                    text=pgettext("page", "Previous"),
                    callback_data=ListCallback(view=view, page=page - 1).pack(),
                )
            )
        nav.append(
            InlineKeyboardButton(
                text=f"{page + 1}/{pages}",
                callback_data=ListCallback(view=view, page=page).pack(),
            )
        )
        if page < pages - 1:
            nav.append(
                InlineKeyboardButton(
                    text=pgettext("page", "Next"),
                    callback_data=ListCallback(view=view, page=page + 1).pack(),
                )
            )
        rows.append(nav)
    return rows


def _reviews_button(count: int) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=_("To check (%(count)d)") % {"count": count},
        callback_data=ListCallback(view="check").pack(),
    )


def _list_label(task: Task, now: datetime, *, review: bool = False) -> str:
    """The title first, then when (audit B-12), then a word for what stands out: "Muzlatgich
    harorati… · 09:00, kechikkan". Words, not marks: sent back, being checked, late, urgent."""
    full = display_title(task)
    note = "" if review else _list_note(task, now)
    limit = TITLE_IN_LIST - (len(note) // 2 if note else 0)
    title = full if len(full) <= limit else f"{full[: limit - 1].rstrip()}…"
    if review:
        when = str(task.assignee)
    elif task.due_at is None:
        when = ""
    else:
        tz = ZoneInfo(task.company.timezone)
        due, today = timezone.localtime(task.due_at, tz), timezone.localtime(now, tz)
        when = f"{due:%H:%M}" if due.date() == today.date() else _short(task, task.due_at, now)
    tail = ", ".join(part for part in (when, note) if part)
    return f"{title} · {tail}" if tail else title


def _list_note(task: Task, now: datetime) -> str:
    """The one word a list entry adds after its time, for what needs attention first."""
    if task.status == Task.Status.RETURNED:
        return pgettext("task list", "sent back")
    if task.status == Task.Status.REVIEW:
        return pgettext("task list", "being checked")
    if task.is_open and task.is_overdue(now):
        return pgettext("task list", "late")
    if task.priority == Task.Priority.URGENT:
        return pgettext("task list", "urgent")
    return ""


def _priority_line(priority: str) -> str:
    # Translators: %(priority)s is "Urgent" or "High", as the task's priority reads.
    return _("Priority: %(priority)s") % {"priority": priority}


def _cut(text: str, limit: int = DESCRIPTION_SHORT) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else f"{text[: limit - 1].rstrip()}…"


def _button(
    text: str, action: TaskAction, task_id: int = 0, *, style: str | None = None
) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text,
        callback_data=TaskCallback(action=action, task_id=task_id).pack(),
        style=style,
    )


# Accepted automatically (PLAN-OWNER §15.3) ---------------------------------------------------


def status_label(task: Task) -> str:
    """The card's status: "Accepted" for finished work nobody had to check (the person who did
    it reads that at once, not "sent for checking"), else the task's status."""
    if rules.accepted_automatically(task):
        return pgettext("task status", "Accepted")
    return task.get_status_display()


def accepted_note(task: Task) -> str | None:
    """What finishing says when the work was accepted at once; None when it wasn't."""
    if rules.accepted_automatically(task):
        return pgettext("task status", "Accepted")
    return None


def accepted_header(task: Task) -> str:
    """The checker's copy of work the company's wait accepted: nobody reviewed it in time."""
    if rules.accepted_automatically(task) and task.confirmed_at is not None:
        return _("<b>Accepted automatically</b> · nobody checked it in time")
    return ""


# A head's team (apps.members.departments) ---------------------------------------------------

TEAM_LATE_SHOWN = 8


def team_summary(head: Membership) -> BotMessage:
    """ "My team": each of the head's people with their open and late work, then the late tasks
    to open or remind about, and what waits for the head's check."""
    from apps.members.departments import team_ids
    from apps.tasks import queries

    now = timezone.now()
    people = list(
        Membership.objects.filter(pk__in=team_ids(head), status=Membership.Status.APPROVED)
        .select_related("user", "position")
        .order_by("first_name", "last_name")
    )
    lines = [_("<b>My team</b>")]
    if not people:
        lines.append(_("Nobody is in your departments yet."))
        return "\n".join(lines), None
    open_work = Task.objects.filter(assignee__in=people, status__in=Task.OPEN_STATUSES).exclude(
        kind=Task.Kind.PERSONAL
    )
    counts: dict[int, list[int]] = {person.pk: [0, 0] for person in people}
    for assignee_id, due_at in open_work.values_list("assignee_id", "due_at"):
        counts[assignee_id][0] += 1
        if due_at is not None and due_at < now:
            counts[assignee_id][1] += 1
    lines.append("")
    for person in people:
        total, late = counts[person.pk]
        facts = _("Open: %(count)d") % {"count": total}
        if late:
            facts += " · " + _("late: %(count)d") % {"count": late}
        lines.append(f"{html.quote(str(person))} — {facts}")
    late_tasks = list(
        open_work.filter(due_at__lt=now)
        .select_related("assignee__user")
        .order_by("due_at")[:TEAM_LATE_SHOWN]
    )
    rows = []
    if late_tasks:
        lines += ["", _("<b>Late now</b>")]
        for task in late_tasks:
            lines.append(
                _("%(task)s — %(name)s, %(late)s late")
                % {
                    "task": html.quote(display_title(task)),
                    "name": html.quote(str(task.assignee)),
                    "late": format_duration(now - task.due_at),
                }
            )
            rows.append(
                [
                    InlineKeyboardButton(
                        text=display_title(task)[:32],
                        callback_data=TaskCallback(action=TaskAction.OPEN, task_id=task.pk).pack(),
                    ),
                    InlineKeyboardButton(
                        text=_("Remind"),
                        callback_data=TaskCallback(action=TaskAction.NUDGE, task_id=task.pk).pack(),
                    ),
                ]
            )
    waiting = queries.awaiting_review_by(head).count()
    if waiting:
        lines += ["", _("To check: %(count)d") % {"count": waiting}]
        rows.append(
            [
                InlineKeyboardButton(
                    text=_("To check"),
                    callback_data=TaskCallback(action=TaskAction.REVIEWS).pack(),
                )
            ]
        )
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
