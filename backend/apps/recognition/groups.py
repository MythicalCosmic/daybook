"""Kudos in the company's linked Telegram groups (docs/PLAN-LEARNING.md §7.5, Should): when the
company turns `post_kudos_to_groups` on, each thank-you is posted to the groups that want the
"Kudos" event (`apps.groups.services.broadcast`; groups narrowed to branches get the receiver's
branch). Plain words in the company's language, no emoji.
"""

from __future__ import annotations

from aiogram import html
from django.utils import translation
from django.utils.translation import gettext as _

from apps.recognition import conf
from apps.recognition.models import Kudos


def text(kudos: Kudos) -> str:
    """The group post: who thanked whom, for what, and the note."""
    lines = [
        f"<b>{html.quote(_('Thanks between colleagues'))}</b>",
        html.quote(_("To: %(name)s") % {"name": kudos.to_member}),
        html.quote(_("From: %(name)s") % {"name": kudos.from_member}),
        html.quote(str(kudos.get_badge_display())),
    ]
    if kudos.message:
        lines.append(f"«{html.quote(kudos.message)}»")
    return "\n".join(lines)


def post_kudos(kudos_id: int) -> int:
    """Post one thank-you to the linked groups; returns how many groups it was queued for."""
    from apps.groups.models import GroupEvent
    from apps.groups.services import broadcast

    kudos = (
        Kudos.objects.select_related("company", "from_member", "to_member")
        .filter(pk=kudos_id, hidden_at__isnull=True)
        .first()
    )
    if kudos is None or not conf.is_on(kudos.company):
        return 0
    if not conf.get_settings(kudos.company).post_kudos_to_groups:
        return 0
    with translation.override(kudos.company.default_language):
        body = text(kudos)
    return broadcast(
        kudos.company_id, GroupEvent.KUDOS, body, branch_id=kudos.to_member.home_branch_id
    )
