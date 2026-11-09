"""What recognition gives the console's registries: the Overview activity stream (thanks between
colleagues) and the permission specs of its owner pages."""

from __future__ import annotations

from datetime import datetime, timedelta

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.console.perms import AnyOf
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.recognition import queries

FEATURE = "recognition"
# Who reads the dashboard's recognition pages: people who see the team or its training.
READ = AnyOf(Perm.MEMBERS_VIEW, Perm.LEARNING_VIEW, Perm.RECOGNITION_MANAGE)
MANAGE = Perm.RECOGNITION_MANAGE


LEADERBOARD_COLUMNS = (
    ("place", _("Place"), "number"),
    ("name", _("Name"), "text"),
    ("position", _("Position"), "text"),
    ("points", _("Points"), "number"),
    ("level", _("Level"), "number"),
    ("level_name", _("Level name"), "text"),
)


def leaderboard_rows(member: Membership, params: dict):
    """The dashboard's leaderboard as it is filtered (`period`, `date`, `branch`, `kind`), in
    the member's branch scope."""
    from django.utils.dateparse import parse_date

    period = params.get("period") if params.get("period") in queries.PERIODS else "week"
    seen = scope.branch_ids(member)
    branch_ids = seen
    branch = str(params.get("branch") or "")
    if branch.isdigit() and (seen is None or int(branch) in seen):
        branch_ids = [int(branch)]
    reasons = queries.LEARNING_REASONS if params.get("kind") == "learning" else None
    board = queries.leaderboard(
        member.company,
        period=period,
        branch_ids=branch_ids,
        day=parse_date(str(params.get("date") or "")) if params.get("date") else None,
        reasons=reasons,
    )
    for row in board.rows:
        yield {
            "place": row.place,
            "name": str(row.member),
            "position": row.member.position.name if row.member.position_id else "",
            "points": row.points,
            "level": row.level.number,
            "level_name": row.level.name,
        }


def stream(member: Membership, since: datetime | None, limit: int) -> list:
    """Thanks between colleagues, newest first, in the member's scope."""
    from apps.console.registry import StreamItem

    company = member.company
    after = since or timezone.now() - timedelta(days=2)
    rows = [
        kudos
        for kudos in queries.kudos_feed(company, branch_ids=scope.branch_ids(member), limit=limit)
        if kudos.created_at > after
    ]
    return [
        StreamItem(
            at=kudos.created_at,
            kind="recognition.kudos",
            actor={"id": kudos.from_member_id, "name": str(kudos.from_member)},
            title=_("Thanked %(name)s: %(reason)s")
            % {"name": kudos.to_member, "reason": kudos.get_badge_display()},
            url=f"/c/{company.pk}/recognition/kudos",
        )
        for kudos in rows
    ]
