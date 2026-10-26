"""`/invite`: the company's invite links as QR codes to show people, and a team link made in three
taps (sync; the handlers call it through sync_to_async, under the person's language).

The main link asks for approval; a team link adds everyone who opens it straight away, with its
branch and role (apps.members.join_links). The bot makes team links with the company's default
role; the dashboard offers every choice.
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from aiogram import html
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.companies.models import Branch
from apps.core import qr
from apps.members import join_links, scope
from apps.members.models import JoinLink, Membership
from apps.members.permissions import Perm
from ownerbot import bot_messages, brief
from ownerbot.callbacks import InviteAct, InviteNew, InvitePick

type BotMessage = bot_messages.BotMessage
# Quick choices when making a team link in the bot.
PLACES = (5, 10, 20, 50, 0)
DAYS = (0, 3, 7, 30)
# The overview lists this many working team links as buttons.
SHOWN = 8


@dataclass(frozen=True)
class Picture:
    """A QR code to send as a photo, with its caption and buttons."""

    png: bytes
    caption: str
    markup: InlineKeyboardMarkup | None


def approvers(user: User) -> list[Membership]:
    """The companies where `user` may invite people (members.approve), by name."""
    return [member for member in brief.memberships(user) if member.has_perm(Perm.MEMBERS_APPROVE)]


def membership(user: User, company_id: int) -> Membership | None:
    return next((m for m in approvers(user) if m.company_id == company_id), None)


def no_access() -> str:
    return _("You can't invite people to this company.")


def start(user: User) -> BotMessage:
    """`/invite`: the one company's links, or which company first."""
    members = approvers(user)
    if not members:
        return _("You can't invite people to any company yet."), None
    if len(members) > 1:
        rows = [
            [
                InlineKeyboardButton(
                    text=m.company.name, callback_data=InvitePick(company=m.company_id).pack()
                )
            ]
            for m in members
        ]
        return _("Which company are you inviting people to?"), InlineKeyboardMarkup(
            inline_keyboard=rows
        )
    return overview(members[0])


def overview(member: Membership) -> BotMessage:
    company = member.company
    now = timezone.now()
    working = [
        link
        for link in join_links.ordered(join_links.visible_links(member), now)
        if link.status_at(now) == JoinLink.Status.ACTIVE
    ]
    lines = [
        _("<b>Invite staff</b> · %(company)s") % {"company": html.quote(company.name)},
        "",
        _("Main link: people ask to join, and you approve each one."),
        _(
            "A team link adds many people at once, with the branch and role you choose: show its "
            "QR code at a meeting or send it to a chat."
        ),
    ]
    if working:
        lines += ["", _("<b>Working team links</b>")]
        lines += [f"{html.quote(link.name)} · {places(link)}" for link in working[:SHOWN]]
    rows = [[_act(_("Main link QR code"), "main", company.pk)]]
    rows += [
        [_act(f"{link.name[:40]} · {short_places(link)}", "show", company.pk, link.pk)]
        for link in working[:SHOWN]
    ]
    new = InviteNew(company=company.pk).pack()
    rows.append([InlineKeyboardButton(text=_("New team link"), callback_data=new)])
    every = bot_messages.web_app_button(
        _("All links in the dashboard"), f"c/{company.pk}/settings/invite"
    )
    if every is not None:
        rows.append([every])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def main_link(member: Membership) -> Picture | str:
    company = member.company
    if not company.invite_link:
        return _("The employee bot isn't connected on this server yet, so there's no link.")
    caption = "\n".join(
        [
            _("<b>%(company)s</b>: the main invite link") % {"company": html.quote(company.name)},
            _("People who open it ask to join, and you approve each one."),
            "",
            html.quote(company.invite_link),
        ]
    )
    markup = InlineKeyboardMarkup(
        inline_keyboard=[[_share(company.invite_link, company.name)], [_back(company.pk)]]
    )
    return Picture(qr.png(company.invite_link), caption, markup)


def team_link(member: Membership, link_id: int) -> Picture | str:
    link = _find(member, link_id)
    if link is None:
        return _("This link is gone.")
    if not link.link:
        return _("The employee bot isn't connected on this server yet, so there's no link.")
    return Picture(qr.png(link.link), caption(link), _link_keyboard(member, link))


def caption(link: JoinLink) -> str:
    now = timezone.now()
    lines = [
        _("<b>%(link)s</b> · %(company)s")
        % {"link": html.quote(link.name), "company": html.quote(link.company.name)}
    ]
    if link.auto_approve:
        lines.append(_("People who open it join straight away."))
    else:
        lines.append(_("People who open it ask to join, and you approve them."))
    if link.branch is not None:
        lines.append(_("Branch: %(branch)s") % {"branch": html.quote(link.branch.name)})
    role = link.role or join_links.default_role(link.company)
    if role is not None:
        lines.append(_("Role: %(role)s") % {"role": html.quote(role.name)})
    lines.append(places(link))
    if link.expires_at is not None:
        lines.append(_("Until: %(time)s") % {"time": link.company.format_datetime(link.expires_at)})
    status = link.status_at(now)
    if status != JoinLink.Status.ACTIVE:
        lines.append(_ended(status))
    lines += ["", html.quote(link.link)]
    return "\n".join(lines)


def places(link: JoinLink) -> str:
    if link.max_uses is None:
        return _("Joined: %(uses)d") % {"uses": link.uses}
    return _("Joined: %(uses)d of %(places)d") % {"uses": link.uses, "places": link.max_uses}


