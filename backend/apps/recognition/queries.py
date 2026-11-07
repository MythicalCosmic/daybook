"""Read functions of recognition, for other apps, the dashboard and the AI tools.

A function returning branch-bound data takes the required keyword
`branch_ids: list[int] | None` (callers pass `apps.members.scope.branch_ids(member)`).

**The contract other apps call** (docs/PLAN-LEARNING.md §7.4; pinned by tests/test_contract.py):
`summary(member)` (points, level and streak for a profile or a card) and `levels()`.

Leaderboards (§7.6): points in a period (this week Monday to Sunday, this month, all time, in
the company's time), for the company or some branches. People with no points aren't listed;
ties go to whoever got there first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Max, Q, QuerySet, Sum
from django.utils import timezone

from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.recognition import badges as catalogue
from apps.recognition import conf, rules
from apps.recognition.models import BadgeAward, Kudos, LevelUp, PointsEntry, Streak

PERIODS = ("week", "month", "all")
STAFF_ROWS = 10
# Points that come from learning (the "top learners" card, the tutor's praise).
LEARNING_REASONS = (
    PointsEntry.Reason.LESSON,
    PointsEntry.Reason.PAGE,
    PointsEntry.Reason.QUIZ,
    PointsEntry.Reason.QUIZ_PERFECT,
    PointsEntry.Reason.COURSE,
    PointsEntry.Reason.DAILY,
    PointsEntry.Reason.CHECK,
    PointsEntry.Reason.STREAK,
)


@dataclass(frozen=True)
class Level:
    number: int
    name: str  # in the active language
    starts_at: int  # total points where it starts
    next_at: int | None  # where the next level starts (None: the top one)


@dataclass(frozen=True)
class Summary:
    points: int  # all-time total
    week_points: int  # since Monday (the company's week)
    level: Level
    streak: int
    best_streak: int
    badges: int
    badge_keys: list[str] = field(default_factory=list)  # the newest first


def level_of(total: int) -> Level:
    info = rules.level_info(rules.level_number(total))
    return Level(
        number=info.number,
        name=rules.level_name(info.number),
        starts_at=info.starts_at,
        next_at=info.next_at,
    )


def levels() -> list[Level]:
    """Every level, lowest first, named in the active language (apps.recognition.rules)."""
    return [level_of(start) for start in rules.LEVELS]


def local_today(company, now: datetime | None = None) -> date:
    return timezone.localtime(now or timezone.now(), ZoneInfo(company.timezone)).date()


def period_bounds(
    company, period: str, *, day: date | None = None, now: datetime | None = None
) -> tuple[datetime | None, datetime | None]:
    """[start, end) of the week (Monday to Sunday) or month holding `day` (default today), in
    the company's time; (None, None) for all time."""
    if period not in PERIODS:
        raise ValueError(f"Unknown period {period!r}.")
    if period == "all":
        return None, None
    tz = ZoneInfo(company.timezone)
    day = day or local_today(company, now)
    if period == "week":
        first = day - timedelta(days=day.weekday())
        last = first + timedelta(days=7)
    else:
        first = day.replace(day=1)
        last = (first + timedelta(days=32)).replace(day=1)
    return (
        datetime.combine(first, datetime.min.time(), tzinfo=tz),
        datetime.combine(last, datetime.min.time(), tzinfo=tz),
    )


def totals(member_ids, *, start: datetime | None = None) -> dict[int, int]:
    entries = PointsEntry.objects.filter(membership_id__in=list(member_ids))
    if start is not None:
        entries = entries.filter(at__gte=start)
    return dict(
        entries.values("membership_id")
        .annotate(total=Sum("points"))
        .values_list("membership_id", "total")
    )


def summary(member: Membership) -> Summary | None:
    """`member`'s points, level, streak and badges; None while the module is off."""
    if not conf.is_on(member.company):
        return None
    start, _end = period_bounds(member.company, "week")
    numbers = PointsEntry.objects.filter(membership=member).aggregate(
        total=Sum("points"), week=Sum("points", filter=Q(at__gte=start))
    )
    points = numbers["total"] or 0
    streak = Streak.objects.filter(membership=member, kind="learning").first()
    keys = list(
        BadgeAward.objects.filter(membership=member)
        .order_by("-awarded_at", "-pk")
        .values_list("badge", flat=True)
    )
    return Summary(
        points=points,
        week_points=numbers["week"] or 0,
        level=level_of(points),
        streak=current_streak(streak, member),
        best_streak=streak.best if streak else 0,
        badges=len(keys),
        badge_keys=keys,
    )


