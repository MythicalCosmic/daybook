"""Read functions about announcements: the console's list with read rates, the employee feed,
audience counts and read-rate statistics."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Count, Exists, OuterRef, Q, QuerySet
from django.utils import timezone

from apps.announcements import telegram_html
from apps.announcements.models import Announcement, Receipt
from apps.companies.models import Branch, Company
from apps.members import scope
from apps.members.models import Membership, Position


def for_console(viewer: Membership) -> QuerySet[Announcement]:
    """Announcements an announcer may see, with `recipients_count` and `read_count`: every one,
    or for someone limited to some branches, theirs and those sent to one of their branches."""
    rows = Announcement.objects.filter(company_id=viewer.company_id)
    allowed = scope.branch_ids(viewer)
    if allowed is not None:
        to_mine = Announcement.objects.filter(
            company_id=viewer.company_id, branches__in=allowed
        ).values("pk")
        rows = rows.filter(Q(pk__in=to_mine) | Q(author=viewer))
    return rows.annotate(
        recipients_count=Count("receipts", distinct=True),
        read_count=Count("receipts", filter=Q(receipts__read_at__isnull=False), distinct=True),
    ).select_related("author__user")


def feed(member: Membership, *, pinned: bool | None = None, now: datetime | None = None):
    """What `member` received, newest first with pinned ones on top; expired ones are gone.
    `pinned=True` keeps only pinned ones."""
    now = now or timezone.now()
    rows = (
        Announcement.objects.filter(
            company_id=member.company_id,
            status=Announcement.Status.SENT,
            receipts__membership=member,
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .annotate(
            is_pinned=Exists(Announcement.objects.filter(pk=OuterRef("pk"), pinned_until__gt=now)),
            read_at=Receipt.objects.filter(announcement=OuterRef("pk"), membership=member).values(
                "read_at"
            )[:1],
        )
        .select_related("author__user")
    )
    if pinned is True:
        rows = rows.filter(pinned_until__gt=now)
    elif pinned is False:
        rows = rows.exclude(pinned_until__gt=now)
    return rows.order_by("-is_pinned", "-sent_at", "-pk")


def audience_count(company: Company, viewer: Membership, position_ids, branch_ids) -> dict:
    """How many people an announcement to these positions and branches reaches right now (the
    composer's live count), and a few of their names."""
    from apps.announcements.services import audience

    positions = list(Position.objects.for_company(company).filter(pk__in=position_ids))
    branches = list(Branch.objects.for_company(company).filter(pk__in=branch_ids))
    allowed = scope.branch_ids(viewer)
    if allowed is not None:
        branches = [branch for branch in branches if branch.pk in allowed] or list(
            Branch.objects.for_company(company).filter(pk__in=allowed)
        )
    people = audience(company.pk, positions, branches).exclude(pk=viewer.pk)
    sample = list(people.select_related("user").order_by("first_name", "last_name")[:6])
    return {
        "count": people.count(),
        "sample": [{"id": person.pk, "name": str(person)} for person in sample],
    }


def read_rates(company: Company, start: date, end: date) -> list[dict]:
    """Every announcement sent from `start` to `end` (inclusive, company days): recipients,
    read and the read rate in percent (a string, one decimal)."""
    tz = ZoneInfo(company.timezone)
    since = datetime.combine(start, time.min, tzinfo=tz)
    until = datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz)
    rows = (
        Announcement.objects.filter(
            company=company,
            status=Announcement.Status.SENT,
            sent_at__gte=since,
            sent_at__lt=until,
        )
        .annotate(
            recipients_count=Count("receipts", distinct=True),
            read_count=Count("receipts", filter=Q(receipts__read_at__isnull=False), distinct=True),
        )
        .select_related("author__user")
        .order_by("-sent_at")
    )
    return [
        {
            "id": row.pk,
            "title": title(row),
            "sent_at": row.sent_at.isoformat() if row.sent_at else None,
            "author": str(row.author) if row.author else None,
            "recipients": row.recipients_count,
            "read": row.read_count,
            "rate": rate(row.read_count, row.recipients_count),
        }
        for row in rows
    ]


def stats(viewer: Membership, now: datetime) -> dict:
    """The numbers above the announcements list (last 30 days, in the viewer's view)."""
    rows = for_console(viewer)
    since = now - timedelta(days=30)
    sent = rows.filter(status=Announcement.Status.SENT, sent_at__gte=since)
    recipients = sum(row.recipients_count for row in sent)
    read = sum(row.read_count for row in sent)
    return {
        "sent_30d": sent.count(),
        "read_rate_30d": rate(read, recipients),
        "scheduled": rows.filter(status=Announcement.Status.SCHEDULED).count(),
        "pinned": rows.filter(status=Announcement.Status.SENT, pinned_until__gt=now).count(),
        "unread_people_30d": recipients - read,
    }


def title(announcement: Announcement, limit: int = 80) -> str:
    """The first line of the text, without formatting."""
    first = telegram_html.plain(announcement.text).split("\n")[0].strip()
    return first if len(first) <= limit else f"{first[: limit - 1]}…"


def rate(read: int, total: int) -> str | None:
    if not total:
        return None
    return f"{100 * read / total:.1f}"


def search(member: Membership, q: str, limit: int):
    rows = for_console(member).filter(text__icontains=q).order_by("-created_at")[:limit]
    return list(rows)
