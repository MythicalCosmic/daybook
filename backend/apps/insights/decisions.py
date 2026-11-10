"""What waits for the owner's decision ("Qaroringizni kutmoqda"): a small registry of decision
sources the cockpit and the owner bot read.

A source is a kind of request someone made that an owner settles with a yes or a no: a join
request, an expense claim above the approval limit, time off, overtime, an advance, a write-off.
Most are already "Needs you" queues of their own apps (`apps.console.registry.register_queue`),
with items whose Approve and Reject buttons call the app's own endpoint (and so its service,
permission check, audit and pulse). Such a source registers by its queue kind alone:

    from apps.insights import decisions

    decisions.register_source("hr.applicants", group="hire", order=15)

and takes the queue's permission, module switch, label, count and items: nothing is built
twice. A source with no queue passes its own `count(member)` and `items(member, limit)` (console
`QueueItem`s, buttons as `QueueAction`s) and a label; its key then starts with its app's label.

`group` says what kind of decision it is (`GROUPS`), for the cockpit's chips; `order` sorts the
sources. Sources are registered in each app's `hooks.py` or, for the existing queues, in
`apps/insights/hooks.py`. Registering a key twice raises.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from django.utils.functional import Promise

from apps.console import registry
from apps.console.perms import PermSpec
from apps.console.registry import Entry, QueueItem, Registry, RegistryError, calling_app

if TYPE_CHECKING:
    from apps.members.models import Membership

logger = logging.getLogger(__name__)

# What kind of decision a source holds (the cockpit groups and labels them).
GROUPS = (
    "expense",  # spending above the approval limit
    "hire",  # applicants to hire
    "people",  # people joining or leaving
    "time_off",
    "overtime",
    "pay",  # advances, bonuses and fines
    "purchase",
    "discount",
    "stock",  # write-offs and other stock losses
    "other",
)


@dataclass(frozen=True)
class DecisionSource(Entry):
    group: str
    order: int
    label: str | Promise | None
    count: Callable[[Membership], int] | None
    items: Callable[[Membership, int], list[QueueItem]] | None

    @property
    def queue(self):
        """The console queue this source reads, when it has no functions of its own."""
        return registry.QUEUE.get(self.key) if self.items is None else None


SOURCES: Registry[DecisionSource] = Registry("decision sources")


def register_source(
    key: str,
    *,
    group: str,
    order: int = 100,
    label: str | Promise | None = None,
    perm: PermSpec = None,
    count: Callable[[Membership], int] | None = None,
    items: Callable[[Membership, int], list[QueueItem]] | None = None,
    feature: str | None = None,
) -> None:
    """A source of owner decisions; without `count` and `items`, the "Needs you" queue of the
    same kind (looked up when read, so the registration order of apps doesn't matter)."""
    if group not in GROUPS:
        raise RegistryError(f"decision source {key!r}: group must be one of {GROUPS}.")
    if (count is None) != (items is None):
        raise RegistryError(f"decision source {key!r}: give both count and items, or neither.")
    own = items is not None
    if own and label is None:
        raise RegistryError(f"decision source {key!r}: a source with its own items needs a label.")
    # A queue-backed source belongs to the queue's app, whoever lists it.
    app = calling_app() if own else None
    SOURCES.add(DecisionSource(key, app, perm, feature, group, order, label, count, items))


def usable(source: DecisionSource, member: Membership) -> bool:
    if not registry.usable(source, member):
        return False
    if source.items is not None:
        return True
    queue = source.queue
    return queue is not None and registry.usable(queue, member)


def visible_to(member: Membership) -> list[DecisionSource]:
    return sorted(
        (source for source in SOURCES if usable(source, member)),
        key=lambda source: (source.order, source.key),
    )


def _label(source: DecisionSource) -> str:
    if source.label is not None:
        return str(source.label)
    queue = source.queue
    return str(queue.label) if queue is not None else source.key


def _count(source: DecisionSource, member: Membership) -> int:
    count = source.count or source.queue.count
    try:
        return int(count(member))
    except Exception:
        logger.exception("decision source %r failed to count; leaving it out", source.key)
        return 0


def _items(source: DecisionSource, member: Membership, limit: int) -> list[QueueItem]:
    items = source.items or source.queue.items
    try:
        return list(items(member, limit))[:limit]
    except Exception:
        logger.exception("decision source %r failed to list; leaving it out", source.key)
        return []


def counts(member: Membership) -> list[tuple[DecisionSource, int]]:
    return [(source, _count(source, member)) for source in visible_to(member)]


def total(member: Membership) -> int:
    return sum(count for _source, count in counts(member))


def collect(member: Membership, *, limit: int = 8) -> dict:
    """{"total", "sources": [{key, group, label, count}], "items": the first `limit`, oldest
    first}: what the cockpit shows. Items are the queues' own, with their source and group;
    only items with at least one button (a decision to make here) are listed."""
    found = counts(member)
    items: list[tuple[DecisionSource, QueueItem]] = []
    for source, count in found:
        if count <= 0:
            continue
        items += [(source, item) for item in _items(source, member, limit) if list(item.actions)]
    items.sort(key=lambda pair: (pair[1].created_at is None, pair[1].created_at or datetime.min))
    return {
        "total": sum(count for _source, count in found),
        "sources": [
            {"key": source.key, "group": source.group, "label": _label(source), "count": count}
            for source, count in found
        ],
        "items": [
            {**registry.to_json(item), "source": source.key, "group": source.group}
            for source, item in items[:limit]
        ],
    }
