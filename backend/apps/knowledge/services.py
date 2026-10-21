"""Business logic of the knowledge base: every write, shared by the API, the bots and Celery.

Each service takes `by: Membership` (`None` means the system), audits its changes with
`apps.audit.services.record` and queues jobs with `transaction.on_commit`.

Pages are edited in place: saving a published page changes what readers see at once, and every
save that changes the content writes a version. `reread=True` on a save (or on publishing)
asks everyone to read the page again: acknowledgements of older versions stop counting and the
readers hear about it.
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import F, Max
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.core.uploads import sanitize_image
from apps.inbox.services import NotificationAction, notify
from apps.knowledge import bot_messages, queries, sanitize, targets
from apps.knowledge.audit_actions import KnowledgeAction
from apps.knowledge.conf import get_settings
from apps.knowledge.models import (
    KnowledgeSettings,
    Page,
    PageAck,
    PageImage,
    PageLink,
    PageVersion,
    Space,
)
from apps.members.models import Membership, Position
from apps.members.permissions import Perm

PULSE_KEY = "knowledge.pages"
KIND_PUBLISHED = "knowledge.page_published"
KIND_REMINDER = "knowledge.read_reminder"
MAX_TITLE = 200


def ensure_manager(by: Membership | None) -> None:
    if by is not None and not by.has_perm(Perm.KNOWLEDGE_MANAGE):
        raise PermissionDenied(_("Only people who manage the knowledge base can do this."))


def _audit(action: str, target, by: Membership | None, **details) -> None:
    company_id = target.company_id
    audit.record(
        action,
        company_id=company_id,
        actor=by.user if by is not None else None,
        target=target,
        **details,
    )


def _bump(company_id: int) -> None:
    transaction.on_commit(lambda: pulse.bump(company_id, PULSE_KEY))


def _clean_title(title: str) -> str:
    title = " ".join((title or "").split())
    if not title:
        raise DomainError(_("Give it a title."))
    if len(title) > MAX_TITLE:
        raise DomainError(_("Keep the title under %(n)d characters.") % {"n": MAX_TITLE})
    return title


def _clean_emoji(emoji: str) -> str:
    emoji = (emoji or "").strip()
    if len(emoji) > 16:
        raise DomainError(_("Pick one emoji."))
    return emoji


def _clean_body(body: str) -> str:
    if body and len(body) > sanitize.MAX_BODY_CHARS:
        raise DomainError(_("This page is too long. Split it into a few pages."))
    return sanitize.clean(body or "")


# Spaces ---------------------------------------------------------------------------------


def _positions(company_id: int, position_ids) -> list[Position]:
    ids = {int(pk) for pk in position_ids or ()}
    positions = list(Position.objects.filter(company_id=company_id, pk__in=ids))
    if len(positions) != len(ids):
        raise DomainError(_("Pick positions of this company."))
    return positions


@transaction.atomic
def create_space(
    company,
    *,
    by: Membership | None,
    name: str,
    icon: str = "",
    description: str = "",
    audience_all: bool = True,
    position_ids=(),
) -> Space:
    ensure_manager(by)
    name = _clean_title(name)[:100]
    positions = _positions(company.pk, position_ids)
    if not audience_all and not positions:
        raise DomainError(_("Pick who reads this space: everyone or some positions."))
    last = Space.objects.filter(company=company).aggregate(top=Max("position"))["top"]
    space = Space.objects.create(
        company=company,
        name=name,
        icon=_clean_emoji(icon),
        description=(description or "").strip()[:300],
        audience_all=audience_all,
        position=(last or 0) + 1,
        created_by=by,
    )
    space.positions.set(positions)
    _audit(KnowledgeAction.SPACE_CREATED, space, by, name=name)
    _bump(company.pk)
    return space


@transaction.atomic
def update_space(space: Space, *, by: Membership | None, **changes) -> Space:
    """Change `name`, `icon`, `description`, `audience_all` and `position_ids`."""
    ensure_manager(by)
    unknown = set(changes) - {"name", "icon", "description", "audience_all", "position_ids"}
    if unknown:
        raise ValueError(f"Can't change {sorted(unknown)} on a space.")
    space = Space.objects.select_for_update().get(pk=space.pk)
    if "name" in changes:
        space.name = _clean_title(changes["name"])[:100]
    if "icon" in changes:
        space.icon = _clean_emoji(changes["icon"])
    if "description" in changes:
        space.description = (changes["description"] or "").strip()[:300]
    if "audience_all" in changes:
        space.audience_all = bool(changes["audience_all"])
    space.save()
    if "position_ids" in changes:
        space.positions.set(_positions(space.company_id, changes["position_ids"]))
    if not space.audience_all and not space.positions.exists():
        raise DomainError(_("Pick who reads this space: everyone or some positions."))
    _audit(KnowledgeAction.SPACE_CHANGED, space, by, changed=sorted(changes))
    _bump(space.company_id)
    return space


@transaction.atomic
def archive_space(space: Space, *, by: Membership | None) -> Space:
    """Hide a space and its pages from readers; nothing is deleted."""
    ensure_manager(by)
    space = Space.objects.select_for_update().get(pk=space.pk)
    if space.archived_at is None:
        space.archived_at = timezone.now()
        space.save(update_fields=["archived_at", "updated_at"])
        _audit(KnowledgeAction.SPACE_ARCHIVED, space, by)
        _bump(space.company_id)
    return space


@transaction.atomic
def restore_space(space: Space, *, by: Membership | None) -> Space:
    ensure_manager(by)
    space = Space.objects.select_for_update().get(pk=space.pk)
    if space.archived_at is not None:
        space.archived_at = None
        space.save(update_fields=["archived_at", "updated_at"])
        _audit(KnowledgeAction.SPACE_CHANGED, space, by, changed=["archived_at"])
        _bump(space.company_id)
    return space


@transaction.atomic
def reorder_spaces(company, ids: list[int], *, by: Membership | None) -> None:
    ensure_manager(by)
    spaces = {space.pk: space for space in Space.objects.filter(company=company, pk__in=ids)}
    for index, pk in enumerate(ids):
        space = spaces.get(int(pk))
        if space is not None and space.position != index:
            space.position = index
            space.save(update_fields=["position", "updated_at"])
    _bump(company.pk)


# Pages ----------------------------------------------------------------------------------


def _next_position(space: Space, parent: Page | None) -> int:
    top = Page.objects.filter(space=space, parent=parent, archived_at__isnull=True).aggregate(
        top=Max("position")
    )["top"]
    return 0 if top is None else top + 1


def _check_parent(space: Space, parent: Page | None, *, subtree: int = 0) -> None:
    if parent is None:
        return
    if parent.space_id != space.pk or parent.company_id != space.company_id:
        raise DomainError(_("The page above must be in the same space."))
    if parent.archived_at is not None:
        raise DomainError(_("That page is archived."))
    if queries.depth_of(parent) + 1 + subtree > queries.MAX_DEPTH:
        raise DomainError(_("Pages nest at most four levels deep."))


def _write_version(page: Page, by: Membership | None, note: str = "") -> PageVersion:
    return PageVersion.objects.create(
        company_id=page.company_id,
        page=page,
        version=page.version,
        title=page.title,
        emoji=page.emoji,
        body=page.body,
        note=(note or "").strip()[:200],
        created_by=by,
    )


def _self_ack(page: Page, by: Membership | None) -> None:
    """Whoever publishes or rewrites a must-read page has read that version."""
    if by is None or not page.require_ack or not page.published:
        return
    PageAck.objects.get_or_create(
        company_id=page.company_id,
        page=page,
        membership=by,
        version=page.version,
        defaults={"at": timezone.now()},
    )


@transaction.atomic
def create_page(
    space: Space,
    *,
    by: Membership | None,
    title: str,
    emoji: str = "",
    body: str = "",
    parent: Page | None = None,
    require_ack: bool = False,
    publish: bool = False,
    notify_readers: bool = True,
) -> Page:
    ensure_manager(by)
    if space.archived_at is not None:
        raise DomainError(_("This space is archived."))
    _check_parent(space, parent)
    clean = _clean_body(body)
    page = Page.objects.create(
        company_id=space.company_id,
        space=space,
        parent=parent,
        title=_clean_title(title),
        emoji=_clean_emoji(emoji),
        body=clean,
        body_text=sanitize.to_text(clean),
        position=_next_position(space, parent),
        require_ack=require_ack,
        created_by=by,
        updated_by=by,
    )
    _write_version(page, by, note=_("First version"))
    _attach_images(page)
    _audit(KnowledgeAction.PAGE_CREATED, page, by, title=page.title)
    _bump(page.company_id)
    if publish:
        page = publish_page(page, by=by, notify_readers=notify_readers)
    return page


@transaction.atomic
def save_page(
    page: Page,
    *,
    by: Membership | None,
    title: str | None = None,
    emoji: str | None = None,
    body: str | None = None,
    require_ack: bool | None = None,
    note: str = "",
    base_version: int | None = None,
    reread: bool = False,
    notify_readers: bool = True,
) -> Page:
    """Save an edit. A change of title, emoji or body writes a new version; `base_version`
    (the version the editor started from) refuses to overwrite someone else's newer save."""
    ensure_manager(by)
    page = Page.objects.select_for_update().select_related("space").get(pk=page.pk)
    if page.archived_at is not None:
        raise DomainError(_("This page is archived. Restore it first."))
    if base_version is not None and base_version != page.version:
        raise DomainError(
            _("Someone saved a newer version of this page. Reload it and make your change again.")
        )
    changed = []
    if title is not None and _clean_title(title) != page.title:
        page.title = _clean_title(title)
        changed.append("title")
    if emoji is not None and _clean_emoji(emoji) != page.emoji:
        page.emoji = _clean_emoji(emoji)
        changed.append("emoji")
    if body is not None:
        clean = _clean_body(body)
        if clean != page.body:
            page.body = clean
            page.body_text = sanitize.to_text(clean)
            changed.append("body")
    content_changed = bool(changed)
    if require_ack is not None and require_ack != page.require_ack:
        page.require_ack = require_ack
        changed.append("require_ack")
    if content_changed:
        page.version += 1
    ask_again = reread and page.published and (content_changed or page.ack_version < page.version)
    if ask_again:
        page.ack_version = page.version
        page.ack_since = timezone.now()
    if not changed and not ask_again:
        return page
    page.updated_by = by
    page.save()
    if content_changed:
        _write_version(page, by, note)
        _attach_images(page)
    _audit(KnowledgeAction.PAGE_SAVED, page, by, changed=changed, version=page.version)
    _self_ack(page, by)
    _bump(page.company_id)
    if ask_again and notify_readers:
        _notify_published(page, by, updated=True)
    return page


