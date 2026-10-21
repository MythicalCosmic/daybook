"""Read functions of the knowledge base, for the API, the bots, other apps and the AI tools.

Who reads what:

- A **space** is read by everyone (`audience_all`) or by the holders of its positions.
- A **page** is readable when it is published and not archived, every page above it is too,
  and its space is one the person reads.
- People with `knowledge.manage` see every space and page, drafts included (the dashboard).

Knowledge pages are not branch-bound (§2.6), but people are: lists of readers are narrowed to
the viewer's branch scope.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from django.db.models import Count, Max, Q, QuerySet

from apps.knowledge.models import LIVE, Page, PageAck, PageLink, Space
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm

MAX_DEPTH = 3  # four levels: a page at depth 0 may hold three levels below it


def can_manage(member: Membership) -> bool:
    return member.has_perm(Perm.KNOWLEDGE_MANAGE)


# Spaces ---------------------------------------------------------------------------------


def reads_space(member: Membership, space: Space) -> bool:
    if space.archived_at is not None and not can_manage(member):
        return False
    if can_manage(member) or space.audience_all:
        return True
    return member.position_id is not None and any(
        position.pk == member.position_id for position in space.positions.all()
    )


def reader_spaces(member: Membership) -> QuerySet[Space]:
    """The spaces meant for `member` as a reader: "everyone" spaces and those of their
    position (whatever they may manage), in shelf order."""
    spaces = (
        Space.objects.for_company(member.company_id)
        .filter(archived_at__isnull=True)
        .prefetch_related("positions")
    )
    audience = Q(audience_all=True)
    if member.position_id is not None:
        audience |= Q(positions=member.position_id)
    return spaces.filter(audience).distinct().order_by("position", "pk")


def visible_spaces(member: Membership, *, include_archived: bool = False) -> QuerySet[Space]:
    """The spaces `member` sees in the dashboard: every one for managers (`include_archived`
    adds archived ones), the ones meant for them otherwise."""
    if not can_manage(member):
        return reader_spaces(member)
    spaces = Space.objects.for_company(member.company_id).prefetch_related("positions")
    if not include_archived:
        spaces = spaces.filter(archived_at__isnull=True)
    return spaces.order_by("position", "pk")


# Pages ----------------------------------------------------------------------------------


def _page_rows(company_id: int, space_ids: list[int] | None = None) -> list[Page]:
    pages = Page.objects.for_company(company_id).filter(archived_at__isnull=True)
    if space_ids is not None:
        pages = pages.filter(space_id__in=space_ids)
    return list(
        pages.only(
            "id",
            "space_id",
            "parent_id",
            "title",
            "emoji",
            "position",
            "published",
            "published_at",
            "require_ack",
            "version",
            "ack_version",
            "updated_at",
            "updated_by_id",
            "company_id",
        ).order_by("position", "pk")
    )


def _readable_ids(pages: list[Page]) -> set[int]:
    """Published pages whose ancestors are all published (archived ones are already out)."""
    by_id = {page.pk: page for page in pages}
    readable: dict[int, bool] = {}

    def ok(page: Page) -> bool:
        if page.pk in readable:
            return readable[page.pk]
        result = page.published
        if result and page.parent_id is not None:
            parent = by_id.get(page.parent_id)
            result = parent is not None and ok(parent)
        readable[page.pk] = result
        return result

    return {page.pk for page in pages if ok(page)}


def reader_pages(member: Membership) -> QuerySet[Page]:
    """Published pages (under published pages) in the spaces meant for `member`: what they
    read in the mini app and must confirm, whatever they may manage."""
    spaces = list(reader_spaces(member).values_list("pk", flat=True))
    ids = _readable_ids(_page_rows(member.company_id, spaces))
    return Page.objects.for_company(member.company_id).filter(pk__in=ids).filter(LIVE)


def readable_pages(member: Membership) -> QuerySet[Page]:
    """Every page `member` may open in the dashboard: for managers every page that isn't
    archived, drafts included; for everyone else `reader_pages`."""
    if not can_manage(member):
        return reader_pages(member)
    spaces = list(visible_spaces(member).values_list("pk", flat=True))
    return Page.objects.for_company(member.company_id).filter(
        space_id__in=spaces, archived_at__isnull=True
    )


def can_read(member: Membership, page: Page) -> bool:
    return readable_pages(member).filter(pk=page.pk).exists()


def is_live(page: Page) -> bool:
    """Readers can open `page`: it is published and not archived, its space isn't archived,
    and every page above it is published too. Only a live page is announced or reminded."""
    if not page.published or page.archived_at is not None:
        return False
    if Space.objects.filter(pk=page.space_id, archived_at__isnull=False).exists():
        return False
    chain = ancestors(page)
    return all(above.published and above.archived_at is None for above in chain)


def get_page(member: Membership, page_id: int) -> Page | None:
    """The page if `member` may read it (managers: any page of the company, archived too)."""
    pages = Page.objects.for_company(member.company_id).select_related(
        "space", "updated_by", "created_by"
    )
    if can_manage(member):
        return pages.filter(pk=page_id).first()
    return readable_pages(member).select_related("space", "updated_by").filter(pk=page_id).first()


@dataclass
class TreeNode:
    page: Page
    children: list[TreeNode]


def tree(member: Membership, space: Space, *, reader: bool = False) -> list[TreeNode]:
    """The pages of `space` `member` may see (`reader`: published ones only, as in the mini
    app), as a tree in position order."""
    rows = _page_rows(member.company_id, [space.pk])
    if reader or not can_manage(member):
        readable = _readable_ids(rows)
        rows = [row for row in rows if row.pk in readable]
    nodes = {row.pk: TreeNode(row, []) for row in rows}
    roots: list[TreeNode] = []
    for row in rows:
        node = nodes[row.pk]
        parent = nodes.get(row.parent_id) if row.parent_id else None
        (parent.children if parent else roots).append(node)
    return roots


def ancestors(page: Page) -> list[Page]:
    """The pages above `page`, from the top down."""
    chain: list[Page] = []
    seen = {page.pk}
    current = page.parent
    while current is not None and current.pk not in seen:
        chain.append(current)
        seen.add(current.pk)
        current = current.parent
    return list(reversed(chain))


def depth_of(page: Page) -> int:
    return len(ancestors(page))


def subtree_depth(page: Page) -> int:
    """How many levels hang below `page` (0 for a leaf)."""
    children = list(Page.objects.filter(parent=page, archived_at__isnull=True))
    if not children:
        return 0
    return 1 + max(subtree_depth(child) for child in children)


def descendant_ids(page: Page) -> list[int]:
    found: list[int] = []
    frontier = [page.pk]
    while frontier:
        children = list(Page.objects.filter(parent_id__in=frontier).values_list("pk", flat=True))
        found += children
        frontier = children
    return found


def search(member: Membership, q: str, *, limit: int = 20, reader: bool = False) -> list[Page]:
    """Pages `member` may open (`reader`: only `reader_pages`) whose title or text holds `q`;
    title matches first."""
    q = (q or "").strip()
    if len(q) < 2:
        return []
    pages = (reader_pages(member) if reader else readable_pages(member)).select_related("space")
    by_title = list(pages.filter(title__icontains=q).order_by("-updated_at")[:limit])
    rest = limit - len(by_title)
    by_text = []
    if rest > 0:
        by_text = list(
            pages.filter(body_text__icontains=q)
            .exclude(pk__in=[page.pk for page in by_title])
            .order_by("-updated_at")[:rest]
        )
    return by_title + by_text


# Readers and acknowledgements -----------------------------------------------------------


def audience(space: Space) -> QuerySet[Membership]:
    """Approved members who read `space`."""
    people = Membership.objects.filter(
        company_id=space.company_id, status=Membership.Status.APPROVED
    )
    if space.audience_all:
        return people
    return people.filter(position__in=space.positions.all())


def is_read(ack_version: int | None, page: Page) -> bool:
    return ack_version is not None and ack_version >= page.ack_version


def latest_acks(page: Page, member_ids=None) -> dict[int, PageAck]:
    """{membership id: their newest acknowledgement of `page`}."""
    acks = PageAck.objects.filter(page=page).order_by("membership_id", "-version")
    if member_ids is not None:
        acks = acks.filter(membership_id__in=member_ids)
    newest: dict[int, PageAck] = {}
    for ack in acks:
        newest.setdefault(ack.membership_id, ack)
    return newest


@dataclass
class ReaderRow:
    membership: Membership
    status: str  # "read" | "outdated" | "unread"
    version: int | None
    at: datetime | None


def readers(page: Page, *, viewer: Membership) -> list[ReaderRow]:
    """Everyone the page is for, within `viewer`'s branch scope, with what they have read."""
    people = scope.restrict(
        audience(page.space).select_related("user", "position", "home_branch"),
        scope.branch_ids(viewer),
        field="branches",
    ).order_by("first_name", "last_name", "pk")
    people = list(people)
    acks = latest_acks(page, [person.pk for person in people])
    rows = []
    for person in people:
        ack = acks.get(person.pk)
        if ack is None:
            status = "unread"
        elif is_read(ack.version, page):
            status = "read"
        else:
            status = "outdated"
        rows.append(
            ReaderRow(person, status, ack.version if ack else None, ack.at if ack else None)
        )
    order = {"unread": 0, "outdated": 1, "read": 2}
    rows.sort(key=lambda row: (order[row.status], row.membership.full_name.lower()))
    return rows