def current_streak(streak: Streak | None, member: Membership, now: datetime | None = None) -> int:
    """The streak as it stands today: a run whose next workday passed without learning is over
    (it shows 0 until the person learns again; the row changes only then)."""
    if streak is None or not streak.current or streak.last_day is None:
        return 0
    from apps.recognition import streaks

    today = local_today(member.company, now)
    if today <= streak.last_day + timedelta(days=1):
        return streak.current
    yesterday = today - timedelta(days=1)
    if streaks.workdays(member, streak.last_day + timedelta(days=1), yesterday):
        return 0
    return streak.current


# People and their pictures ---------------------------------------------------------------------


def person(membership: Membership) -> dict:
    """`{id, name, avatar_url, position}`: how recognition names someone."""
    photo = membership.user.photo if membership.user_id else None
    return {
        "id": membership.pk,
        "name": str(membership),
        "avatar_url": photo.url if photo else None,
        "position": membership.position.name if membership.position_id else None,
    }


def is_manager(member: Membership) -> bool:
    """People who see everyone's points in their scope (not only the top ten)."""
    return any(
        member.has_perm(perm)
        for perm in (Perm.MEMBERS_VIEW, Perm.LEARNING_VIEW, Perm.RECOGNITION_MANAGE)
    )


def own_branches(member: Membership) -> list[int] | None:
    """The branches a person works in (their home branch when they have none listed); None
    when they have neither (the board is then the company's)."""
    ids = sorted(member.branches.values_list("pk", flat=True))
    if ids:
        return ids
    return [member.home_branch_id] if member.home_branch_id else None


# Leaderboards ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class BoardRow:
    place: int
    member: Membership
    points: int
    level: Level  # by all-time points
    last_at: datetime | None


@dataclass(frozen=True)
class Board:
    period: str
    start: datetime | None
    end: datetime | None
    rows: list[BoardRow]

    def place_of(self, member_id: int) -> BoardRow | None:
        return next((row for row in self.rows if row.member.pk == member_id), None)


def people_in(company, branch_ids: list[int] | None) -> QuerySet[Membership]:
    people = Membership.objects.filter(company=company, status=Membership.Status.APPROVED)
    if branch_ids is not None:
        people = people.filter(branches__in=branch_ids)
    return people


def leaderboard(
    company,
    *,
    period: str,
    branch_ids: list[int] | None,
    day: date | None = None,
    now: datetime | None = None,
    reasons=None,
) -> Board:
    """Everyone with points in the period (approved people in `branch_ids`), most first."""
    start, end = period_bounds(company, period, day=day, now=now)
    entries = PointsEntry.objects.filter(
        company=company, membership__status=Membership.Status.APPROVED
    )
    if start is not None:
        entries = entries.filter(at__gte=start, at__lt=end)
    if reasons:
        entries = entries.filter(reason__in=list(reasons))
    if branch_ids is not None:
        entries = entries.filter(membership_id__in=people_in(company, branch_ids).values("pk"))
    ranked = list(
        entries.values("membership_id")
        .annotate(total=Sum("points"), last_at=Max("at", filter=~Q(points=0)))
        .filter(total__gt=0)
        .order_by("-total", "last_at", "membership_id")
    )
    ids = [row["membership_id"] for row in ranked]
    people = Membership.objects.select_related("user", "position").in_bulk(ids)
    all_time = totals(ids) if start is not None or reasons else {}
    rows = []
    for index, row in enumerate(ranked):
        member = people.get(row["membership_id"])
        if member is None:
            continue
        total = all_time.get(member.pk, row["total"]) if all_time else row["total"]
        rows.append(
            BoardRow(
                place=index + 1,
                member=member,
                points=row["total"],
                level=level_of(total),
                last_at=row["last_at"],
            )
        )
    return Board(period=period, start=start, end=end, rows=rows)


def period_points(member: Membership, period: str, *, now: datetime | None = None) -> int:
    start, end = period_bounds(member.company, period, now=now)
    entries = PointsEntry.objects.filter(membership=member)
    if start is not None:
        entries = entries.filter(at__gte=start, at__lt=end)
    return entries.aggregate(total=Sum("points"))["total"] or 0