def short_places(link: JoinLink) -> str:
    return f"{link.uses}/{link.max_uses}" if link.max_uses is not None else str(link.uses)


def stop(member: Membership, link_id: int) -> tuple[str, JoinLink | None]:
    """Stop a team link: the answer for the tap, and the stopped link (None if refused)."""
    link = _find(member, link_id)
    if link is None:
        return _("This link is gone."), None
    if not join_links.may_edit(member, link):
        return _("You can't change this link."), None
    link = join_links.update_link(link, by=member, is_active=False)
    return _("The link is stopped. Nobody new can join through it."), link


def edited_caption(member: Membership, link: JoinLink) -> tuple[str, InlineKeyboardMarkup]:
    return caption(link), _link_keyboard(member, link)


# Making a team link -------------------------------------------------------------------------


def new_link(member: Membership, step: InviteNew) -> BotMessage | JoinLink:
    """The next question, or the link once every choice is made."""
    company = member.company
    if step.branch == -1:
        options = _branches(member)
        if len(options) > 1:
            return _ask_branch(step, options)
        step = step.model_copy(update={"branch": options[0].pk if options else 0})
    if step.places == -1:
        return _ask_places(step)
    if step.days == -1:
        return _ask_days(step)
    branch = (
        Branch.objects.filter(company=company, pk=step.branch, is_active=True).first()
        if step.branch
        else None
    )
    zone = ZoneInfo(company.timezone)
    today = timezone.localtime(timezone.now(), zone).date()
    name = (
        f"{branch.name[:90]} · {today:%d.%m}"
        if branch is not None
        else _("Team link %(date)s") % {"date": f"{today:%d.%m}"}
    )
    return join_links.create_link(
        company,
        by=member,
        name=name,
        branch=branch,
        max_uses=step.places or None,
        expires_at=_ends(step.days, zone),
    )


def _ends(days: int, zone: ZoneInfo) -> datetime:
    """`days` 0: tonight at midnight, else that many days from now."""
    now = timezone.now()
    if days:
        return now + timedelta(days=days)
    tomorrow = timezone.localtime(now, zone).date() + timedelta(days=1)
    return datetime.combine(tomorrow, time(0), tzinfo=zone)


def _branches(member: Membership) -> list[Branch]:
    branches = Branch.objects.filter(company=member.company, is_active=True).order_by(
        "order", "name"
    )
    allowed = scope.branch_ids(member)
    return [branch for branch in branches if scope.allows(allowed, branch.pk)]


def _ask_branch(step: InviteNew, options: list[Branch]) -> BotMessage:
    buttons = [
        InlineKeyboardButton(
            text=branch.name[:40],
            callback_data=step.model_copy(update={"branch": branch.pk}).pack(),
        )
        for branch in options
    ]
    rows = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
    rows.append([_back(step.company)])
    text = _("<b>New team link</b>") + "\n\n" + _("Which branch will these people work in?")
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def _ask_places(step: InviteNew) -> BotMessage:
    buttons = [
        InlineKeyboardButton(
            text=str(count) if count else _("No limit"),
            callback_data=step.model_copy(update={"places": count}).pack(),
        )
        for count in PLACES
    ]
    rows = [buttons[:3], buttons[3:], [_back(step.company)]]
    text = _("<b>New team link</b>") + "\n\n" + _("How many people will join through it?")
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def _ask_days(step: InviteNew) -> BotMessage:
    labels = {
        0: _("Until tonight"),
        3: _("3 days"),
        7: _("7 days"),
        30: _("30 days"),
    }
    buttons = [
        InlineKeyboardButton(
            text=labels[days], callback_data=step.model_copy(update={"days": days}).pack()
        )
        for days in DAYS
    ]
    rows = [buttons[:2], buttons[2:], [_back(step.company)]]
    text = _("<b>New team link</b>") + "\n\n" + _("How long should it work?")
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


# Helpers ----------------------------------------------------------------------------------------


def _find(member: Membership, link_id: int) -> JoinLink | None:
    return join_links.visible_links(member).select_related("company").filter(pk=link_id).first()


def _link_keyboard(member: Membership, link: JoinLink) -> InlineKeyboardMarkup:
    rows = []
    working = link.status_at(timezone.now()) == JoinLink.Status.ACTIVE
    if working:
        rows.append([_share(link.link, link.company.name)])
        if join_links.may_edit(member, link):
            rows.append([_act(_("Stop the link"), "stop", link.company_id, link.pk)])
    rows.append([_back(link.company_id)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _ended(status: str) -> str:
    return {
        JoinLink.Status.STOPPED: _("The link is stopped."),
        JoinLink.Status.EXPIRED: _("The link has ended."),
        JoinLink.Status.FULL: _("The link is full."),
    }[status]


def _share(url: str, company: str) -> InlineKeyboardButton:
    text = _("Join %(company)s in Telegram") % {"company": company}
    query = urlencode({"url": url, "text": text})
    return InlineKeyboardButton(text=_("Share"), url=f"https://t.me/share/url?{query}")


def _act(text: str, action: str, company: int, link: int = 0) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text, callback_data=InviteAct(action=action, company=company, link=link).pack()
    )


def _back(company: int) -> InlineKeyboardButton:
    return _act(_("Back"), "list", company)
