"""Registries modules plug into instead of editing shared files (docs/PLAN-OWNER.md §2.5, §13).

Each module registers from its own `hooks.py` (imported by `AppConfig.ready()`):

    from apps.console import registry

    registry.register_pulse("tasks.review", perm=Perm.TASKS_CONFIRM, count=queries.review_count)

Rules every registry enforces at registration time:

- **App prefix** (rule 14): a key is the registering app's label or starts with it plus a dot
  (`"sales"`, `"sales.cash_difference"`). The app is the module that calls `register_*`.
- **No duplicates**: registering a key twice raises `DuplicateKey`.
- `perm` is a `Perm`, `AnyOf(...)`/`AllOf(...)` (a plain tuple means all of them), or None
  (any approved member with dashboard access). `feature` (optional everywhere) hides the entry
  while that module is off in `Company.features`.

The `collect_*` / `run_*` helpers apply both checks for the caller, and isolate providers: one
module's exception is logged and its entry left out, so a page never fails because of it.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.utils import timezone
from django.utils.functional import Promise

from apps.console import contracts
from apps.console.perms import PermSpec, holds

if TYPE_CHECKING:
    from apps.companies.models import Company
    from apps.console.ranges import Range
    from apps.members.models import Membership

logger = logging.getLogger(__name__)

KEY = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$")


class RegistryError(ValueError):
    """A registration breaks a registry rule."""


class DuplicateKey(RegistryError):
    pass


class BadKey(RegistryError):
    pass


def calling_app(depth: int = 2) -> str | None:
    """The label of the app whose module called the function asking (`apps.<label>.…`)."""
    name = sys._getframe(depth).f_globals.get("__name__", "")
    parts = name.split(".")
    return parts[1] if len(parts) > 1 and parts[0] == "apps" else None


def key_belongs_to(key: str, app: str) -> bool:
    return key == app or key.startswith(f"{app}.")


@dataclass(frozen=True)
class Entry:
    key: str
    app: str | None
    perm: PermSpec
    feature: str | None


class Registry[E: Entry]:
    """Entries by key, in registration order. Every instance is listed in `REGISTRIES`."""

    def __init__(self, name: str, *, keys: frozenset[str] | None = None):
        self.name = name
        self.allowed_keys = keys
        self._entries: dict[str, E] = {}
        REGISTRIES.append(self)

    def add(self, entry: E) -> E:
        key = entry.key
        if not isinstance(key, str) or not KEY.match(key):
            raise BadKey(f"{self.name}: {key!r} is not a valid key (lowercase, dot-separated).")
        if self.allowed_keys is not None and key not in self.allowed_keys:
            raise BadKey(
                f"{self.name}: {key!r} is not one of the fixed keys {sorted(self.allowed_keys)}."
            )
        if entry.app is not None and not key_belongs_to(key, entry.app):
            raise BadKey(f"{self.name}: {key!r} must start with its app's label {entry.app!r}.")
        if key in self._entries:
            owner = self._entries[key].app or "?"
            raise DuplicateKey(f"{self.name}: {key!r} is already registered by apps.{owner}.")
        self._entries[key] = entry
        return entry

    def get(self, key: str) -> E | None:
        return self._entries.get(key)

    def __contains__(self, key: str) -> bool:
        return key in self._entries

    def __iter__(self) -> Iterator[E]:
        return iter(list(self._entries.values()))

    def __len__(self) -> int:
        return len(self._entries)

    def keys(self) -> list[str]:
        return list(self._entries)

    def visible_to(self, member: Membership) -> list[E]:
        """Entries `member` may use: permission held and module switched on."""
        return [entry for entry in self if usable(entry, member)]

    @contextmanager
    def isolated(self) -> Iterator[Registry[E]]:
        """Tests: register freely inside the block; the entries before it come back after."""
        saved = dict(self._entries)
        try:
            yield self
        finally:
            self._entries = saved


REGISTRIES: list[Registry] = []


def usable(entry: Entry, member: Membership) -> bool:
    if entry.feature is not None and not member.company.has_feature(entry.feature):
        return False
    return holds(member, entry.perm)


def _safely[T](registry: Registry, key: str, default: T, call: Callable[..., T], *args) -> T:
    try:
        return call(*args)
    except Exception:
        logger.exception("%s provider %r failed; leaving it out", registry.name, key)
        return default


# Shapes ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchHit:
    type: str
    id: int | str
    title: str
    subtitle: str
    url: str


QUEUE_METHODS = ("POST", "PATCH", "PUT", "DELETE")
QUEUE_STYLES = ("primary", "danger", "default")


@dataclass(frozen=True)
class QueueAction:
    """A button on a "Needs you" item. The client sends `method` to `endpoint`, relative to
    `/api/v1/owner/companies/{cid}/` (e.g. `time-off/42/approve/`), with `body` (plus
    `reason` when `needs_reason`). On a 2xx the item disappears and the queue refreshes."""

    key: str
    label: str
    style: str
    method: str
    endpoint: str
    body: dict = field(default_factory=dict)
    needs_reason: bool = False

    def __post_init__(self):
        if self.method not in QUEUE_METHODS:
            raise ValueError(f"QueueAction method must be one of {QUEUE_METHODS}.")
        if self.style not in QUEUE_STYLES:
            raise ValueError(f"QueueAction style must be one of {QUEUE_STYLES}.")
        endpoint = self.endpoint
        if (
            not endpoint
            or endpoint.startswith("/")
            or "://" in endpoint
            or ".." in endpoint.split("/")
            or not endpoint.endswith("/")
        ):
            raise ValueError(
                "QueueAction endpoint must be relative to /api/v1/owner/companies/{cid}/ "
                f"and end with a slash, e.g. 'time-off/42/approve/' (got {endpoint!r})."
            )


@dataclass(frozen=True)
class QueueItem:
    kind: str
    id: int | str
    title: str
    subtitle: str
    created_at: datetime | None
    url: str
    actions: tuple[QueueAction, ...] | list[QueueAction]


@dataclass(frozen=True)
class StreamItem:
    at: datetime
    kind: str
    actor: contracts.Person | None
    title: str
    url: str
    photo_url: str | None = None


FIELD_KINDS = ("text", "textarea", "bool", "choice", "date", "money", "number", "member")


@dataclass(frozen=True)
class FieldSpec:
    """A question an offboarding step asks; the answer reaches `member_left`'s
    `details[step key][name]`."""

    name: str
    label: str
    kind: str = "text"
    required: bool = False
    choices: tuple[tuple[str, str], ...] = ()
    help: str = ""

    def __post_init__(self):
        if self.kind not in FIELD_KINDS:
            raise ValueError(f"FieldSpec kind must be one of {FIELD_KINDS}.")


@dataclass
class OffboardStep:
    lines: list[str]
    blockers: list[str]
    fields: list[FieldSpec]
    defaults: dict


@dataclass(frozen=True)
class CalendarItem:
    id: int | str
    kind: str
    title: str
    start: date | datetime
    end: date | datetime | None
    all_day: bool
    color: str
    url: str


def to_json(value: Any) -> Any:
    """Shapes as JSON: dataclasses to dicts, moments to ISO strings, lazy text to str, and
    decimals (money) to strings, never floats."""
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_json(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Promise | Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(k): to_json(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [to_json(item) for item in value]
    return value


# Entries --------------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchProvider(Entry):
    search: Callable[[Membership, str, int], list[SearchHit]]


@dataclass(frozen=True)
class QueueSource(Entry):
    label: str
    count: Callable[[Membership], int]
    items: Callable[[Membership, int], list[QueueItem]]


@dataclass(frozen=True)
class PulseCounter(Entry):
    count: Callable[[Membership], int] | None


@dataclass(frozen=True)
class StreamSource(Entry):
    fetch: Callable[[Membership, datetime | None, int], list[StreamItem]]


@dataclass(frozen=True)
class BranchFactsProvider(Entry):
    facts: Callable[[Company, date, datetime, list[int]], dict[int, dict]]


@dataclass(frozen=True)
class BriefSection(Entry):
    order: int
    build: Callable[[Company, date, datetime, list[int] | None], dict | None]


@dataclass(frozen=True)
class PersonFieldsProvider(Entry):
    fetch: Callable[[Company, list[int], datetime], dict[int, dict]]


@dataclass(frozen=True)
class OffboardStepProvider(Entry):
    order: int
    label: str
    preview: Callable[[Membership], OffboardStep]


@dataclass(frozen=True)
class SetupStep(Entry):
    order: int
    label: str
    description: str
    url: str
    done: Callable[[Company], bool]


@dataclass(frozen=True)
class CompanyFactsProvider(Entry):
    facts: Callable[[Company, Range, Membership], dict]


@dataclass(frozen=True)
class CopyPart(Entry):
    label: str
    copy: Callable[[Company, Company, Membership], int]


@dataclass(frozen=True)
class CalendarSource(Entry):
    label: str
    events: Callable[[Company, date, date, Membership], list[CalendarItem]]


SEARCH: Registry[SearchProvider] = Registry("search")
QUEUE: Registry[QueueSource] = Registry("queue")
PULSE: Registry[PulseCounter] = Registry("pulse")
STREAM: Registry[StreamSource] = Registry("stream")
BRANCH_FACTS: Registry[BranchFactsProvider] = Registry(
    "branch facts", keys=frozenset(contracts.BRANCH_FACTS)
)
BRIEF_SECTIONS: Registry[BriefSection] = Registry("brief sections")
PERSON_FIELDS: Registry[PersonFieldsProvider] = Registry("person fields")
OFFBOARD_STEPS: Registry[OffboardStepProvider] = Registry("offboard steps")
SETUP_STEPS: Registry[SetupStep] = Registry("setup steps")
COMPANY_FACTS: Registry[CompanyFactsProvider] = Registry(
    "company facts", keys=frozenset(contracts.COMPANY_FACTS)
)
COPY_PARTS: Registry[CopyPart] = Registry("copy parts")
CALENDAR_SOURCES: Registry[CalendarSource] = Registry("calendar sources")


# Registration ---------------------------------------------------------------------------


def register_search(
    type: str,
    *,
    perm: PermSpec,
    search: Callable[[Membership, str, int], list[SearchHit]],
    feature: str | None = None,
) -> None:
    """Command palette results of one type. `search(member, q, limit)` applies branch scope."""
    SEARCH.add(SearchProvider(type, calling_app(), perm, feature, search))


def register_queue(
    kind: str,
    *,
    perm: PermSpec,
    label: str,
    count: Callable[[Membership], int],
    items: Callable[[Membership, int], list[QueueItem]],
    feature: str | None = None,
) -> None:
    """Items for "Needs you". An approval is either here or an actionable notification, never
    both: give its inbox kind `queue_kind=kind` (§2.5)."""
    QUEUE.add(QueueSource(kind, calling_app(), perm, feature, label, count, items))


def register_pulse(
    key: str,
    *,
    perm: PermSpec,
    count: Callable[[Membership], int] | None,
    feature: str | None = None,
) -> None:
    """A sidebar badge (`count(member)`) and/or a version key (`pulse.bump(cid, key)` after a
    change). `count=None` registers a version key only."""
    PULSE.add(PulseCounter(key, calling_app(), perm, feature, count))


def register_stream(
    key: str,
    *,
    perm: PermSpec,
    fetch: Callable[[Membership, datetime | None, int], list[StreamItem]],
    feature: str | None = None,
) -> None:
    """Overview activity: `fetch(member, since, limit)`, newest first, branch-scoped."""
    STREAM.add(StreamSource(key, calling_app(), perm, feature, fetch))


def register_branch_facts(
    key: str,
    *,
    perm: PermSpec,
    facts: Callable[[Company, date, datetime, list[int]], dict[int, dict]],
    feature: str | None = None,
) -> None:
    """Branch cards: `facts(company, day, now, branch_ids)` → {branch id: the fixed shape of
    `contracts.BRANCH_FACTS[key]`}. `key` is one of sales, attendance, tasks, finance."""
    BRANCH_FACTS.add(BranchFactsProvider(key, calling_app(), perm, feature, facts))


def register_brief_section(
    key: str,
    *,
    perm: PermSpec,
    order: int,
    build: Callable[[Company, date, datetime, list[int] | None], dict | None],
    feature: str | None = None,
) -> None:
    """Briefings (N) and the owner bot's `/today` (A). `build` returns None to stay silent."""
    BRIEF_SECTIONS.add(BriefSection(key, calling_app(), perm, feature, order, build))


