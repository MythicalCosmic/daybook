"""Read-only AI tools of recognition (docs/PLAN-LEARNING.md §10, PLAN-OWNER §8.3).

`recognition_leaderboard` answers who is ahead (points this week, month or all time, all points
or learning only) and `recognition_person` one person's points, level, streak, badges and
thanks, for the tutor and Ask AI. People the asker sees only (branch scope); names, points and
badges, never a phone or a note an owner wrote about a correction beyond its words.
"""

from typing import Literal

from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, Field

from apps.ai.tools.registry import ToolContext, ToolNotFound, ToolResult, ai_tool
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.recognition import queries


class LeaderboardInput(BaseModel):
    period: Literal["week", "month", "all"] = Field(
        "week", description="This week (Monday to Sunday), this month, or all time."
    )
    kind: Literal["all", "learning"] = Field(
        "all", description="All points, or only those from lessons, tests and the daily question."
    )
    limit: int = Field(10, ge=1, le=50, description="How many people to return, top first.")


@ai_tool(
    "recognition_leaderboard",
    domain="people",
    perm=Perm.MEMBERS_VIEW,
    label=_(
        "The leaderboard: who has the most points this week, this month or all time (all points "
        "or learning only), with their level"
    ),
    input=LeaderboardInput,
    feature="recognition",
)
def recognition_leaderboard(ctx: ToolContext, args: LeaderboardInput) -> ToolResult:
    board = queries.leaderboard(
        ctx.company,
        period=args.period,
        branch_ids=ctx.branch_ids,
        now=ctx.now,
        reasons=queries.LEARNING_REASONS if args.kind == "learning" else None,
    )
    rows = [
        {
            "id": row.member.pk,
            "place": row.place,
            "name": str(row.member),
            "position": row.member.position.name if row.member.position_id else None,
            "points": row.points,
            "level": row.level.number,
            "level_name": row.level.name,
        }
        for row in board.rows[: args.limit]
    ]
    return ToolResult(
        rows=rows,
        total=len(board.rows),
        data={
            "period": args.period,
            "kind": args.kind,
            "start": board.start.isoformat() if board.start else None,
            "end": board.end.isoformat() if board.end else None,
        },
        as_of=ctx.now,
    )


class PersonInput(BaseModel):
    member_id: int = Field(description="The person's id (from recognition_leaderboard or members).")


@ai_tool(
    "recognition_person",
    domain="people",
    perm=Perm.MEMBERS_VIEW,
    label=_(
        "One person's recognition: points (all time, this week, this month), level, learning "
        "streak, badges, thanks received and given, the latest points"
    ),
    input=PersonInput,
    feature="recognition",
)
def recognition_person(ctx: ToolContext, args: PersonInput) -> ToolResult:
    person = (
        Membership.objects.filter(company=ctx.company, pk=args.member_id)
        .select_related("user", "position", "company")
        .first()
    )
    if person is None or not _visible(ctx, person):
        raise ToolNotFound
    profile = queries.profile(person, now=ctx.now)
    data = {
        "id": person.pk,
        "name": str(person),
        "points": profile["points"],
        "week_points": profile["week_points"],
        "month_points": profile["month_points"],
        "level": profile["level"]["number"],
        "level_name": profile["level"]["name"],
        "next_level_at": profile["level"]["next_at"],
        "streak": profile["streak"],
        "best_streak": profile["best_streak"],
        "badges": [badge["name"] for badge in profile["badges"]],
        "kudos_received": profile["kudos_received"],
        "kudos_given": profile["kudos_given"],
        "recent": [
            {
                "points": row["points"],
                "for": row["label"],
                "detail": row["detail"],
                "at": row["at"].isoformat(),
            }
            for row in profile["history"][:10]
        ],
    }
    return ToolResult(data=data, as_of=ctx.now)


def _visible(ctx: ToolContext, person: Membership) -> bool:
    if ctx.branch_ids is None or person.pk == ctx.membership.pk:
        return True
    return person.branches.filter(pk__in=ctx.branch_ids).exists()
