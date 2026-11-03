"""Morning plan: each head and manager gets their team's day (v0.2 AI contract §3).

On the company's workdays at `at`: what their people have due today, what is late, what waits
for their check and who is off, in the bot they use; someone with nothing to say gets nothing.
It is about the team: everyone's own tasks come in the morning digest (apps.reports.digest),
and the group report goes to the team group, so nothing is said twice. With Claude, two
sentences on top sum it up (from these numbers only; no Claude, no summary).
"""

import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext
from pydantic import BaseModel
from pydantic import Field as PydanticField

from apps.ai import availability, bot_messages, client, events
from apps.ai.agents import registry, runner
from apps.ai.agents.registry import Agent, EventTemplate, Field
from apps.members import departments
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.notifications import tasks as telegram_jobs
from apps.notifications.telegram import BotName, serialize_markup
from apps.tasks import queries as task_queries
from apps.tasks.models import Task
from apps.tasks.offdays import people_off
from apps.timeoff.queries import is_holiday, members_off

logger = logging.getLogger(__name__)

KEY = "morning_plan"
BATCH = 200
LATE_SHOWN = 3


def next_run(config: dict, now: datetime, company) -> datetime:
    """The next `at` on one of the company's workdays, after `now`."""
    zone = ZoneInfo(company.timezone)
    workdays = company.workdays or None
    local = timezone.localtime(now, zone)
    at = time.fromisoformat(config["at"])
    day = local.date()
    for _attempt in range(8):
        moment = datetime.combine(day, at, tzinfo=zone)
        if moment > local and (workdays is None or day.weekday() in workdays):
            return moment
        day += timedelta(days=1)
    return datetime.combine(local.date() + timedelta(days=1), at, tzinfo=zone)


def _schedule(config: dict) -> str:
    return _("Workdays at %(time)s") % {"time": config["at"]}


def recipients(company, who: str) -> list[Membership]:
    """Heads (who manage people through departments) and managers (who give work to others),
    approved and registered."""
    people = (
        Membership.objects.for_company(company)
        .filter(status=Membership.Status.APPROVED, onboarded_at__isnull=False)
        .exclude(user__telegram_id__isnull=True)
        .select_related("user", "role", "company")
    )
    org = departments.Org(company.pk)  # the tree once, not once per person
    chosen = []
    for person in people[:BATCH]:
        heads = bool(departments.team_ids(person, org))
        manages = person.has_perm(Perm.TASKS_ASSIGN)
        if (
            (who == "heads" and heads)
            or (who == "managers" and manages)
            or (who == "both" and (heads or manages))
        ):
            chosen.append(person)
    return chosen


def team_day(member: Membership, now: datetime) -> dict:
    """The facts of a head's or manager's team today, from the database: only work the reader
    may open (`visible_tasks`: never someone's personal tasks, nor what their rights hide)."""
    zone = ZoneInfo(member.company.timezone)
    local = timezone.localtime(now, zone)
    today = local.date()
    start = datetime.combine(today, time.min, tzinfo=zone)
    end = start + timedelta(days=1)
    team = list(departments.assignable(member).values_list("pk", flat=True))
    work = task_queries.visible_tasks(member).filter(
        assignee_id__in=team, status__in=Task.OPEN_STATUSES
    )
    due_today = work.filter(due_at__gte=max(start, now), due_at__lt=end).count()
    late = list(
        work.filter(due_at__lt=now).select_related("assignee__user").order_by("due_at")[:50]
    )
    off_ids = (members_off(member.company, today) | people_off(member.company, today)) & set(team)
    off = list(
        Membership.objects.filter(pk__in=off_ids).select_related("user").order_by("first_name")
    )
    to_check = task_queries.awaiting_review_by(member).count()
    return {
        "team": len(team),
        "due_today": due_today,
        "late": late,
        "to_check": to_check,
        "off": off,
    }


class PlanSummary(BaseModel):
    summary: str = PydanticField(description="Two short sentences, in the reader's language.")