def register_person_fields(
    key: str,
    *,
    perm: PermSpec,
    fetch: Callable[[Company, list[int], datetime], dict[int, dict]],
    feature: str | None = None,
) -> None:
    """Extra team directory / Person 360 fields, dropped for callers without `perm`. The keys
    in `contracts.PERSON_FIELDS` must return exactly those fields."""
    PERSON_FIELDS.add(PersonFieldsProvider(key, calling_app(), perm, feature, fetch))


def register_offboard_step(
    key: str,
    *,
    perm: PermSpec,
    order: int,
    label: str,
    preview: Callable[[Membership], OffboardStep],
    feature: str | None = None,
) -> None:
    """A step in the offboarding wizard; its answers reach `member_left` as `details[key]`."""
    OFFBOARD_STEPS.add(
        OffboardStepProvider(key, calling_app(), perm, feature, order, label, preview)
    )


def register_setup_step(
    key: str,
    *,
    perm: PermSpec,
    order: int,
    label: str,
    description: str,
    url: str,
    done: Callable[[Company], bool],
    feature: str | None = None,
) -> None:
    """A "Get started" checklist step."""
    SETUP_STEPS.add(
        SetupStep(key, calling_app(), perm, feature, order, label, description, url, done)
    )


def register_company_facts(
    key: str,
    *,
    perm: PermSpec,
    facts: Callable[[Company, Range, Membership], dict],
    feature: str | None = None,
) -> None:
    """Portfolio cards: `facts(company, range, member)` → the fixed shape of
    `contracts.COMPANY_FACTS[key]`."""
    COMPANY_FACTS.add(CompanyFactsProvider(key, calling_app(), perm, feature, facts))


