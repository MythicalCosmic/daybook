"""What the bots say about the AI features: the voice-note card (v0.2 AI contract §6).

The card is one message that changes as the draft moves on: "Eshitayapman…" while it is heard,
"Tushunyapman…" while it is read, then the tasks understood with Create / Edit in the app /
Cancel, then "Created N tasks" with each task's Open button (and Undo for a while after an
automatic create). Both bots and the ai worker build it here, so it reads the same wherever it
is edited. Every text a person wrote or said is escaped.
"""

from aiogram import html
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from django.conf import settings
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.ai.callbacks import AIDraftCallback, DraftAction
from apps.ai.models import AIDraft
from apps.members.bot_messages import miniapp_url
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.tasks import bot_messages as task_messages
from apps.tasks import dates
from apps.tasks.models import Task

type BotMessage = tuple[str, InlineKeyboardMarkup | None]

TRANSCRIPT_SHORT = 200
TRANSCRIPT_MAX = 700
TITLE_ON_BUTTON = 28
OWNER_BOT = "owner"


def listening() -> str:
    return _("Listening…")


def understanding() -> str:
    return _("Understanding…")


def too_long(max_seconds: int) -> str:
    return _("The recording is too long: %(max)s seconds at most.") % {"max": max_seconds}


def too_big() -> str:
    return _("The recording is too big: 10 MB at most.")


def gone() -> str:
    return _("This voice note is no longer here.")


def voice_off(member: Membership, *, speech_missing: bool = False, typed_here: bool = True) -> str:
    """The one line for a voice message while voice tasks can't be used: typed tasks still
    work (in the employee bot: the owner bot takes no typed task, `typed_here` False), and
    whoever can switch them on is told where."""
    if speech_missing:
        if typed_here:
            text = _("I can't listen to voice messages here yet. Type the task instead.")
        else:
            text = _("I can't listen to voice messages here yet.")
        if member.has_perm(Perm.AI_CONFIGURE):
            text += " " + _("Voice needs a speech service on the server (AI_SPEECH_URL).")
        return text
    if typed_here:
        text = _("Voice tasks aren't switched on in this company. Type the task instead.")
    else:
        text = _("Voice tasks aren't switched on in this company.")
    if member.has_perm(Perm.AI_CONFIGURE):
        text += " " + _("You can switch them on in the dashboard: AI, then Agents.")
    return text


def draft_card(draft: AIDraft) -> BotMessage:
    """The card for the draft as it is now, in the active language."""
    match draft.status:
        case AIDraft.Status.QUEUED | AIDraft.Status.TRANSCRIBING:
            return listening(), None
        case AIDraft.Status.THINKING:
            return understanding(), None
        case AIDraft.Status.READY:
            return _ready(draft)
        case AIDraft.Status.APPLIED:
            return _applied(draft)
        case AIDraft.Status.FAILED:
            return _failed(draft), None
        case AIDraft.Status.EXPIRED:
            return _("This voice note is too old. Send it again."), None
        case _:
            if draft.undone_at is not None:
                return _("Taken back: the tasks were cancelled."), None
            return _("Cancelled."), None


def _ready(draft: AIDraft) -> BotMessage:
    items = draft.drafts
    company = draft.company
    now = timezone.localtime(timezone.now(), _zone(company))
    lang = _lang()
    people = _people(draft, [item.get("assignee_id") for item in items])
    allowed = _allowed(draft) if people else set()
    if not items:
        lines = [_("I didn't hear a task in this. Say who should do what, and by when.")]
    else:
        lines = [
            "<b>"
            + ngettext("Understood %(count)s task", "Understood %(count)s tasks", len(items))
            % {"count": len(items)}
            + "</b>",
            "",
        ]
        for number, item in enumerate(items, start=1):
            lines.append(_draft_line(number, item, people, now, lang))
            lines.extend(f"    {note}" for note in _problems(item, allowed, now))
    if draft.transcript:
        lines += ["", _quote(draft.transcript)]
    for question in draft.questions:
        lines.append(html.quote(question))
    rows = []
    if items:
        label = ngettext("Create %(count)s task", "Create %(count)s tasks", len(items)) % {
            "count": len(items)
        }
        rows.append([_callback(label, DraftAction.APPLY, draft)])
    if edit := _edit_button(draft):
        rows.append([edit])
    rows.append([_callback(_("Cancel"), DraftAction.CANCEL, draft)])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def _draft_line(number: int, item: dict, people: dict, now, lang: str) -> str:
    title = html.bold(html.quote(item.get("title") or _("Untitled task")))
    person = people.get(item.get("assignee_id"))
    who = html.quote(str(person)) if person else _("for you")
    parts = [who]
    if due := _moment(item.get("due_at")):
        local = timezone.localtime(due, now.tzinfo)
        parts.append(dates.short_due(local, now, lang))
    if item.get("priority") == "urgent":
        parts.append(_("urgent"))
    if item.get("proof") == "photo":
        parts.append(_("with a photo"))
    return f"{number}. {title} — " + " · ".join(parts)