def staff_board(
    member: Membership, *, period: str, scope: str = "company", now: datetime | None = None
) -> dict:
    """The mini app's leaderboard (§7.6): staff see the top ten of their scope and their own
    place (nothing while `leaderboard_for_staff` is off); managers see everyone they see."""
    company = member.company
    settings = conf.get_settings(company)
    manager = is_manager(member)
    mine = period_points(member, period, now=now)
    start, end = period_bounds(company, period, now=now)
    if not manager and not settings.leaderboard_for_staff:
        return {
            "visible": False,
            "period": period,
            "scope": scope,
            "start": start,
            "end": end,
            "rows": [],
            "me": {"place": None, "points": mine},
        }
    from apps.members import scope as member_scope

    if manager:
        seen = member_scope.branch_ids(member)
        branch_ids = seen
        if scope == "branch":
            own = own_branches(member) or []
            branch_ids = own if seen is None else [pk for pk in own if pk in seen]
    elif scope == "branch" or settings.leaderboard_scope == settings.Scope.BRANCH:
        scope = "branch"
        branch_ids = own_branches(member)
    else:
        branch_ids = None
    board = leaderboard(company, period=period, branch_ids=branch_ids, now=now)
    rows = board.rows if manager else board.rows[:STAFF_ROWS]
    me = board.place_of(member.pk)
    return {
        "visible": True,
        "period": period,
        "scope": scope,
        "start": start,
        "end": end,
        "rows": [board_row(row) for row in rows],
        "me": {"place": me.place if me else None, "points": me.points if me else mine},
    }


def board_row(row: BoardRow) -> dict:
    return {
        "place": row.place,
        "member": person(row.member),
        "points": row.points,
        "level": {"number": row.level.number, "name": row.level.name},
    }


# The person's achievements ---------------------------------------------------------------------


def topic_names(refs) -> dict[str, str]:
    ids = [int(ref) for ref in refs if str(ref).isdigit()]
    if not ids:
        return {}
    from apps.knowledge.models import Topic

    return {
        str(pk): name for pk, name in Topic.objects.filter(pk__in=ids).values_list("pk", "name")
    }


def badge_payload(award: BadgeAward, topics: dict[str, str]) -> dict:
    badge = catalogue.CATALOGUE.get(award.badge)
    return {
        "key": award.badge,
        "ref": award.ref,
        "name": catalogue.title(award.badge, award.ref, topic=topics.get(award.ref)),
        "description": badge.description() if badge else "",
        "icon": badge.icon if badge else "award",
        "tier": badge.tier if badge else catalogue.BRONZE,
        "awarded_at": award.awarded_at,
    }


def catalogue_payload(badge: catalogue.Badge) -> dict:
    return {
        "key": badge.key,
        "name": badge.name(),
        "description": badge.description(),
        "icon": badge.icon,
        "tier": badge.tier,
    }


def earned(member: Membership) -> list[BadgeAward]:
    return list(BadgeAward.objects.filter(membership=member).order_by("-awarded_at", "-pk"))


def unseen(member: Membership, awards: list[BadgeAward], topics: dict[str, str]) -> list[dict]:
    """What the app celebrates on opening: the newest level not seen yet, then the badges."""
    found = []
    level = (
        LevelUp.objects.filter(membership=member, seen_at__isnull=True).order_by("-number").first()
    )
    if level is not None:
        info = rules.level_info(level.number)
        found.append(
            {
                "type": "level",
                "number": level.number,
                "name": rules.level_name(level.number),
                "starts_at": info.starts_at,
                "next_at": info.next_at,
            }
        )
    for award in sorted(
        (row for row in awards if row.seen_at is None), key=lambda row: (row.awarded_at, row.pk)
    ):
        found.append({"type": "badge", **badge_payload(award, topics)})
    return found


def reason_label(reason: str) -> str:
    try:
        return str(PointsEntry.Reason(reason).label)
    except ValueError:
        return reason