def register_copy_part(
    key: str,
    *,
    label: str,
    perm: PermSpec,
    copy: Callable[[Company, Company, Membership], int],
    feature: str | None = None,
) -> None:
    """For "Copy setup from another company": `copy(source, target, by)` returns rows created.
    People, money and history are never copied."""
    COPY_PARTS.add(CopyPart(key, calling_app(), perm, feature, label, copy))


def register_calendar_source(
    key: str,
    *,
    label: str,
    perm: PermSpec,
    events: Callable[[Company, date, date, Membership], list[CalendarItem]],
    feature: str | None = None,
) -> None:
    """Company calendar dates: `events(company, start, end, member)`, both days inclusive."""
    CALENDAR_SOURCES.add(CalendarSource(key, calling_app(), perm, feature, label, events))


# Running --------------------------------------------------------------------------------


def run_search(
    member: Membership, q: str, *, types: list[str] | None = None, limit: int = 5
) -> list[SearchHit]:
    hits: list[SearchHit] = []
    for provider in SEARCH.visible_to(member):
        if types and provider.key not in types:
            continue
        found = _safely(SEARCH, provider.key, [], provider.search, member, q, limit)
        hits += list(found)[:limit]
    return hits


def queue_counts(member: Membership) -> list[tuple[QueueSource, int]]:
    return [
        (source, _safely(QUEUE, source.key, 0, source.count, member))
        for source in QUEUE.visible_to(member)
    ]