def _problems(item: dict, allowed: set[int], now) -> list[str]:
    """The draft's problems in plain words (the same ones the apps show)."""
    notes = []
    guess = html.quote(item.get("assignee_guess") or "")
    problems = item.get("problems") or []
    assignee_id = item.get("assignee_id")
    if "ambiguous_assignee" in problems:
        notes.append(
            _("Several people are called “%(name)s”: choose one in the app.") % {"name": guess}
        )
    elif "no_assignee_match" in problems or (guess and not assignee_id):
        notes.append(
            _("“%(name)s” isn't among your people: for now it's for you.") % {"name": guess}
        )
    elif assignee_id and assignee_id not in allowed:
        notes.append(_("You can't give work to this person."))
    due = _moment(item.get("due_at"))
    if due is None:
        notes.append(_("No deadline was heard."))
    elif due <= now:
        notes.append(_("That time has already passed."))
    return [f"<i>{note}</i>" for note in notes]


def _applied(draft: AIDraft) -> BotMessage:
    tasks = list(
        Task.objects.filter(company_id=draft.company_id, pk__in=draft.applied_ids).select_related(
            "assignee__user"
        )
    )
    tasks.sort(key=lambda task: draft.applied_ids.index(task.pk))
    now = timezone.localtime(timezone.now(), _zone(draft.company))
    lang = _lang()
    header = ngettext("Created %(count)s task", "Created %(count)s tasks", len(tasks)) % {
        "count": len(tasks)
    }
    lines = [f"<b>{header}</b>", ""]
    for number, task in enumerate(tasks, start=1):
        mine = task.assignee_id == draft.created_by_id
        parts = [_("for you") if mine else html.quote(str(task.assignee))]
        if task.due_at:
            parts.append(dates.short_due(timezone.localtime(task.due_at, now.tzinfo), now, lang))
        lines.append(f"{number}. {html.bold(html.quote(task.title))} — " + " · ".join(parts))
    rows = [[button] for task in tasks if (button := _open_button(draft, task))]
    from apps.ai.drafts import can_undo

    if can_undo(draft):
        lines += ["", _("Created at once. You can undo it for 10 minutes.")]
        rows.append([_callback(_("Undo"), DraftAction.UNDO, draft)])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def _failed(draft: AIDraft) -> str:
    return {
        "speech_unavailable": _(
            "I can't listen to voice messages right now. Type the task instead."
        ),
        "audio_unreadable": _("I couldn't play this recording. Record it again."),
        "nothing_heard": _("I didn't hear any words. Record it again, a little closer."),
        "expired": _("This voice note is too old. Send it again."),
    }.get(draft.error_code, _("Something went wrong with this voice note. Send it again."))


def error_text(code: str) -> str:
    """What a draft's `error_code` means, for the apps' `error` field."""
    probe = AIDraft(error_code=code)
    return _failed(probe) if code else ""


def _open_button(draft: AIDraft, task: Task) -> InlineKeyboardButton | None:
    title = task.title if len(task.title) <= TITLE_ON_BUTTON else task.title[:TITLE_ON_BUTTON] + "…"
    label = _("Open: %(title)s") % {"title": title}
    if draft.tg_bot == OWNER_BOT:
        return _dashboard_button(label, f"c/{draft.company_id}/tasks?task={task.pk}")
    button = task_messages.open_button(task)
    return button.model_copy(update={"text": label})


def _edit_button(draft: AIDraft) -> InlineKeyboardButton | None:
    label = _("Edit in the app")
    if draft.tg_bot == OWNER_BOT:
        return _dashboard_button(label, f"c/{draft.company_id}/ai/voice?draft={draft.pk}")
    if not settings.EMPLOYEE_MINIAPP_URL.startswith("https://"):
        return None
    return InlineKeyboardButton(
        text=label, web_app=WebAppInfo(url=miniapp_url(f"drafts:{draft.pk}"))
    )


