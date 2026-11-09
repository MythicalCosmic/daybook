"""The topics a page is about (docs/PLAN-LEARNING.md §2.5): set in the page editor, offered from
the company's live topics; a topic already on the page may stay after it was archived."""

from __future__ import annotations

from django.db import transaction

from apps.knowledge import topics
from apps.knowledge.audit_actions import KnowledgeAction
from apps.knowledge.models import Page
from apps.knowledge.services import PULSE_KEY, _audit, ensure_manager
from apps.members.models import Membership


@transaction.atomic
def set_page_topics(page: Page, *, by: Membership | None, topic_ids) -> list[int]:
    """Tag `page` with `topic_ids` (in that order); returns the ids it carries now."""
    ensure_manager(by)
    kept = set(page.topics.values_list("pk", flat=True))
    wanted = [int(pk) for pk in topic_ids or ()]
    live = set(topics.live_ids(page.company_id, [pk for pk in wanted if pk not in kept]))
    final = [pk for pk in dict.fromkeys(wanted) if pk in kept or pk in live]
    if set(final) != kept:
        page.topics.set(final)
        _audit(KnowledgeAction.PAGE_SAVED, page, by, changed=["topics"])
        company_id = page.company_id
        from apps.console import pulse

        transaction.on_commit(lambda: pulse.bump(company_id, PULSE_KEY))
    return final
