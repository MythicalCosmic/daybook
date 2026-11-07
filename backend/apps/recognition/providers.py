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