def _summary(member: Membership, day: dict) -> str:
    """Two sentences from Claude over the numbers; "" without Claude or on any failure."""
    company = member.company
    if not availability.status(company).available or availability.fake():
        return ""
    language = member.user.language
    facts = (
        f"Team size: {day['team']}. Due today: {day['due_today']}. Late: {len(day['late'])}. "
        f"Waiting for this manager's check: {day['to_check']}. Off today: {len(day['off'])}."
    )
    try:
        result, _call = client.structured(
            "morning_plan",
            company=company,
            membership=member,
            model=settings.AI_MODEL_FAST,
            schema=PlanSummary,
            effort="low",
            max_tokens=2000,
            system=(
                "You write a two-sentence morning summary for a pharmacy team's manager from "
                "the numbers given, in the requested language (Uzbek in Latin script). Use only "
                "these numbers; say what matters first."
            ),
            user=[{"type": "text", "text": f"<language>{language}</language>\n{facts}"}],
        )
    except client.ClaudeError:
        return ""
    return " ".join(result.summary.split())[:400]


def run(company, state, now: datetime) -> int:
    config = registry.config_of(AGENT, state)
    zone = ZoneInfo(company.timezone)
    local = timezone.localtime(now, zone)
    if local.weekday() not in (company.workdays or []) or is_holiday(company, local.date()):
        return 0
    sent = 0
    for member in recipients(company, config["who"]):
        key = f"plan:{member.pk}:{local.date().isoformat()}"
        if events.already(company, key):
            continue
        day = team_day(member, now)
        if not (day["due_today"] or day["late"] or day["to_check"] or day["off"]):
            continue  # nothing to say
        with translation.override(member.user.language):
            summary = _summary(member, day)
            text, markup = bot_messages.morning_plan(member, day, now, summary=summary)
        logged = events.log(
            company,
            KEY,
            "plan_sent",
            params={
                "to": str(member),
                "due_today": day["due_today"],
                "late": len(day["late"]),
                "to_check": day["to_check"],
            },
            subject=("member", member.pk),
            branch_id=member.home_branch_id,
            dedupe_key=key,
        )
        if logged is None:
            continue
        bot = _bot_of(member)
        transaction.on_commit(
            lambda bot=bot, chat=member.user.telegram_id, text=text, markup=markup: (
                telegram_jobs.send_telegram_message.delay(bot, chat, text, serialize_markup(markup))
            )
        )
        sent += 1
    return sent


def upcoming(company, state, now: datetime) -> list[tuple[datetime | None, str]]:
    """The plans of the next run: one for each head or manager it is for (those with nothing
    to hear that morning get none)."""
    people = len(recipients(company, registry.config_of(AGENT, state)["who"]))
    at = next(iter(runner.next_runs(AGENT, state, company, now, 1)), None)
    label = ngettext("Plans for %(count)s person", "Plans for %(count)s people", people)
    return [(at, label % {"count": people})]


def _bot_of(member: Membership) -> str:
    """The bot the person uses: the staff bot, unless they only ever talk to the owner bot."""
    user = member.user
    if user.employee_bot_blocked_at is not None and user.owner_bot_started_at is not None:
        return BotName.OWNER
    return BotName.EMPLOYEE


AGENT = registry.register(
    Agent(
        key=KEY,
        order=30,
        name=gettext_lazy("Morning plan"),
        description=gettext_lazy(
            "Each workday morning, every head and manager gets their team's day: what is due, "
            "what is late, what waits for their check and who is off."
        ),
        icon="sunrise",
        needs_claude=False,
        default_enabled=True,
        fields=(
            Field("at", "time", gettext_lazy("Send at"), "08:30"),
            Field(
                "who",
                "choice",
                gettext_lazy("Who gets it"),
                "both",
                options=(
                    ("heads", gettext_lazy("Department heads")),
                    ("managers", gettext_lazy("Managers")),
                    ("both", gettext_lazy("Heads and managers")),
                ),
            ),
        ),
        schedule=_schedule,
        run=run,
        next_run=next_run,
        upcoming=upcoming,
        events={
            "plan_sent": EventTemplate(
                gettext_lazy(
                    "Morning plan for %(to)s: %(due_today)s due today, %(late)s late, "
                    "%(to_check)s to check"
                ),
                level="info",
            ),
        },
    )
)
