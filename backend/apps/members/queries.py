"""Read functions about memberships: the team directory, one person's overview, join requests,
who holds a permission. Other apps and the AI tools call these instead of querying members.

Branch scope (§2.6): functions returning people take the required keyword `branch_ids`
(`members.scope.branch_ids(viewer)`; None means every branch, [] none at all).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Count, F, Q, QuerySet
from django.utils import timezone

from apps.companies.models import Company
from apps.members.models import AccessRole, Membership, Position
from apps.members.permissions import Perm

# People the directory shows by default: working here now (suspended people included).
CURRENT = (Membership.Status.APPROVED, Membership.Status.SUSPENDED)
DIRECTORY_STATUSES = {
    "active": (Membership.Status.APPROVED,),
    "current": CURRENT,
    "suspended": (Membership.Status.SUSPENDED,),
    "left": (Membership.Status.LEFT,),
    "blocked": (Membership.Status.BLOCKED,),
    "former": (Membership.Status.LEFT, Membership.Status.BLOCKED),
    "pending": (Membership.Status.PENDING,),
}


def suspended_ids(company: Company, day: date) -> set[int]:
    """Members suspended on `day` (an offdays provider: no daily tasks for them)."""
    suspended = Membership.objects.for_company(company).filter(status=Membership.Status.SUSPENDED)
    return set(
        suspended.filter(Q(suspended_until__isnull=True) | Q(suspended_until__gte=day)).values_list(
            "pk", flat=True
        )
    )


def members_with_perm(company: Company, perm: Perm) -> QuerySet[Membership]:
    """Approved members whose role grants `perm`."""
    return (
        Membership.objects.for_company(company)
        .filter(status=Membership.Status.APPROVED)
        .filter(Q(role__is_owner=True) | Q(role__permissions__contains=[str(perm)]))
    )


# Small shapes other apps reuse ----------------------------------------------------------


def photo_url(membership: Membership) -> str | None:
    photo = membership.user.photo
    return photo.url if photo else None


def person_ref(membership: Membership | None) -> dict | None:
    """`{id, name, photo_url}`: how owner endpoints name a person (the dashboard's PersonRef)."""
    if membership is None:
        return None
    return {"id": membership.pk, "name": str(membership), "photo_url": photo_url(membership)}


def branch_ref(branch) -> dict | None:
    if branch is None:
        return None
    return {"id": branch.pk, "name": branch.name, "code": branch.code}


# The directory --------------------------------------------------------------------------


def directory(
    company: Company,
    *,
    branch_ids: list[int] | None,
    q: str | None = None,
    position_id: int | list[int] | None = None,
    status: str | None = None,
    role_id: int | list[int] | None = None,
    branch: list[int] | None = None,
    include: Membership | None = None,
) -> QuerySet[Membership]:
    """The team directory: people of `company` inside `branch_ids` (people sharing one of
    those branches; everyone when None), plus `include` (the viewer sees themselves).

    `status` is one of DIRECTORY_STATUSES ("current" by default: approved and suspended),
    `position_id`/`role_id` one id or several, `branch` narrows to people in those branches
    (already intersected with the scope by the caller), `q` searches names, phone and
    Telegram username."""
    people = Membership.objects.for_company(company)
    if branch_ids is not None:
        visible = Q(branches__in=branch_ids)
        if include is not None:
            visible |= Q(pk=include.pk)
        people = people.filter(visible)
    statuses = DIRECTORY_STATUSES.get(status or "current", CURRENT)
    people = people.filter(status__in=statuses)
    if position_id:
        ids = position_id if isinstance(position_id, list) else [position_id]
        people = people.filter(position_id__in=ids)
    if role_id:
        ids = role_id if isinstance(role_id, list) else [role_id]
        people = people.filter(role_id__in=ids)
    if branch:
        people = people.filter(branches__in=branch)
    if q:
        for word in q.split()[:4]:
            people = people.filter(
                Q(first_name__icontains=word)
                | Q(last_name__icontains=word)
                | Q(user__phone__icontains=word)
                | Q(user__telegram_username__icontains=word)
                | Q(position__name__icontains=word)
            )
    if branch_ids is not None or branch:
        # Filtering across branches repeats a person per shared branch: keep one row each.
        people = Membership.objects.filter(pk__in=people.values("pk"))
    return people.select_related("user", "role", "position", "home_branch").prefetch_related(
        "branches"
    )


def in_scope(viewer: Membership, member: Membership) -> bool:
    """Whether `viewer` may see `member` in the console: themselves, or someone sharing one of
    the branches they see (everyone when they see every branch)."""
    from apps.members import scope

    if viewer.pk == member.pk:
        return True
    branches = scope.branch_ids(viewer)
    if branches is None:
        return True
    return member.branches.filter(pk__in=branches).exists()


# Numbers about people --------------------------------------------------------------------


def work_scores(company: Company, member_ids: list[int], now: datetime, *, days: int = 30) -> dict:
    """{member id: {"on_time_30d": "93" | None, "done_30d", "late_now", "open_now"}}: shared
    work (daily and assigned tasks, never personal ones) whose deadline fell in the last
    `days` days. Finished on time counts; work waiting for a check counts as finished."""
    from apps.tasks.models import Task

    if not member_ids:
        return {}
    tz = ZoneInfo(company.timezone)
    today = timezone.localtime(now, tz).date()
    since = datetime.combine(today - timedelta(days=days), time.min, tzinfo=tz)
    finished = (Task.Status.DONE, Task.Status.REVIEW)
    shared = Task.objects.filter(
        company=company,
        assignee_id__in=member_ids,
        kind__in=(Task.Kind.DAILY, Task.Kind.ASSIGNED),
    ).exclude(status=Task.Status.CANCELLED)
    rows = (
        shared.filter(due_at__gte=since, due_at__lt=now)
        .values("assignee_id")
        .annotate(
            on_time=Count("pk", filter=Q(status__in=finished, completed_at__lte=F("due_at"))),
            late=Count("pk", filter=Q(status__in=finished, completed_at__gt=F("due_at"))),
            missed=Count("pk", filter=Q(status__in=Task.OPEN_STATUSES)),
        )
    )
    scores = {
        row["assignee_id"]: {
            "on_time": row["on_time"],
            "total": row["on_time"] + row["late"] + row["missed"],
            "done": row["on_time"] + row["late"],
        }
        for row in rows
    }
    now_rows = (
        shared.filter(status__in=Task.OPEN_STATUSES)
        .values("assignee_id")
        .annotate(open=Count("pk"), late=Count("pk", filter=Q(due_at__lt=now)))
    )
    open_now = {row["assignee_id"]: row for row in now_rows}
    out = {}
    for member_id in member_ids:
        score = scores.get(member_id)
        current = open_now.get(member_id, {})
        percent = None
        if score and score["total"]:
            percent = f"{100 * score['on_time'] / score['total']:.1f}".removesuffix(".0")
        out[member_id] = {
            "on_time_30d": percent,
            "done_30d": score["done"] if score else 0,
            "late_now": current.get("late", 0),
            "open_now": current.get("open", 0),
        }
    return out


def on_time_trend(membership: Membership, now: datetime, *, weeks: int = 12) -> list[dict]:
    """Week by week (Monday first, oldest first): `{"date", "on_time_percent", "done",
    "total"}` of the person's shared work due that week, for the Person 360 chart."""
    from apps.tasks.models import Task

    tz = ZoneInfo(membership.company.timezone)
    today = timezone.localtime(now, tz).date()
    monday = today - timedelta(days=today.weekday())
    first = monday - timedelta(weeks=weeks - 1)
    since = datetime.combine(first, time.min, tzinfo=tz)
    tasks = (
        Task.objects.filter(
            assignee=membership,
            kind__in=(Task.Kind.DAILY, Task.Kind.ASSIGNED),
            due_at__gte=since,
            due_at__lt=now,
        )
        .exclude(status=Task.Status.CANCELLED)
        .values_list("due_at", "status", "completed_at")
    )
    buckets: dict[date, list[int]] = {first + timedelta(weeks=i): [0, 0] for i in range(weeks)}
    finished = (Task.Status.DONE, Task.Status.REVIEW)
    for due_at, status, completed_at in tasks:
        day = timezone.localtime(due_at, tz).date()
        week = day - timedelta(days=day.weekday())
        bucket = buckets.get(week)
        if bucket is None:
            continue
        bucket[1] += 1
        if status in finished and completed_at is not None and completed_at <= due_at:
            bucket[0] += 1
    return [
        {
            "date": week.isoformat(),
            "on_time_percent": round(100 * on_time / total, 1) if total else None,
            "done": on_time,
            "total": total,
        }
        for week, (on_time, total) in sorted(buckets.items())
    ]


def streak(membership: Membership, now: datetime, *, limit: int = 90) -> int:
    """Days in a row, up to yesterday, on which every shared task due that day was finished
    on time (days without such work don't break the run)."""
    from apps.tasks.models import Task

    tz = ZoneInfo(membership.company.timezone)
    today = timezone.localtime(now, tz).date()
    since = datetime.combine(today - timedelta(days=limit), time.min, tzinfo=tz)
    until = datetime.combine(today, time.min, tzinfo=tz)
    finished = (Task.Status.DONE, Task.Status.REVIEW)
    days: dict[date, bool] = {}
    for due_at, status, completed_at in (
        Task.objects.filter(
            assignee=membership,
            kind__in=(Task.Kind.DAILY, Task.Kind.ASSIGNED),
            due_at__gte=since,
            due_at__lt=until,
        )
        .exclude(status=Task.Status.CANCELLED)
        .values_list("due_at", "status", "completed_at")
    ):
        day = timezone.localtime(due_at, tz).date()
        good = status in finished and completed_at is not None and completed_at <= due_at
        days[day] = days.get(day, True) and good
    count = 0
    for day in sorted(days, reverse=True):
        if not days[day]:
            break
        count += 1
    return count


def person_overview(membership: Membership, start: date, end: date, now: datetime) -> dict:
    """The numbers on someone's Person 360: shared work from `start` to `end` (inclusive),
    right now, their streak and weekly on-time trend, tenure and time off this year."""
    from apps.tasks.models import Task
    from apps.timeoff.models import TimeOff

    company = membership.company
    tz = ZoneInfo(company.timezone)
    today = timezone.localtime(now, tz).date()
    since = datetime.combine(start, time.min, tzinfo=tz)
    until = min(datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz), now)
    finished = (Task.Status.DONE, Task.Status.REVIEW)
    shared = Task.objects.filter(
        assignee=membership, kind__in=(Task.Kind.DAILY, Task.Kind.ASSIGNED)
    ).exclude(status=Task.Status.CANCELLED)
    period = shared.filter(due_at__gte=since, due_at__lt=until).aggregate(
        on_time=Count("pk", filter=Q(status__in=finished, completed_at__lte=F("due_at"))),
        late=Count("pk", filter=Q(status__in=finished, completed_at__gt=F("due_at"))),
        missed=Count("pk", filter=Q(status__in=Task.OPEN_STATUSES)),
    )
    total = period["on_time"] + period["late"] + period["missed"]
    current = shared.filter(status__in=Task.OPEN_STATUSES).aggregate(
        open=Count("pk"), late=Count("pk", filter=Q(due_at__lt=now))
    )
    year_start = date(today.year, 1, 1)
    days_off = 0
    for first, last in TimeOff.objects.filter(
        membership=membership,
        status=TimeOff.Status.APPROVED,
        first_day__lte=today,
        last_day__gte=year_start,
    ).values_list("first_day", "last_day"):
        days_off += (min(last, today) - max(first, year_start)).days + 1
    upcoming = (
        TimeOff.objects.filter(
            membership=membership,
            status__in=(TimeOff.Status.PENDING, TimeOff.Status.APPROVED),
            last_day__gte=today,
        )
        .order_by("first_day")
        .values("id", "first_day", "last_day", "status", "reason")[:5]
    )
    joined = membership.decided_at or membership.created_at
    joined_on = timezone.localtime(joined, tz).date() if joined else None
    return {
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "on_time_percent": round(100 * period["on_time"] / total, 1) if total else None,
        "on_time": period["on_time"],
        "late": period["late"],
        "missed": period["missed"],
        "done": period["on_time"] + period["late"],
        "total": total,
        "open_now": current["open"],
        "late_now": current["late"],
        "streak": streak(membership, now),
        "trend": on_time_trend(membership, now),
        "joined_on": joined_on.isoformat() if joined_on else None,
        "tenure_days": (today - joined_on).days if joined_on else None,
        "days_off_this_year": days_off,
        "upcoming_time_off": [
            {
                "id": row["id"],
                "first_day": row["first_day"].isoformat(),
                "last_day": row["last_day"].isoformat(),
                "status": row["status"],
                "reason": row["reason"],
            }
            for row in upcoming
        ],
    }