def details(entries: list[PointsEntry]) -> dict[int, str]:
    """What each entry was for, in a few words: the lesson, test or course title, the task,
    who thanked, the owner's note."""
    found: dict[int, str] = {}
    wanted: dict[str, dict[int, list[int]]] = {}
    for entry in entries:
        if entry.reason == PointsEntry.Reason.ADJUST:
            found[entry.pk] = entry.note
            continue
        prefix, _sep, rest = entry.key.partition(":")
        object_id = rest.split(":")[0]
        if object_id.isdigit():
            wanted.setdefault(prefix, {}).setdefault(int(object_id), []).append(entry.pk)
    sources = {
        "lesson": ("apps.learning.models", "Lesson", "title"),
        "quiz": ("apps.learning.models", "Quiz", "title"),
        "quiz-perfect": ("apps.learning.models", "Quiz", "title"),
        "course": ("apps.learning.models", "Assignment", "course__title"),
        "page": ("apps.knowledge.models", "Page", "title"),
        "task": ("apps.tasks.models", "Task", "title"),
        "kudos": ("apps.recognition.models", "Kudos", "from_member"),
    }
    from importlib import import_module

    for prefix, ids in wanted.items():
        source = sources.get(prefix)
        if source is None:
            continue
        module, model_name, field_name = source
        model = getattr(import_module(module), model_name)
        if prefix == "kudos":
            names = {
                kudos.pk: str(kudos.from_member)
                for kudos in model.objects.select_related("from_member").filter(pk__in=ids)
            }
        else:
            names = dict(model.objects.filter(pk__in=ids).values_list("pk", field_name))
        for object_id, entry_ids in ids.items():
            if object_id in names:
                for entry_id in entry_ids:
                    found[entry_id] = str(names[object_id])
    return found


def history(member: Membership, *, limit: int = 30) -> list[dict]:
    """The person's points, newest first (entries worth nothing left out)."""
    entries = list(
        PointsEntry.objects.filter(membership=member)
        .exclude(points=0)
        .order_by("-at", "-pk")[:limit]
    )
    about = details(entries)
    return [
        {
            "id": entry.pk,
            "points": entry.points,
            "reason": entry.reason,
            "label": reason_label(entry.reason),
            "detail": about.get(entry.pk, ""),
            "at": entry.at,
        }
        for entry in entries
    ]


def kudos_today(member: Membership, *, now: datetime | None = None) -> list[Kudos]:
    """Thanks the person got today (the company's day), newest first."""
    tz = ZoneInfo(member.company.timezone)
    today = local_today(member.company, now)
    start = datetime.combine(today, datetime.min.time(), tzinfo=tz)
    return list(
        Kudos.objects.select_related("from_member__user", "from_member__position")
        .filter(to_member=member, hidden_at__isnull=True, created_at__gte=start)
        .order_by("-created_at")
    )


def me(member: Membership, *, now: datetime | None = None) -> dict:
    """Everything the mini app's achievements screen and Home chip show (§13 R)."""
    from apps.recognition import services

    company = member.company
    settings = conf.get_settings(company)
    start, _end = period_bounds(company, "week", now=now)
    numbers = PointsEntry.objects.filter(membership=member).aggregate(
        total=Sum("points"), week=Sum("points", filter=Q(at__gte=start))
    )
    points = numbers["total"] or 0
    level = level_of(points)
    streak = Streak.objects.filter(membership=member, kind="learning").first()
    awards = earned(member)
    topics = topic_names(award.ref for award in awards if award.badge == "topic_expert")
    have = {award.badge for award in awards}
    received = kudos_today(member, now=now)
    return {
        "enabled": settings.points_enabled,
        "points": points,
        "week_points": numbers["week"] or 0,
        "level": {
            "number": level.number,
            "name": level.name,
            "starts_at": level.starts_at,
            "next_at": level.next_at,
        },
        "streak": current_streak(streak, member, now),
        "best_streak": streak.best if streak else 0,
        "badges": [badge_payload(award, topics) for award in awards],
        "locked": [catalogue_payload(badge) for badge in catalogue.BADGES if badge.key not in have],
        "recent": history(member, limit=20),
        "unseen": unseen(member, awards, topics),
        "kudos_enabled": settings.kudos_enabled,
        "kudos_left": services.kudos_left(member, now=now) if settings.kudos_enabled else 0,
        "kudos_today": [kudos_payload(item, member) for item in received],
        "leaderboard": settings.leaderboard_for_staff or is_manager(member),
    }


# Kudos -----------------------------------------------------------------------------------------


