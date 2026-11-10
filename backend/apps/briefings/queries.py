"""Read functions of briefings, for other apps, the dashboard and the AI tools.

A reader only ever sees the reviews of their own reading scope (apps.briefings.scope): the
same domains and the same branches, so a manager never reads the owner's finance review.

    visible(member)                       their reviews, newest first, one per day and kind
    latest(member, kind)                  their newest review of `kind` (None before the first)
    get(member, pk)                       one of theirs, or None
    shape(briefing)                       a review as the dashboard and the advisor tools read it
"""

from apps.briefings import display, scope
from apps.briefings.models import Briefing
from apps.members.models import Membership


def _rows(member: Membership, kind: str | None = None):
    rows = Briefing.objects.for_company(member.company).filter(scope_key=scope.of(member).key)
    if kind:
        rows = rows.filter(kind=kind)
    return rows


def visible(member: Membership, *, kind: str | None = None, limit: int = 52) -> list[Briefing]:
    """`member`'s reviews, newest first: one per day and kind, in their language when it was
    written in it (else the one there is: the same facts, other words)."""
    language = display.lang_of(member.user.language)
    chosen: dict[tuple, Briefing] = {}
    for row in _rows(member, kind).order_by("-day", "kind", "pk")[: limit * 3]:
        key = (row.day, row.kind)
        if key not in chosen or (row.language == language and chosen[key].language != language):
            chosen[key] = row
    return sorted(chosen.values(), key=lambda row: (row.day, row.kind), reverse=True)[:limit]


def latest(member: Membership, kind: str = Briefing.Kind.WEEKLY) -> Briefing | None:
    found = visible(member, kind=kind, limit=1)
    return found[0] if found else None


def get(member: Membership, pk: int) -> Briefing | None:
    return _rows(member).filter(pk=pk).first()


def summary(briefing: Briefing) -> dict:
    facts = briefing.facts or {}
    return {
        "id": briefing.pk,
        "kind": briefing.kind,
        "day": briefing.day,
        "period": facts.get("period", {}),
        "headline": (briefing.content or {}).get("headline", ""),
        "written_by": briefing.written_by,
        "written_at": briefing.written_at,
        "language": briefing.language,
    }


def shape(briefing: Briefing) -> dict:
    content = briefing.content or {}
    return summary(briefing) | {
        "sections": content.get("sections", []),
        "actions": content.get("actions", []),
        "facts": briefing.facts or {},
    }


def review_lines(briefing: Briefing) -> dict:
    """The review's words, flat, for the advisor tools."""
    content = briefing.content or {}
    sections = {section["key"]: section for section in content.get("sections", [])}
    return {
        "period": (briefing.facts or {}).get("period", {}),
        "headline": content.get("headline", ""),
        "went_well": sections.get("went_well", {}).get("bullets", []),
        "went_wrong": sections.get("went_wrong", {}).get("bullets", []),
        "suggestions": [action["text"] for action in content.get("actions", [])],
        "written_by": briefing.written_by,
    }