def team_stats(viewer: Membership, now: datetime) -> dict:
    """The numbers above the team directory, inside `viewer`'s branch scope."""
    from apps.members import scope
    from apps.timeoff.models import TimeOff

    company = viewer.company
    branch_ids = scope.branch_ids(viewer)
    everyone = directory(company, branch_ids=branch_ids, status="current", include=viewer)
    ids = list(everyone.values_list("pk", flat=True))
    today = timezone.localtime(now, ZoneInfo(company.timezone)).date()
    month_ago = now - timedelta(days=30)
    former = directory(company, branch_ids=branch_ids, status="former")
    return {
        "current": len(ids),
        "active": everyone.filter(status=Membership.Status.APPROVED).count(),
        "suspended": everyone.filter(status=Membership.Status.SUSPENDED).count(),
        "on_leave_today": TimeOff.objects.filter(
            membership_id__in=ids,
            status=TimeOff.Status.APPROVED,
            first_day__lte=today,
            last_day__gte=today,
        )
        .values("membership_id")
        .distinct()
        .count(),
        "joined_30d": everyone.filter(decided_at__gte=month_ago).count(),
        "left_30d": former.filter(decided_at__gte=month_ago).count(),
        "pending_requests": pending_count(company) if viewer.has_perm(Perm.MEMBERS_APPROVE) else 0,
        "bot_blocked": everyone.filter(user__employee_bot_blocked_at__isnull=False).count(),
    }