@transaction.atomic
def publish_page(page: Page, *, by: Membership | None, notify_readers: bool = True) -> Page:
    """Make a draft readable. Readers hear about it (unless `notify_readers` is off or the
    company switched that off), and must confirm this version when the page asks for it."""
    ensure_manager(by)
    page = Page.objects.select_for_update().select_related("space").get(pk=page.pk)
    if page.archived_at is not None:
        raise DomainError(_("This page is archived. Restore it first."))
    if page.published:
        return page
    if not page.body_text.strip():
        raise DomainError(_("Write something on the page before publishing it."))
    page.published = True
    page.published_at = timezone.now()
    page.ack_version = page.version
    page.ack_since = page.published_at
    page.updated_by = by
    page.save()
    _audit(KnowledgeAction.PAGE_PUBLISHED, page, by, version=page.version)
    _self_ack(page, by)
    _bump(page.company_id)
    if notify_readers:
        _notify_published(page, by, updated=False)
    return page


@transaction.atomic
def unpublish_page(page: Page, *, by: Membership | None) -> Page:
    ensure_manager(by)
    page = Page.objects.select_for_update().get(pk=page.pk)
    if page.published:
        page.published = False
        page.updated_by = by
        page.save(update_fields=["published", "updated_by", "updated_at"])
        _audit(KnowledgeAction.PAGE_UNPUBLISHED, page, by)
        _bump(page.company_id)
    return page


