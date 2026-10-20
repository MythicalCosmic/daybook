"""Read-only AI tools about the team (docs/PLAN-OWNER.md §8.3). They act as the person asking:
their company, their branch scope, nothing they couldn't open in the dashboard."""

from datetime import timedelta

from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, Field

from apps.ai.tools.registry import ToolContext, ToolNotFound, ToolResult, ai_tool
from apps.members import queries
from apps.members.models import Membership
from apps.members.permissions import Perm


class DirectoryInput(BaseModel):
    q: str | None = Field(default=None, description="Part of a name or position.")
    status: str = Field(
        default="current",
        description="current (working now), suspended, left, blocked, former or pending.",
    )


@ai_tool(
    "members_directory",
    domain="people",
    perm=Perm.MEMBERS_VIEW,
    label=_("Team directory: who works here, their position, role, branch and on-time rate"),
    input=DirectoryInput,
)
def members_directory(ctx: ToolContext, args: DirectoryInput) -> ToolResult:
    status = args.status if args.status in queries.DIRECTORY_STATUSES else "current"
    people = list(
        queries.directory(
            ctx.company,
            branch_ids=ctx.branch_ids,
            q=(args.q or "").strip() or None,
            status=status,
            include=ctx.membership,
        ).order_by("first_name", "last_name")[:200]
    )
    scores = queries.work_scores(ctx.company, [p.pk for p in people], ctx.now)
    rows = [
        {
            "id": person.pk,
            "name": str(person),
            "position": person.position.name if person.position else None,
            "role": person.role.name if person.role else None,
            "home_branch": person.home_branch.name if person.home_branch else None,
            "status": person.status,
            "suspended_until": person.suspended_until.isoformat()
            if person.suspended_until
            else None,
            "on_time_percent_30d": scores[person.pk]["on_time_30d"],
            "late_now": scores[person.pk]["late_now"],
        }
        for person in people
    ]
    return ToolResult(rows=rows, as_of=ctx.now)


class PersonInput(BaseModel):
    member_id: int = Field(description="The person's id from members_directory.")


@ai_tool(
    "members_person",
    domain="people",
    perm=Perm.MEMBERS_VIEW,
    label=_("One person's numbers: tenure, on-time rate and trend, open and late work, time off"),
    input=PersonInput,
)
def members_person(ctx: ToolContext, args: PersonInput) -> ToolResult:
    person = (
        Membership.objects.filter(company=ctx.company, pk=args.member_id)
        .select_related("user", "role", "position", "home_branch", "company")
        .first()
    )
    if person is None or not _visible(ctx, person):
        raise ToolNotFound
    today = timezone.localtime(ctx.now).date()
    overview = queries.person_overview(person, today - timedelta(days=29), today, ctx.now)
    data = {
        "id": person.pk,
        "name": str(person),
        "position": person.position.name if person.position else None,
        "role": person.role.name if person.role else None,
        "status": person.status,
        **{key: overview[key] for key in overview if key != "upcoming_time_off"},
        "upcoming_time_off": overview["upcoming_time_off"],
    }
    return ToolResult(data=data, as_of=ctx.now)


def _visible(ctx: ToolContext, person: Membership) -> bool:
    if ctx.branch_ids is None or person.pk == ctx.membership.pk:
        return True
    return person.branches.filter(pk__in=ctx.branch_ids).exists()
