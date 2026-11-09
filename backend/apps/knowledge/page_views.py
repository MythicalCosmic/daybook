"""Who read what: page views (docs/PLAN-LEARNING.md §4.1). Always on, also without learning.

The mini app's page reader (and the dashboard's page view) reports while the page is in front
of the person: on open, then every 15 s, and on leaving: `{session, seconds, scrolled}`.

- `seconds` counted per report is at most the time since the previous report of that session
  plus 5 s, and at most 30 (a session's first report: at most 5);
- `scrolled` (percent) keeps the maximum; `version` the newest opened;
- a new visit starts when the previous report is over 30 minutes old.

One `PageView` row per person and page. The session's last report time is kept in the cache
(the row has no session), so a lost cache only means one report counts at most 5 s.

A person never sees anyone else's views; managers see them in the page's readers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.knowledge.models import Page, PageView
from apps.members.models import Membership

MAX_SECONDS = 30
SLACK = 5
NEW_VISIT_AFTER = timedelta(minutes=30)
SESSION_TTL = 60 * 60


def _key(page: Page, member: Membership) -> str:
    return f"knowledge:view:{page.pk}:{member.pk}"


def record(
    page: Page, member: Membership, *, session: str, seconds, scrolled, now=None
) -> PageView:
    """Count one report of the reader (the caller checked the person may read the page)."""
    now = now or timezone.now()
    session = str(session or "")[:40]
    previous = cache.get(_key(page, member))
    if previous and previous.get("session") == session:
        elapsed = max(0.0, now.timestamp() - float(previous.get("at", now.timestamp())))
        allowed = min(MAX_SECONDS, elapsed + SLACK)
    else:
        allowed = SLACK
    try:
        counted = int(max(0.0, min(float(seconds or 0), allowed)))
    except TypeError, ValueError:
        counted = 0
    try:
        depth = int(max(0.0, min(float(scrolled or 0), 100.0)))
    except TypeError, ValueError:
        depth = 0
    with transaction.atomic():
        row = PageView.objects.select_for_update().filter(page=page, membership=member).first()
        created = False
        if row is None:
            try:
                with transaction.atomic():
                    row = PageView.objects.create(
                        company_id=page.company_id,
                        page=page,
                        membership=member,
                        first_at=now,
                        last_at=now,
                        visits=1,
                        seconds=counted,
                        version=page.version,
                        scrolled=depth,
                    )
                created = True
            except IntegrityError:  # the first two reports at once
                row = PageView.objects.select_for_update().get(page=page, membership=member)
        if not created:
            _add(row, page, counted, depth, now)
    cache.set(_key(page, member), {"session": session, "at": now.timestamp()}, SESSION_TTL)
    return row


def _add(row: PageView, page: Page, counted: int, depth: int, now: datetime) -> None:
    if now - row.last_at > NEW_VISIT_AFTER:
        row.visits += 1
    row.seconds += counted
    row.scrolled = max(row.scrolled, depth)
    row.version = max(row.version, page.version)
    row.last_at = max(row.last_at, now)
    row.save(update_fields=["visits", "seconds", "scrolled", "version", "last_at", "updated_at"])


@dataclass(frozen=True)
class ViewFacts:
    opened: bool
    visits: int
    seconds: int
    scrolled: int
    version: int | None
    first_at: datetime | None
    last_at: datetime | None


NOT_OPENED = ViewFacts(False, 0, 0, 0, None, None, None)


def views_of(page: Page, member_ids) -> dict[int, ViewFacts]:
    """{membership id: their views of `page`} for the readers drawer."""
    return {
        row.membership_id: ViewFacts(
            True, row.visits, row.seconds, row.scrolled, row.version, row.first_at, row.last_at
        )
        for row in PageView.objects.filter(page=page, membership_id__in=list(member_ids))
    }


def opened_counts(pages) -> dict[int, int]:
    """{page id: how many people opened it}."""
    from django.db.models import Count

    rows = (
        PageView.objects.filter(page__in=pages)
        .values("page_id")
        .annotate(people=Count("membership_id", distinct=True))
    )
    return {row["page_id"]: row["people"] for row in rows}
