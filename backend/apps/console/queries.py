"""Read functions of the owner console, for other apps, the dashboard and the AI tools.

A function returning branch-bound data takes the required keyword
`branch_ids: list[int] | None` (callers pass `apps.members.scope.branch_ids(member)`).
"""

import zoneinfo
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from django.db.models import Prefetch, Q
from django.utils import timezone

from apps.accounts.models import User
from apps.companies.models import Branch, Feature
from apps.console import pulse, registry
from apps.console.models import SavedView
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.timeoff.models import Holiday

# A branch counts as "not opened" this long after its opening time with nothing recorded.
OPENING_GRACE = timedelta(minutes=10)


class BranchStatus:
    OPEN = "open"
    NOT_OPENED = "not_opened"
    CLOSED = "closed"
    DAY_OFF = "day_off"


BRANCH_STATUSES = (
    BranchStatus.OPEN,
    BranchStatus.NOT_OPENED,
    BranchStatus.CLOSED,
    BranchStatus.DAY_OFF,
)


def top_memberships(user: User) -> list[Membership]:
    """The memberships through which `user` uses the owner bot: dashboard access, as an owner or
    a top manager (apps.members.departments.is_top_manager)."""
    from apps.members.departments import is_top_manager

    return [member for member in owner_memberships(user) if is_top_manager(member)]


def owner_memberships(user: User) -> list[Membership]:
    """Every membership through which `user` may open the dashboard, by company name."""
    memberships = (
        Membership.objects.filter(
            user=user, status=Membership.Status.APPROVED, company__is_active=True
        )
        .filter(Q(role__is_owner=True) | Q(role__permissions__contains=[Perm.DASHBOARD_ACCESS]))
        .select_related("company", "role", "home_branch", "user")
        .prefetch_related(
            Prefetch(
                "branches",
                queryset=Branch.objects.filter(is_active=True).order_by("order", "name"),
                to_attr="active_branches",
            )
        )
        .order_by("company__name", "company_id")
    )
    return list(memberships)


def visible_branches(member: Membership) -> list[Branch]:
    """Active branches inside the member's scope, in display order."""
    branches = Branch.objects.for_company(member.company).filter(is_active=True)
    return list(scope.restrict(branches, scope.branch_ids(member), field="id"))


def me_companies(user: User) -> list[dict]:
    """The `companies` of `GET /owner/me/`."""
    memberships = owner_memberships(user)
    every_branch = defaultdict(list)
    for branch in Branch.objects.filter(
        company__in=[m.company_id for m in memberships], is_active=True
    ).order_by("order", "name"):
        every_branch[branch.company_id].append(branch)

    companies = []
    for member in memberships:
        company = member.company
        branch_scope = scope.branch_ids(member)
        branches = every_branch[company.pk] if branch_scope is None else member.active_branches
        home = member.home_branch
        companies.append(
            {
                "id": company.pk,
                "name": company.name,
                "logo": company.logo.url if company.logo else None,
                "timezone": company.timezone,
                "base_currency": company.base_currency,
                "features": list(company.features),
                "role": {"id": member.role_id, "name": member.role.name} if member.role else None,
                "is_owner": bool(member.role and member.role.is_owner),
                "permissions": [perm.value for perm in Perm if member.has_perm(perm)],
                "branch_scope": branch_scope,
                "branches": [{"id": b.pk, "name": b.name, "code": b.code} for b in branches],
                "home_branch": {"id": home.pk, "name": home.name} if home else None,
                "pending": pulse.counters(member).get("console.queue", 0),
                "setup_completed": company.setup_completed_at is not None,
                "membership_id": member.pk,
            }
        )
    return companies


def branches_today(member: Membership, now: datetime) -> list[dict]:
    """Branch cards (`GET branches/today/`): fixed facts from the registered providers."""
    company = member.company
    local = timezone.localtime(now, zoneinfo.ZoneInfo(company.timezone))
    day = local.date()
    branches = visible_branches(member)
    holiday = Holiday.objects.filter(company=company, date=day).exists()
    facts = registry.collect_branch_facts(member, day, now, [branch.pk for branch in branches])
    # Only a till or a check-in records that a branch opened: without either module a branch
    # (a distributor's warehouse, an office) goes by its hours instead of "not opened" all day.
    records_openings = company.has_feature(Feature.SALES) or company.has_feature(Feature.ATTENDANCE)
    cards = []
    for branch in branches:
        card = {
            "id": branch.pk,
            "name": branch.name,
            "code": branch.code,
            "opens_at": _clock(branch.opens_at),
            "closes_at": _clock(branch.closes_at),
        }
        for key, by_branch in facts.items():
            if branch.pk in by_branch:
                card[key] = by_branch[branch.pk]
        card["status"] = branch_status(
            branch, local, holiday=holiday, card=card, records_openings=records_openings
        )
        cards.append(card)
    return cards


def branch_status(
    branch: Branch, local: datetime, *, holiday: bool, card: dict, records_openings: bool = True
) -> str:
    """open (a till or the first check-in opened it), not_opened (an open day, more than 10
    minutes past `opens_at`, nothing recorded), closed (after `closes_at`, or not open yet) or
    day_off (a weekday it doesn't open, or a holiday). When the company runs neither sales nor
    attendance (`records_openings` off), nothing can record an opening: a branch is open within
    its hours on an open day, never not_opened."""
    opened = bool(
        (card.get("sales") or {}).get("opened_at")
        or (card.get("attendance") or {}).get("first_check_in")
    )
    day_off = holiday or local.weekday() not in branch.open_weekdays
    if day_off and not opened:
        return BranchStatus.DAY_OFF
    if _after_closing(branch, local.time()):
        return BranchStatus.CLOSED
    if opened:
        return BranchStatus.OPEN
    if not records_openings:
        return BranchStatus.OPEN if _within_hours(branch, local.time()) else BranchStatus.CLOSED
    if branch.opens_at is not None and local >= _at(local.date(), branch.opens_at, local) + (
        OPENING_GRACE
    ):
        return BranchStatus.NOT_OPENED
    return BranchStatus.CLOSED


def saved_views(member: Membership, *, module: str | None = None):
    """The member's own saved views and the ones colleagues shared."""
    views = SavedView.objects.for_company(member.company).filter(
        Q(membership=member) | Q(is_shared=True)
    )
    if module:
        views = views.filter(module=module)
    # The owner's name falls back to their user's when the membership has none.
    return views.select_related("membership__user").order_by("module", "order", "name", "pk")


def _after_closing(branch: Branch, now: time) -> bool:
    opens, closes = branch.opens_at, branch.closes_at
    if closes is None:
        return False
    if opens is not None and closes < opens:  # open past midnight, e.g. 18:00-02:00
        return closes <= now < opens
    return now >= closes


def _within_hours(branch: Branch, now: time) -> bool:
    opens, closes = branch.opens_at, branch.closes_at
    if opens is None:
        return False
    if closes is None:
        return now >= opens
    if closes < opens:  # open past midnight
        return now >= opens or now < closes
    return opens <= now < closes


def _at(day: date, clock: time, local: datetime) -> datetime:
    return datetime.combine(day, clock, tzinfo=local.tzinfo)


def _clock(value: time | None) -> str | None:
    return value.strftime("%H:%M") if value else None