def queue_total(member: Membership) -> int:
    return sum(count for _source, count in queue_counts(member))


def queue_items(member: Membership, *, kind: str | None = None, limit: int = 50) -> list[QueueItem]:
    """Items of every kind (or one), oldest first: approvals are first come, first served."""
    items: list[QueueItem] = []
    for source in QUEUE.visible_to(member):
        if kind is not None and source.key != kind:
            continue
        items += list(_safely(QUEUE, source.key, [], source.items, member, limit))[:limit]
    items.sort(key=lambda item: (item.created_at is None, item.created_at or datetime.min))
    return items


def pulse_counts(member: Membership) -> dict[str, int]:
    return {
        counter.key: _safely(PULSE, counter.key, 0, counter.count, member)
        for counter in PULSE.visible_to(member)
        if counter.count is not None
    }


def run_stream(
    member: Membership, *, since: datetime | None = None, limit: int = 50
) -> list[StreamItem]:
    items: list[StreamItem] = []
    for source in STREAM.visible_to(member):
        items += list(_safely(STREAM, source.key, [], source.fetch, member, since, limit))
    if since is not None:
        items = [item for item in items if item.at > since]
    items.sort(key=lambda item: item.at, reverse=True)
    return items[:limit]


def collect_branch_facts(
    member: Membership, day: date, now: datetime, branch_ids: list[int]
) -> dict[str, dict[int, dict]]:
    """{fact key: {branch id: facts}} from the providers `member` may see; a provider whose
    output doesn't fit its shape is logged and left out."""
    found: dict[str, dict[int, dict]] = {}
    for provider in BRANCH_FACTS.visible_to(member):
        result = _safely(
            BRANCH_FACTS,
            provider.key,
            None,
            provider.facts,
            member.company,
            day,
            now,
            branch_ids,
        )
        if result is None:
            continue
        shape = contracts.BRANCH_FACTS[provider.key]
        wrong = {
            branch_id: issues
            for branch_id, facts in result.items()
            if (issues := contracts.problems(shape, facts))
        }
        if wrong:
            logger.error("branch facts %r don't fit %s: %s", provider.key, shape.__name__, wrong)
            continue
        found[provider.key] = result
    return found


def collect_brief_sections(
    member: Membership, day: date, now: datetime, *, branch_ids: list[int] | None
) -> list[tuple[str, dict]]:
    """[(section key, data)] in `order`, for the sections `member` may see; silent ones out."""
    sections = []
    for section in sorted(BRIEF_SECTIONS.visible_to(member), key=lambda s: (s.order, s.key)):
        data = _safely(
            BRIEF_SECTIONS, section.key, None, section.build, member.company, day, now, branch_ids
        )
        if data is not None:
            sections.append((section.key, data))
    return sections


