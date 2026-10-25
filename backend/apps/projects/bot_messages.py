"""What the bots say about projects (Uzbek first through gettext; buttons over typing).

The employee bot's update conversation (`/start upd_<project id>`, linked from the weekly
nudge): pick how it's going, then a line or two, or skip.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from django.utils.html import escape
from django.utils.translation import gettext as _

from apps.members.bot_messages import BotMessage, miniapp_url
from apps.projects.callbacks import ProjectUpdateCallback, UpdateStep
from apps.projects.models import Health, Project, ProjectUpdate

# The health buttons' colours; the words say it as well ("On track", "At risk", "Off track").
HEALTH_STYLES = {Health.ON_TRACK: "success", Health.OFF_TRACK: "danger"}


def health_label(health: str) -> str:
    return str(Health(health).label)


def _title(project: Project) -> str:
    return f"<b>{escape(project.key)}</b> · {escape(project.name)}"


def ask_health(project: Project) -> BotMessage:
    text = _("How is %(project)s going this week?") % {"project": _title(project)}
    buttons = [
        InlineKeyboardButton(
            text=health_label(health),
            callback_data=ProjectUpdateCallback(
                step=UpdateStep.HEALTH, project_id=project.pk, health=health
            ).pack(),
            style=HEALTH_STYLES.get(health),
        )
        for health in Health.values
    ]
    stop = InlineKeyboardButton(
        text=_("Not now"),
        callback_data=ProjectUpdateCallback(step=UpdateStep.STOP, project_id=project.pk).pack(),
    )
    return text, InlineKeyboardMarkup(inline_keyboard=[[b] for b in buttons] + [[stop]])


def ask_text(project: Project, health: str) -> BotMessage:
    text = _("%(health)s. Now one or two lines for the team: what's done, what's blocking?") % {
        "health": health_label(health)
    }
    skip = InlineKeyboardButton(
        text=_("Post without text"),
        callback_data=ProjectUpdateCallback(
            step=UpdateStep.SKIP, project_id=project.pk, health=health
        ).pack(),
    )
    return text, InlineKeyboardMarkup(inline_keyboard=[[skip]])


def posted(project: Project, update: ProjectUpdate) -> BotMessage:
    text = _("Update posted to %(project)s: %(health)s") % {
        "project": _title(project),
        "health": health_label(update.health),
    }
    url = miniapp_url(f"projects.updates:{project.pk}")
    if not url.startswith("https://"):
        return text, None
    button = InlineKeyboardButton(text=_("Open the project"), web_app=WebAppInfo(url=url))
    return text, InlineKeyboardMarkup(inline_keyboard=[[button]])


def not_allowed() -> str:
    return _("Only the project's lead and members post updates.")


def not_found() -> str:
    return _("This project isn't there any more, or you're not on it.")


def cancelled() -> str:
    return _("Okay, maybe later.")


def too_long() -> str:
    return _("That's a bit long: keep it under 4 000 characters.")
