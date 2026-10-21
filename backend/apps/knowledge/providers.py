"""What the knowledge base gives the shared registries: palette search, the Overview activity,
the picture download check and "copy setup from another company"."""

from __future__ import annotations

from datetime import datetime

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils.translation import gettext as _

from apps.console.registry import SearchHit, StreamItem
from apps.knowledge import queries, sanitize
from apps.knowledge.models import Page, PageImage, PageVersion, Space
from apps.members.models import Membership, Position


def _url(page: Page) -> str:
    return f"/c/{page.company_id}/knowledge/p/{page.pk}"


def search(member: Membership, q: str, limit: int) -> list[SearchHit]:
    hits = []
    for page in queries.search(member, q, limit=limit):
        space = f"{page.space.icon} {page.space.name}".strip()
        state = "" if page.published else f" · {_('Draft')}"
        hits.append(
            SearchHit(
                type="knowledge.page",
                id=page.pk,
                title=f"{page.emoji} {page.title}".strip(),
                subtitle=f"{space}{state} · {sanitize.excerpt(page.body_text, 80)}",
                url=_url(page),
            )
        )
    return hits


def stream(member: Membership, since: datetime | None, limit: int) -> list[StreamItem]:
    """Pages published, newest first (the ones `member` may open)."""
    pages = (
        queries.readable_pages(member)
        .filter(published=True, published_at__isnull=False)
        .select_related("updated_by")
        .order_by("-published_at")
    )
    if since is not None:
        pages = pages.filter(published_at__gt=since)
    items = []
    for page in pages[:limit]:
        actor = page.updated_by
        items.append(
            StreamItem(
                at=page.published_at,
                kind="knowledge.published",
                actor={"id": actor.pk, "name": actor.full_name or str(actor)} if actor else None,
                title=_("Published the page “%(title)s”") % {"title": page.title},
                url=_url(page),
            )
        )
    return items


def image_check(user, company_id: int, object_id: int) -> bool:
    """A page picture opens for managers, and for readers of the page it is on."""
    image = PageImage.objects.filter(company_id=company_id, pk=object_id).first()
    if image is None:
        return False
    member = (
        Membership.objects.select_related("role", "company")
        .filter(company_id=company_id, user=user, status=Membership.Status.APPROVED)
        .first()
    )
    if member is None:
        return False
    if queries.can_manage(member):
        return True
    if image.page_id is None:
        return False
    return queries.reader_pages(member).filter(pk=image.page_id).exists()


@transaction.atomic
def copy_spaces(source, target, by: Membership) -> int:
    """Copy every active space of `source` and its published pages (with their pictures) into
    `target`, as drafts-free first versions. A space read by positions keeps the positions
    `target` has under the same names (copying positions comes first in "copy setup"), and is
    read by everyone when none match. The empty starter shelf a new company gets is replaced.
    Returns the number of rows created."""
    spaces = list(
        Space.objects.filter(company=source, archived_at__isnull=True)
        .prefetch_related("positions")
        .order_by("position", "pk")
    )
    if not spaces:
        return 0
    Space.objects.filter(company=target, created_by__isnull=True, pages__isnull=True).delete()
    positions = {position.name: position for position in Position.objects.filter(company=target)}
    created = 0
    for space in spaces:
        mapped = [positions[p.name] for p in space.positions.all() if p.name in positions]
        copy = Space.objects.create(
            company=target,
            name=space.name,
            icon=space.icon,
            description=space.description,
            audience_all=space.audience_all or not mapped,
            position=space.position,
            created_by=by,
        )
        if not copy.audience_all:
            copy.positions.set(mapped)
        created += 1
        pages = queries._page_rows(source.pk, [space.pk])
        live = queries._readable_ids(pages)
        mapping: dict[int, Page] = {}
        for row in sorted(
            (Page.objects.get(pk=row.pk) for row in pages if row.pk in live),
            key=lambda page: (len(queries.ancestors(page)), page.position, page.pk),
        ):
            body = _copy_images(row, target, by)
            page = Page.objects.create(
                company=target,
                space=copy,
                parent=mapping.get(row.parent_id),
                title=row.title,
                emoji=row.emoji,
                body=body,
                body_text=sanitize.to_text(body),
                position=row.position,
                published=True,
                published_at=row.published_at,
                require_ack=row.require_ack,
                ack_since=row.published_at,
                created_by=by,
                updated_by=by,
            )
            PageVersion.objects.create(
                company=target,
                page=page,
                version=1,
                title=page.title,
                emoji=page.emoji,
                body=page.body,
                note=_("Copied from %(company)s") % {"company": source.name},
                created_by=by,
            )
            PageImage.objects.filter(company=target, pk__in=sanitize.image_ids(body)).update(
                page=page
            )
            mapping[row.pk] = page
            created += 1
    return created


def _copy_images(page: Page, target, by: Membership) -> str:
    """The body with each picture copied into `target`'s storage (pictures are per company)."""
    ids = sanitize.image_ids(page.body)
    if not ids:
        return page.body
    body = page.body
    for image in PageImage.objects.filter(company_id=page.company_id, pk__in=ids):
        try:
            with image.file.open("rb") as handle:
                content = ContentFile(handle.read(), name=f"copy{image.file.name[-4:]}")
        except OSError:
            continue
        copy = PageImage(
            company=target, width=image.width, height=image.height, uploaded_by=by.user
        )
        copy.file.save(f"{image.pk}.jpg", content, save=False)
        copy.save()
        body = body.replace(f'data-image-id="{image.pk}"', f'data-image-id="{copy.pk}"')
    return body