# Join requests, roles, positions ----------------------------------------------------------


def join_requests(company: Company) -> QuerySet[Membership]:
    """People waiting for a decision, oldest first. Those who haven't created their account
    yet come last: there is nothing to decide on until they have."""
    return (
        Membership.objects.for_company(company)
        .filter(status=Membership.Status.PENDING)
        .select_related("user", "position")
        .order_by(F("onboarded_at").asc(nulls_last=True), "created_at")
    )


def pending_count(company: Company) -> int:
    """Join requests ready for a decision (the person filled in their details)."""
    return (
        Membership.objects.for_company(company)
        .filter(status=Membership.Status.PENDING, onboarded_at__isnull=False)
        .count()
    )


def former_member(membership: Membership) -> dict | None:
    """When someone asking to join worked here before: when they left and how ("left" or
    "blocked"), from the audit log; None for a first-timer."""
    from apps.audit.models import AuditLog

    row = (
        AuditLog.objects.filter(
            company_id=membership.company_id,
            target_type="membership",
            target_id=membership.pk,
            action__in=(AuditLog.Action.MEMBER_LEFT, AuditLog.Action.MEMBER_BLOCKED),
        )
        .order_by("-created_at")
        .first()
    )
    if row is None:
        return None
    left_on = (row.details or {}).get("terminated_on") or row.created_at.date().isoformat()
    how = "blocked" if row.action == AuditLog.Action.MEMBER_BLOCKED else "left"
    return {"left_on": left_on, "how": how}


def roles(company: Company) -> QuerySet[AccessRole]:
    """The company's roles with how many current members hold each, owners first."""
    return (
        AccessRole.objects.for_company(company)
        .annotate(members_count=Count("members", filter=Q(members__status__in=CURRENT)))
        .order_by("-is_owner", "name")
    )


def positions(company: Company, *, active: bool | None = None) -> QuerySet[Position]:
    rows = Position.objects.for_company(company).annotate(
        members_count=Count("members", filter=Q(members__status__in=CURRENT))
    )
    if active is not None:
        rows = rows.filter(is_active=active)
    return rows.order_by("order", "name")