def read_counts(pages: list[Page]) -> dict[int, tuple[int, int]]:
    """{page id: (people who read the current version, people the page is for)}."""
    if not pages:
        return {}
    spaces = {page.space_id for page in pages}
    space_rows = Space.objects.filter(pk__in=spaces).prefetch_related("positions")
    audience_ids = {
        space.pk: set(audience(space).values_list("pk", flat=True)) for space in space_rows
    }
    newest: dict[int, dict[int, int]] = defaultdict(dict)
    rows = (
        PageAck.objects.filter(page__in=pages)
        .values("page_id", "membership_id")
        .annotate(version=Max("version"))
    )
    for row in rows:
        newest[row["page_id"]][row["membership_id"]] = row["version"]
    counts = {}
    for page in pages:
        people = audience_ids.get(page.space_id, set())
        read = sum(
            1
            for member_id, version in newest[page.pk].items()
            if member_id in people and version >= page.ack_version
        )
        counts[page.pk] = (read, len(people))
    return counts


def my_ack(member: Membership, page: Page) -> PageAck | None:
    return PageAck.objects.filter(page=page, membership=member).order_by("-version").first()


def to_read(member: Membership) -> list[Page]:
    """Pages `member` must confirm and hasn't for the current version, oldest first."""
    pages = list(
        reader_pages(member)
        .filter(require_ack=True)
        .select_related("space")
        .order_by("published_at", "pk")
    )
    if not pages:
        return []
    acked = dict(
        PageAck.objects.filter(membership=member, page__in=pages)
        .values("page_id")
        .annotate(version=Max("version"))
        .values_list("page_id", "version")
    )
    return [page for page in pages if not is_read(acked.get(page.pk), page)]