def _dashboard_button(label: str, path: str) -> InlineKeyboardButton | None:
    """A Mini App button into the dashboard (Telegram takes https links only)."""
    base = settings.DASHBOARD_URL
    if not base.startswith("https://"):
        return None
    return InlineKeyboardButton(
        text=label, web_app=WebAppInfo(url=base.rstrip("/") + "/" + path.lstrip("/"))
    )


def _callback(label: str, action: DraftAction, draft: AIDraft) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=label, callback_data=AIDraftCallback(action=action, id=draft.pk).pack()
    )


def _people(draft: AIDraft, ids) -> dict[int, Membership]:
    wanted = [pk for pk in ids if pk]
    if not wanted:
        return {}
    return {
        person.pk: person
        for person in Membership.objects.for_company(draft.company_id)
        .filter(pk__in=wanted)
        .select_related("user")
    }


def _allowed(draft: AIDraft) -> set[int]:
    from apps.ai.drafts import allowed_ids

    return allowed_ids(draft.created_by)


def _quote(text: str) -> str:
    text = " ".join(text.split())
    if len(text) > TRANSCRIPT_MAX:
        text = text[:TRANSCRIPT_MAX].rstrip() + "…"
    expandable = " expandable" if len(text) > TRANSCRIPT_SHORT else ""
    return f"<blockquote{expandable}>{html.quote(text)}</blockquote>"


def _moment(value):
    from apps.ai.drafts import moment

    return moment(value)


def _lang() -> str:
    """The reader's language for dates (the message is built under their translation)."""
    return dates.language(translation.get_language())


def _zone(company):
    from zoneinfo import ZoneInfo

    return ZoneInfo(company.timezone)


# The agents' messages ---------------------------------------------------------------------------


def late_task(task: Task, recipient: Membership, now) -> BotMessage:
    """The deadline watcher's note to whoever gave the task: Open, and "+1 hour" when they
    may change the task (a head without that right gets Open only)."""
    from apps.ai.callbacks import AILateCallback, LateAction
    from apps.tasks.rules import can_manage

    local_now = timezone.localtime(now, _zone(task.company))
    due = timezone.localtime(task.due_at, local_now.tzinfo)
    lines = [
        "<b>" + _("Late task") + "</b>",
        "",
        html.bold(html.quote(task.title)),
        _("For: %(name)s") % {"name": html.quote(str(task.assignee))},
        _("Deadline: %(when)s") % {"when": dates.short_due(due, local_now, _lang())},
        _("Late by: %(late)s") % {"late": task_messages.format_duration(now - task.due_at)},
    ]
    row = [task_messages.open_button(task)]
    if can_manage(task, recipient):
        row.append(
            InlineKeyboardButton(
                text=_("+1 hour"),
                callback_data=AILateCallback(action=LateAction.HOUR_MORE, task_id=task.pk).pack(),
            )
        )
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=[row])


def morning_plan(member: Membership, day: dict, now, *, summary: str = "") -> BotMessage:
    """A head's or manager's team today, in a few lines."""
    from apps.tasks.callbacks import ListCallback

    local_now = timezone.localtime(now, _zone(member.company))
    lang = _lang()
    lines = ["<b>" + _("Your team today") + "</b>"]
    if summary:
        lines += ["", html.quote(summary)]
    lines += ["", _("Due today: %(count)s") % {"count": day["due_today"]}]
    late = day["late"]
    lines.append(_("Late: %(count)s") % {"count": len(late)})
    for task in late[:3]:
        when = dates.short_due(timezone.localtime(task.due_at, local_now.tzinfo), local_now, lang)
        lines.append(f"    · {html.quote(task.title)} — {html.quote(str(task.assignee))} ({when})")
    if day["to_check"]:
        lines.append(_("Waiting for your check: %(count)s") % {"count": day["to_check"]})
    if day["off"]:
        names = ", ".join(html.quote(str(person)) for person in day["off"][:6])
        lines.append(_("Off today: %(names)s") % {"names": names})
    rows = []
    if day["to_check"]:
        label = _("To check (%(count)s)") % {"count": day["to_check"]}
        rows.append(
            [InlineKeyboardButton(text=label, callback_data=ListCallback(view="check").pack())]
        )
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def hour_more_done(task: Task, now) -> str:
    local_now = timezone.localtime(now, _zone(task.company))
    due = timezone.localtime(task.due_at, local_now.tzinfo)
    return _("New deadline for «%(title)s»: %(when)s") % {
        "title": html.quote(task.title),
        "when": dates.short_due(due, local_now, _lang()),
    }