@transaction.atomic
def move_page(
    page: Page,
    *,
    by: Membership | None,
    parent: Page | None,
    index: int,
    space: Space | None = None,
) -> Page:
    """Put `page` at `index` among the children of `parent` (the top of `space` when None).
    Its pages move with it."""
    ensure_manager(by)
    page = Page.objects.select_for_update().select_related("space").get(pk=page.pk)
    target_space = space or (parent.space if parent is not None else page.space)
    if target_space.company_id != page.company_id:
        raise DomainError(_("Pick a space of this company."))
    if parent is not None and (parent.pk == page.pk or parent.pk in queries.descendant_ids(page)):
        raise DomainError(_("A page can't go inside itself."))
    _check_parent(target_space, parent, subtree=queries.subtree_depth(page))
    moved_space = target_space.pk != page.space_id
    siblings = list(
        Page.objects.select_for_update()
        .filter(space=target_space, parent=parent, archived_at__isnull=True)
        .exclude(pk=page.pk)
        .order_by("position", "pk")
    )
    index = max(0, min(int(index), len(siblings)))
    siblings.insert(index, page)
    page.space = target_space
    page.parent = parent
    for position, sibling in enumerate(siblings):
        if sibling.pk == page.pk:
            page.position = position
            continue
        if sibling.position != position:
            sibling.position = position
            sibling.save(update_fields=["position", "updated_at"])
    page.save(update_fields=["space", "parent", "position", "updated_at"])
    if moved_space:
        Page.objects.filter(pk__in=queries.descendant_ids(page)).update(space=target_space)
    _audit(
        KnowledgeAction.PAGE_MOVED,
        page,
        by,
        space=target_space.pk,
        parent=parent.pk if parent else None,
        index=index,
    )
    _bump(page.company_id)
    return page