def unread_audience(page: Page) -> list[Membership]:
    """People the page is for who haven't confirmed its current version."""
    people = list(audience(page.space).select_related("user"))
    acks = latest_acks(page, [person.pk for person in people])
    return [
        person
        for person in people
        if not (ack := acks.get(person.pk)) or not is_read(ack.version, page)
    ]


# Links ----------------------------------------------------------------------------------


def links_for(member: Membership, target_type: str, target_id: int) -> list[PageLink]:
    """Links from pages `member` may read to one task or routine."""
    from apps.knowledge import targets

    pages = readable_pages(member)
    links = (
        PageLink.objects.for_company(member.company_id)
        .filter(target_type=target_type, target_id=target_id, page__in=pages)
        .select_related("page", "page__space")
        .order_by("pk")
    )
    return targets.visible_links(member, links)


# Overview -------------------------------------------------------------------------------


def space_counts(company_id: int) -> dict[int, dict[str, int]]:
    """{space id: {pages, published, drafts}} over pages that aren't archived."""
    rows = (
        Page.objects.for_company(company_id)
        .filter(archived_at__isnull=True)
        .values("space_id")
        .annotate(
            pages=Count("pk"),
            published=Count("pk", filter=Q(published=True)),
        )
    )
    return {
        row["space_id"]: {
            "pages": row["pages"],
            "published": row["published"],
            "drafts": row["pages"] - row["published"],
        }
        for row in rows
    }


def readable_counts(member: Membership, space_ids: list[int]) -> dict[int, int]:
    """{space id: pages `member` may read in it}."""
    rows = (
        readable_pages(member)
        .filter(space_id__in=space_ids)
        .values("space_id")
        .annotate(n=Count("pk"))
    )
    return {row["space_id"]: row["n"] for row in rows}


def recent(member: Membership, *, limit: int = 8) -> list[Page]:
    return list(
        readable_pages(member).select_related("space", "updated_by").order_by("-updated_at")[:limit]
    )