def kudos_payload(kudos: Kudos, viewer: Membership | None = None) -> dict:
    return {
        "id": kudos.pk,
        "from": person(kudos.from_member),
        "to": person(kudos.to_member),
        "badge": kudos.badge,
        "badge_label": str(kudos.get_badge_display()),
        "message": kudos.message,
        "task": {"id": kudos.task_id, "title": kudos.task.title} if kudos.task_id else None,
        "at": kudos.created_at,
        "seen": kudos.seen_at is not None,
        "mine": viewer is not None and kudos.from_member_id == viewer.pk,
    }


def _kudos() -> QuerySet[Kudos]:
    return Kudos.objects.filter(hidden_at__isnull=True).select_related(
        "from_member__user",
        "from_member__position",
        "to_member__user",
        "to_member__position",
        "task",
    )


def kudos_box(member: Membership, box: str, *, limit: int = 50) -> list[Kudos]:
    """The person's thanks, received or given, newest first (hidden ones never)."""
    rows = _kudos().filter(company=member.company)
    rows = rows.filter(from_member=member) if box == "given" else rows.filter(to_member=member)
    return list(rows.order_by("-created_at", "-pk")[:limit])


def kudos_feed(
    company,
    *,
    branch_ids: list[int] | None,
    member_id: int | None = None,
    limit: int = 100,
    before: datetime | None = None,
) -> list[Kudos]:
    """The company's thanks in scope (either side works in one of `branch_ids`), newest first."""
    rows = _kudos().filter(company=company)
    if branch_ids is not None:
        people = Membership.objects.filter(company=company, branches__in=branch_ids).values("pk")
        rows = rows.filter(Q(to_member__in=people) | Q(from_member__in=people))
    if member_id is not None:
        rows = rows.filter(Q(to_member_id=member_id) | Q(from_member_id=member_id))
    if before is not None:
        rows = rows.filter(created_at__lt=before)
    return list(rows.order_by("-created_at", "-pk")[:limit])


def colleagues(member: Membership, q: str = "", *, limit: int = 50) -> list[Membership]:
    """Who the person can thank: approved colleagues in their team directory, not themselves."""
    from apps.members import scope
    from apps.members.queries import directory

    people = (
        directory(member.company, branch_ids=scope.branch_ids(member), q=q or None, status="active")
        .exclude(pk=member.pk)
        .order_by("first_name", "last_name", "pk")
    )
    return list(people[:limit])


# Badges in the company -------------------------------------------------------------------------


def badge_holders(company, *, branch_ids: list[int] | None) -> dict[str, list[BadgeAward]]:
    """Who has each badge (approved people in scope), the newest first."""
    awards = BadgeAward.objects.filter(
        company=company, membership__status=Membership.Status.APPROVED
    ).select_related("membership__user", "membership__position")
    if branch_ids is not None:
        awards = awards.filter(membership__in=people_in(company, branch_ids).values("pk"))
    found: dict[str, list[BadgeAward]] = {badge.key: [] for badge in catalogue.BADGES}
    for award in awards.order_by("-awarded_at", "-pk"):
        found.setdefault(award.badge, []).append(award)
    return found


def profile(member: Membership, *, now: datetime | None = None) -> dict:
    """A person's recognition for the dashboard: totals, level, streak, badges, history."""
    company = member.company
    week, _end = period_bounds(company, "week", now=now)
    month, _end = period_bounds(company, "month", now=now)
    numbers = PointsEntry.objects.filter(membership=member).aggregate(
        total=Sum("points"),
        week=Sum("points", filter=Q(at__gte=week)),
        month=Sum("points", filter=Q(at__gte=month)),
    )
    points = numbers["total"] or 0
    level = level_of(points)
    streak = Streak.objects.filter(membership=member, kind="learning").first()
    awards = earned(member)
    topics = topic_names(award.ref for award in awards if award.badge == "topic_expert")
    shown = Kudos.objects.filter(hidden_at__isnull=True)
    return {
        "member": person(member),
        "points": points,
        "week_points": numbers["week"] or 0,
        "month_points": numbers["month"] or 0,
        "level": {
            "number": level.number,
            "name": level.name,
            "starts_at": level.starts_at,
            "next_at": level.next_at,
        },
        "streak": current_streak(streak, member, now),
        "best_streak": streak.best if streak else 0,
        "badges": [badge_payload(award, topics) for award in awards],
        "history": history(member, limit=50),
        "kudos_received": shown.filter(to_member=member).count(),
        "kudos_given": shown.filter(from_member=member).count(),
    }
