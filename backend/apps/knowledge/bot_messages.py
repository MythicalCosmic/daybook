"""What the bots say about the knowledge base. Call these under the reader's language."""

from aiogram import html
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from django.conf import settings
from django.utils.translation import gettext as _

from apps.knowledge import sanitize
from apps.knowledge.callbacks import KbAction, KbCallback
from apps.knowledge.models import Page
from apps.members.bot_messages import BotMessage, miniapp_url

LIST_LIMIT = 10


def app_screen(page: Page) -> str:
    """The mini app deep link of a page (`?screen=knowledge.page:12`)."""
    return f"knowledge.page:{page.pk}"


def dashboard_url(page: Page) -> str:
    return f"/c/{page.company_id}/knowledge/p/{page.pk}"


def display_title(page: Page) -> str:
    return f"{page.emoji} {page.title}".strip()


def published_title(page: Page, *, updated: bool) -> str:
    if updated:
        return _("Page updated, please read it again: %(title)s") % {
            "title": display_title(page)
        }
    if page.require_ack:
        return _("New page to read: %(title)s") % {"title": display_title(page)}
    return _("New page in the knowledge base: %(title)s") % {"title": display_title(page)}


def reminder_title(page: Page) -> str:
    return _("Please read and confirm: %(title)s") % {"title": display_title(page)}


def page_excerpt(page: Page) -> str:
    space = f"{page.space.icon} {page.space.name}".strip()
    return f"{space} · {sanitize.excerpt(page.body_text, 240)}"


def read_button() -> str:
    return _("Read")


def _web_app_button(page: Page) -> InlineKeyboardButton | None:
    if not settings.EMPLOYEE_MINIAPP_URL.startswith("https://"):
        return None
    return InlineKeyboardButton(
        text=_("Open in the app"), web_app=WebAppInfo(url=miniapp_url(app_screen(page)))
    )


def page_message(page: Page, *, read: bool) -> BotMessage:
    """The page itself, in the chat, with "I've read it" when the page asks for it."""
    body, cut = sanitize.to_telegram(page.body)
    space = html.quote(f"{page.space.icon} {page.space.name}".strip())
    lines = [f"<b>{html.quote(display_title(page))}</b>", f"<i>{space}</i>", "", body]
    if cut:
        lines += ["", _("The page is longer: open it in the app to read the rest.")]
    rows: list[list[InlineKeyboardButton]] = []
    if page.require_ack:
        if read:
            lines += ["", _("You've confirmed reading this version.")]
        else:
            ack = KbCallback(action=KbAction.ACK, page_id=page.pk, version=page.version)
            rows.append([InlineKeyboardButton(text=_("I've read it"), callback_data=ack.pack())])
    if button := _web_app_button(page):
        rows.append([button])
    markup = InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
    return "\n".join(lines), markup


def acked(page: Page) -> BotMessage:
    return page_message(page, read=True)


def to_read(pages: list[Page]) -> BotMessage:
    """The pages someone still has to confirm, one button each."""
    if not pages:
        return _("You've read everything you need to. Thank you!"), None
    lines = [_("<b>Pages to read</b>: %(count)d") % {"count": len(pages)}, ""]
    lines.append(_("Tap a page to read it here, then confirm with “I've read it”."))
    rows = [
        [
            InlineKeyboardButton(
                text=f"{display_title(page)}"[:60],
                callback_data=KbCallback(action=KbAction.OPEN, page_id=page.pk).pack(),
            )
        ]
        for page in pages[:LIST_LIMIT]
    ]
    if len(pages) > LIST_LIMIT:
        more = len(pages) - LIST_LIMIT
        lines.append(_("And %(count)d more in the app.") % {"count": more})
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def not_found() -> str:
    return _("This page isn't available any more.")


def thanks() -> str:
    return _("Thank you! Marked as read.")


def sent_below() -> str:
    return _("Sent the page below")