@transaction.atomic
def archive_page(page: Page, *, by: Membership | None) -> Page:
    """Archive a page and every page below it; readers stop seeing them."""
    ensure_manager(by)
    page = Page.objects.select_for_update().get(pk=page.pk)
    if page.archived_at is not None:
        return page
    now = timezone.now()
    ids = [page.pk, *queries.descendant_ids(page)]
    Page.objects.filter(pk__in=ids, archived_at__isnull=True).update(archived_at=now)
    page.archived_at = now
    _audit(KnowledgeAction.PAGE_ARCHIVED, page, by, pages=len(ids))
    _bump(page.company_id)
    return page


@transaction.atomic
def restore_page(page: Page, *, by: Membership | None) -> Page:
    """Bring back an archived page (and the pages archived with it) at the end of its level;
    if the page above it is still archived, it comes back at the top of its space."""
    ensure_manager(by)
    page = Page.objects.select_for_update(of=("self",)).select_related("parent").get(pk=page.pk)
    if page.archived_at is None:
        return page
    when = page.archived_at
    ids = [page.pk, *queries.descendant_ids(page)]
    Page.objects.filter(pk__in=ids, archived_at=when).update(archived_at=None)
    page.archived_at = None
    if page.parent is not None and page.parent.archived_at is not None:
        page.parent = None
    page.position = _next_position(page.space, page.parent)
    page.save(update_fields=["parent", "position", "archived_at", "updated_at"])
    _audit(KnowledgeAction.PAGE_RESTORED, page, by)
    _bump(page.company_id)
    return page


@transaction.atomic
def restore_version(page: Page, version: int, *, by: Membership | None) -> Page:
    """Save an earlier version again, as the newest one."""
    ensure_manager(by)
    old = PageVersion.objects.filter(page=page, version=version).first()
    if old is None:
        raise DomainError(_("That version doesn't exist."))
    page = save_page(
        page,
        by=by,
        title=old.title,
        emoji=old.emoji,
        body=old.body,
        note=_("Restored version %(n)d") % {"n": version},
    )
    _audit(KnowledgeAction.VERSION_RESTORED, page, by, version=version)
    return page


# Reading --------------------------------------------------------------------------------


def acknowledge(page: Page, *, by: Membership) -> PageAck:
    """`by` confirms reading the current version of `page` (once per version)."""
    if not queries.can_read(by, page):
        raise PermissionDenied(_("You don't have access to this page."))
    page = Page.objects.get(pk=page.pk)
    existing = PageAck.objects.filter(page=page, membership=by, version=page.version).first()
    if existing is not None:
        return existing
    try:
        with transaction.atomic():
            ack = PageAck.objects.create(
                company_id=page.company_id,
                page=page,
                version=page.version,
                membership=by,
                at=timezone.now(),
            )
    except IntegrityError:  # two taps at once
        return PageAck.objects.get(page=page, membership=by, version=page.version)
    _bump(page.company_id)
    return ack


def remind_unread(page: Page, *, by: Membership | None) -> int:
    """Ask everyone who hasn't confirmed the current version to read it; returns how many."""
    ensure_manager(by)
    if not page.published or page.archived_at is not None:
        raise DomainError(_("Only published pages can be read."))
    people = [
        person for person in queries.unread_audience(page) if by is None or person.pk != by.pk
    ]
    if not people:
        return 0
    with transaction.atomic():
        notify(
            people,
            KIND_REMINDER,
            title=lambda person: bot_messages.reminder_title(page),
            body=lambda person: bot_messages.page_excerpt(page),
            app_screen=bot_messages.app_screen(page),
            url=bot_messages.dashboard_url(page),
            target=page,
            actor=by,
            actions=_read_actions(),
        )
        if by is not None:
            _audit(KnowledgeAction.READERS_REMINDED, page, by, people=len(people))
    return len(people)


def _read_actions() -> list[NotificationAction]:
    return [NotificationAction("read", lambda person: bot_messages.read_button(), "primary")]


def _notify_published(page: Page, by: Membership | None, *, updated: bool) -> None:
    if not get_settings(page.company).notify_on_publish:
        return
    people = [
        person
        for person in queries.audience(page.space).select_related("user")
        if by is None or person.pk != by.pk
    ]
    if not people:
        return
    notify(
        people,
        KIND_PUBLISHED,
        title=lambda person: bot_messages.published_title(page, updated=updated),
        body=lambda person: bot_messages.page_excerpt(page),
        app_screen=bot_messages.app_screen(page),
        url=bot_messages.dashboard_url(page),
        target=page,
        actor=by,
        actions=_read_actions(),
        dedupe_key=f"knowledge:{page.pk}:v{page.ack_version}",
    )