def collect_person_fields(
    viewer: Membership, member_ids: list[int], now: datetime
) -> dict[int, dict]:
    """{member id: merged extra fields} from the providers `viewer` may see."""
    merged: dict[int, dict] = {member_id: {} for member_id in member_ids}
    for provider in PERSON_FIELDS.visible_to(viewer):
        result = _safely(
            PERSON_FIELDS, provider.key, {}, provider.fetch, viewer.company, member_ids, now
        )
        shape = contracts.PERSON_FIELDS.get(provider.key)
        for member_id, values in result.items():
            if member_id not in merged:
                continue
            if shape is not None and (issues := contracts.problems(shape, values)):
                logger.error("person fields %r don't fit: %s", provider.key, issues)
                continue
            merged[member_id].update(values)
    return merged


def collect_offboard_steps(membership: Membership, *, by: Membership) -> list[dict]:
    """The wizard for offboarding `membership`, as `by` may run it, in step order."""
    steps = []
    for provider in sorted(OFFBOARD_STEPS.visible_to(by), key=lambda p: (p.order, p.key)):
        step = _safely(OFFBOARD_STEPS, provider.key, None, provider.preview, membership)
        if step is None:
            continue
        steps.append(
            {"key": provider.key, "label": str(provider.label), "order": provider.order}
            | to_json(step)
        )
    return steps


def collect_setup_steps(member: Membership) -> list[dict]:
    company = member.company
    return [
        {
            "key": step.key,
            "label": str(step.label),
            "description": str(step.description),
            "url": step.url,
            "order": step.order,
            "done": bool(_safely(SETUP_STEPS, step.key, False, step.done, company)),
        }
        for step in sorted(SETUP_STEPS.visible_to(member), key=lambda s: (s.order, s.key))
    ]


def collect_company_facts(member: Membership, range: Range) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for provider in COMPANY_FACTS.visible_to(member):
        facts = _safely(
            COMPANY_FACTS, provider.key, None, provider.facts, member.company, range, member
        )
        if facts is None:
            continue
        if issues := contracts.problems(contracts.COMPANY_FACTS[provider.key], facts):
            logger.error("company facts %r don't fit: %s", provider.key, issues)
            continue
        found[provider.key] = facts
    return found


def run_copy(source: Company, target: Company, keys: list[str], *, by: Membership) -> dict:
    """Copy the chosen parts from `source` into `target` as `by` (a member of `target`).

    `by`'s user must also be an approved member of `source` with dashboard access and each
    part's permission there: nobody copies the setup of a company they can't see. Unknown
    parts and parts `by` may not copy raise `RegistryError`, before anything is copied; a
    failing part raises too, so the caller's transaction keeps everything or nothing."""
    if by.company_id != target.pk:
        raise RegistryError("`by` must be a member of the company copied into.")
    if source.pk == target.pk:
        raise RegistryError("Pick another company to copy from.")
    reader = _source_member(source, by)
    parts = []
    for key in keys:
        part = COPY_PARTS.get(key)
        if part is None or not usable(part, by) or reader is None or not holds(reader, part.perm):
            raise RegistryError(f"Can't copy {key!r}.")
        parts.append(part)
    return {part.key: part.copy(source, target, by) for part in parts}


def _source_member(source: Company, by: Membership) -> Membership | None:
    """`by`'s user's membership in `source`, when it lets them open that company's dashboard."""
    from apps.members.models import Membership
    from apps.members.permissions import Perm

    reader = (
        Membership.objects.select_related("role", "company")
        .filter(
            company=source,
            company__is_active=True,
            user_id=by.user_id,
            status=Membership.Status.APPROVED,
        )
        .first()
    )
    if reader is None or not reader.has_perm(Perm.DASHBOARD_ACCESS):
        return None
    return reader


def collect_calendar(
    member: Membership, start: date, end: date, *, sources: list[str] | None = None
) -> list[CalendarItem]:
    items: list[CalendarItem] = []
    for source in CALENDAR_SOURCES.visible_to(member):
        if sources and source.key not in sources:
            continue
        items += list(
            _safely(
                CALENDAR_SOURCES, source.key, [], source.events, member.company, start, end, member
            )
        )
    items.sort(key=lambda item: _as_datetime(item.start))
    return items


def _as_datetime(value: date | datetime) -> datetime:
    """A sort key that puts all-day dates at the start of their day."""
    if isinstance(value, datetime):
        return timezone.make_naive(value) if timezone.is_aware(value) else value
    return datetime(value.year, value.month, value.day)