def remind_due(now=None) -> int:
    """Celery: one reminder per page and ack version, `remind_unread_after_hours` after it was
    published (per the company's setting). Returns how many pages were handled."""
    now = now or timezone.now()
    handled = 0
    candidates = (
        Page.objects.filter(
            published=True, require_ack=True, archived_at__isnull=True, space__archived_at=None
        )
        .exclude(reminded_version__gte=F("ack_version"))
        .select_related("space", "company")
    )
    settings_by_company: dict[int, KnowledgeSettings] = {}
    for page in candidates:
        if not page.company.is_active:
            continue
        settings_row = settings_by_company.get(page.company_id)
        if settings_row is None:
            settings_row = settings_by_company[page.company_id] = get_settings(page.company)
        hours = settings_row.remind_unread_after_hours
        since = page.ack_since or page.published_at
        if not hours or since is None or (now - since).total_seconds() < hours * 3600:
            continue
        with transaction.atomic():
            locked = Page.objects.select_for_update(skip_locked=True).filter(pk=page.pk).first()
            if locked is None or locked.reminded_version >= locked.ack_version:
                continue
            Page.objects.filter(pk=page.pk).update(reminded_version=locked.ack_version)
            with translation.override(page.company.default_language):
                remind_unread(locked, by=None)
        handled += 1
    return handled


# Links ----------------------------------------------------------------------------------


@transaction.atomic
def link_page(
    page: Page, *, by: Membership | None, target_type: str, target_id: int, target_title: str = ""
) -> PageLink:
    ensure_manager(by)
    if target_type not in PageLink.Target.values:
        raise DomainError(_("Link a task or a routine."))
    title = targets.title(page.company_id, target_type, int(target_id), by=by)
    if title is None:
        raise DomainError(_("That task or routine doesn't exist."))
    link, created = PageLink.objects.get_or_create(
        company_id=page.company_id,
        page=page,
        target_type=target_type,
        target_id=int(target_id),
        defaults={"target_title": (title or target_title)[:200], "created_by": by},
    )
    if created:
        _audit(KnowledgeAction.PAGE_LINKED, page, by, target_type=target_type, target_id=target_id)
        _bump(page.company_id)
    return link


@transaction.atomic
def unlink(link: PageLink, *, by: Membership | None) -> None:
    ensure_manager(by)
    page = link.page
    _audit(
        KnowledgeAction.PAGE_UNLINKED,
        page,
        by,
        target_type=link.target_type,
        target_id=link.target_id,
    )
    link.delete()
    _bump(page.company_id)


# Pictures -------------------------------------------------------------------------------


def upload_image(company, file, *, by: Membership | None, page: Page | None = None) -> PageImage:
    """Re-encode a picture for a page and keep it in private storage."""
    ensure_manager(by)
    if page is not None and page.company_id != company.pk:
        raise DomainError(_("Pick a page of this company."))
    clean = sanitize_image(file, max_side=2000)
    image = PageImage(company=company, page=page, uploaded_by=by.user if by is not None else None)
    width, height = _size(clean)
    image.width, image.height = width, height
    image.file.save(clean.name, clean, save=False)
    image.save()
    return image


def _size(content) -> tuple[int, int]:
    from PIL import Image

    content.seek(0)
    with Image.open(content) as picture:
        size = picture.size
    content.seek(0)
    return size


def _attach_images(page: Page) -> None:
    """Pictures the body shows belong to the page (pictures uploaded before it was saved)."""
    ids = sanitize.image_ids(page.body)
    if ids:
        PageImage.objects.filter(company_id=page.company_id, pk__in=ids, page__isnull=True).update(
            page=page
        )


# Settings -------------------------------------------------------------------------------


@transaction.atomic
def update_settings(company, *, by: Membership | None, **changes) -> KnowledgeSettings:
    ensure_manager(by)
    row = get_settings(company)
    allowed = {"notify_on_publish", "remind_unread_after_hours"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError(f"Can't change {sorted(unknown)} in the knowledge settings.")
    for name, value in changes.items():
        setattr(row, name, value)
    row.save()
    if by is not None:
        audit.record(
            KnowledgeAction.SETTINGS_CHANGED,
            company_id=company.pk,
            actor=by.user,
            target=row,
            changed=sorted(changes),
        )
    _bump(company.pk)
    return row
