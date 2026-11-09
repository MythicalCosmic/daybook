"""The tutor ("Ustoz" / "Наставник"): the pharmacy's training coach (docs/PLAN-LEARNING.md §6).

It runs on the company's workdays at `at` (09:00) where the `learning` module is on, and does
what is due that day:

- **Nudges** (`nudge_learners`): a person who scored below the pass mark in the last days (a
  quiz or a check, not a manager's try) hears once, the next workday, which lesson helps with
  the topic they missed most ("Yesterday's test on <topic> was hard. This lesson helps: …",
  with the app's lesson). At most one every three days a person; never while on time off.
- **Suggestions** (`suggest`): on the report day it works out the suggestions of §4.10
  (`apps.learning.suggestions`): assign a course, a lesson is missing, late with mandatory
  training, could coach, say thanks. A closed check round works them out too.
- **The weekly report** (`weekly_report`): on `report_day` (or the first workday after it that
  week) each holder of `learning.manage` hears how the people they see are doing: mandatory
  training (finished, of, late, by name up to five), the week's tests (count, average), the
  weakest topic, the most points, who needs help (weak topics, late) and the open suggestions,
  with "Assign suggested" (accepts every open `assign` suggestion they see) and "Open" (the
  dashboard's tutor page). Owners and top managers hear it in the owner bot, the others in the
  staff bot (`apps.inbox.delivery.bots_for`).

Everything works without Claude (template wording). With Claude (`AI_MODEL_FAST`, effort low)
one call writes the report's two-sentence opening from the facts; a number in it that isn't one
of the facts sends the template instead. Claude gets names, counts and percentages, never a
phone number, an id or pay. The "Ask the tutor" chat (an Ask AI conversation with `agent`
"tutor", `apps.ai.chat`) adds `CHAT_SYSTEM` to the system prompt and keeps to the learning,
knowledge, recognition and people tools.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext, ngettext_lazy
from pydantic import BaseModel
from pydantic import Field as PydanticField

from apps.ai import availability, client, events, instructions
from apps.ai.agents import morning_plan, registry, runner
from apps.ai.agents.registry import Agent, EventTemplate, Field, Prompt
from apps.ai.tools.scrub import scrub_data
from apps.companies.models import Feature
from apps.inbox.models import Notification
from apps.inbox.services import NotificationAction
from apps.learning import conf as learning_conf
from apps.learning import daily, notify_quizzes, queries, quiz_queries, skills, suggestions
from apps.learning.models import AnswerLog, Attempt, TutorSuggestion
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import members_with_perm
from apps.recognition.models import PointsEntry
from apps.timeoff.queries import members_off

logger = logging.getLogger(__name__)

KEY = "tutor"
# Readers of one run, names per part of a report.
BATCH = 200
SHOWN = 5
OPENING_MAX = 300
MAX_TOKENS = 4000
NUDGE_DAYS = 3
WEEKDAYS = (
    ("0", gettext_lazy("Monday")),
    ("1", gettext_lazy("Tuesday")),
    ("2", gettext_lazy("Wednesday")),
    ("3", gettext_lazy("Thursday")),
    ("4", gettext_lazy("Friday")),
    ("5", gettext_lazy("Saturday")),
    ("6", gettext_lazy("Sunday")),
)
LANGUAGES = (
    "uz is Uzbek in Latin script with o‘ and g‘ (the polite siz form), ru is Russian (вы), "
    "en is English"
)

REPORT_SYSTEM = f"""You write the opening of a pharmacy company's weekly staff-training report \
for one of its managers in Uzbekistan: two short, warm and factual sentences from the facts \
given (mandatory training finished and late, the week's tests and their average, the weakest \
topic, who earned the most points, who needs help). Write in the language asked ({LANGUAGES}). \
Use only the names and numbers in the facts; never invent a name, a number or a date. No \
greeting, no list, no advice about medicines or doses."""

CHAT_SYSTEM = """You are also the company's tutor ("Ustoz"): its training of pharmacy staff \
(lessons, courses, quizzes, the question of the day, regular checks, the skill matrix, points \
and badges). Help the owner or manager see who is ahead and who needs help and why, which \
topics are weak, and what to do next: assign a course, add a lesson on a weak topic, run a \
check, ask a strong person to coach, thank someone. Use the learning, knowledge, recognition \
and people tools; every name and number comes from a tool. You can't change anything: say \
what to do in the dashboard. Never give advice about medicines or doses to patients."""

CHAT_DOMAINS = frozenset({"learning", "knowledge", "recognition", "people"})


def _schedule(config: dict) -> str:
    day = dict(WEEKDAYS).get(str(config["report_day"]), WEEKDAYS[0][1])
    return _("Workdays at %(time)s; the weekly report on %(day)s") % {
        "time": config["at"],
        "day": day,
    }


def _local(company, now: datetime) -> datetime:
    return timezone.localtime(now, ZoneInfo(company.timezone))


def week_key(company, now: datetime) -> str:
    year, week, _day = _local(company, now).isocalendar()
    return f"{year}-W{week:02d}"


def report_due(company, config: dict, now: datetime) -> bool:
    """On the report day, or the first run after it in the same week, once a week."""
    if not config["weekly_report"]:
        return False
    if _local(company, now).weekday() < int(config["report_day"]):
        return False
    return not events.already(company, f"tutor:report:{week_key(company, now)}")


def run(company, state, now: datetime) -> int:
    """What is due today, each part on its own: one failing never stops the others."""
    if not learning_conf.is_on(company):
        return 0
    config = registry.config_of(AGENT, state)
    parts = []
    if config["nudge_learners"]:
        parts.append(send_nudges)
    if config["suggest"] and report_due(company, config, now):
        parts.append(make_suggestions)
    if report_due(company, config, now):
        parts.append(send_reports)
    done = 0
    for part in parts:
        try:
            with transaction.atomic():
                done += part(company, config, now)
        except Exception:
            logger.exception("Tutor: %s failed for company %s", part.__name__, company.pk)
    return done


# Suggestions ------------------------------------------------------------------------------


def make_suggestions(company, config: dict, now: datetime) -> int:
    made, _resolved = suggestions.refresh(company, now)
    if made:
        events.log(
            company,
            KEY,
            "suggestions_made",
            params={"count": made},
            dedupe_key=f"tutor:suggest:{week_key(company, now)}",
        )
    return made


# Nudges -----------------------------------------------------------------------------------


def send_nudges(company, config: dict, now: datetime) -> int:
    local = _local(company, now)
    today = local.date()
    zone = ZoneInfo(company.timezone)
    start = datetime.combine(today - timedelta(days=NUDGE_DAYS), time.min, zone)
    end = datetime.combine(today, time.min, zone)
    away = members_off(company, today)
    hard = (
        Attempt.objects.filter(
            company=company,
            trial=False,
            passed=False,
            state__in=(Attempt.State.FINISHED, Attempt.State.EXPIRED),
            finished_at__gte=start,
            finished_at__lt=end,
            membership__status=Membership.Status.APPROVED,
        )
        .select_related("membership__user", "membership__company")
        .order_by("-finished_at")[:BATCH]
    )
    told: set[int] = set()
    sent = 0
    for attempt in hard:
        member = attempt.membership
        if member.pk in away or member.pk in told:
            continue
        if Notification.objects.filter(
            recipient=member,
            kind=notify_quizzes.NUDGE,
            created_at__gte=now - timedelta(days=NUDGE_DAYS),
        ).exists():
            continue
        missed = (
            AnswerLog.objects.filter(attempt=attempt, correct=False, topic__isnull=False)
            .values("topic_id", "topic__name")
            .annotate(count=Count("pk"))
            .order_by("-count", "topic_id")
            .first()
        )
        if missed is None:
            continue
        lessons = list(queries.lessons_for_topic(company, missed["topic_id"]))
        if not lessons:
            continue
        told.add(member.pk)
        with translation.override(member.user.language):
            sent += notify_quizzes.nudge(
                member, topic=missed["topic__name"], lesson=lessons[0], attempt_id=attempt.pk
            )
    if sent:
        events.log(
            company,
            KEY,
            "nudges_sent",
            params={"count": sent},
            dedupe_key=f"tutor:nudge:{today.isoformat()}",
        )
    return sent


# The weekly report ------------------------------------------------------------------------


def report_facts(company, reader: Membership, now: datetime, threshold: int) -> dict | None:
    """What `reader` hears about the people they see, as plain data (names, counts,
    percentages): None when they see nobody else."""
    branch_ids = scope.branch_ids(reader)
    people = list(
        quiz_queries.people(company, branch_ids=branch_ids)
        .filter(status=Membership.Status.APPROVED)
        .exclude(pk=reader.pk)
        .select_related("user")
    )
    if not people:
        return None
    ids = [member.pk for member in people]
    names = {member.pk: str(member) for member in people}
    since = now - timedelta(days=7)
    compliance = queries.compliance(company, branch_ids=branch_ids, now=now)
    late_names = []
    for late in compliance.late:
        if late.membership_id in names and late.name not in late_names:
            late_names.append(late.name)
    tests = list(
        Attempt.objects.filter(
            company=company,
            trial=False,
            membership_id__in=ids,
            state__in=(Attempt.State.FINISHED, Attempt.State.EXPIRED),
            finished_at__gte=since,
        ).values_list("percent", flat=True)
    )
    weakest = skills.weakest_topics(company, branch_ids=branch_ids, limit=1)
    top = (
        PointsEntry.objects.filter(company=company, membership_id__in=ids, at__gte=since)
        .values("membership_id")
        .annotate(total=Sum("points"))
        .filter(total__gt=0)
        .order_by("-total", "membership_id")[:3]
    )
    found_mastery = skills.mastery(company, member_ids=ids)
    weak_by_person: dict[int, list[str]] = {}
    topic_names = {}
    for (member_id, topic_id), value in found_mastery.items():
        if value.score is not None and value.score < threshold:
            weak_by_person.setdefault(member_id, []).append(topic_id)
            topic_names[topic_id] = None
    if topic_names:
        from apps.knowledge.models import Topic

        for topic in Topic.objects.filter(pk__in=list(topic_names)):
            topic_names[topic.pk] = topic.name
    late_ids = {late.membership_id for late in compliance.late}
    needing = sorted(
        set(weak_by_person) | (late_ids & set(ids)),
        key=lambda member_id: (-len(weak_by_person.get(member_id, [])), names[member_id]),
    )
    open_rows = suggestions.visible(reader)
    return {
        "mandatory": {
            "people": compliance.people,
            "completed": compliance.completed,
            "late": compliance.overdue_people,
            "late_names": late_names[:SHOWN],
        },
        "tests": {
            "count": len(tests),
            "average": round(sum(value or 0 for value in tests) / len(tests)) if tests else 0,
        },
        "weakest_topic": {
            "name": weakest[0]["topic"].name,
            "average": weakest[0]["average"],
            "weak": weakest[0]["weak"],
        }
        if weakest
        else None,
        "top": [{"name": names[row["membership_id"]], "points": row["total"]} for row in top],
        "help": [
            {
                "name": names[member_id],
                "topics": [topic_names[topic] for topic in weak_by_person.get(member_id, [])][:2],
                "late": member_id in late_ids,
            }
            for member_id in needing[:SHOWN]
        ],
        "suggestions": {
            "open": open_rows.count(),
            "assign": open_rows.filter(kind=TutorSuggestion.Kind.ASSIGN).count(),
        },
    }


def send_reports(company, config: dict, now: datetime) -> int:
    week = week_key(company, now)
    readers = (
        members_with_perm(company, Perm.LEARNING_MANAGE)
        .select_related("user", "role", "company")
        .order_by("pk")[:BATCH]
    )
    sent = 0
    for reader in readers:
        with translation.override(reader.user.language):
            facts = report_facts(company, reader, now, int(config["weak_threshold"]))
            if facts is None:
                continue
            opening = _opening(reader, facts)
            actions = (
                [NotificationAction("assign", gettext_lazy("Assign suggested"), "primary")]
                if facts["suggestions"]["assign"]
                else []
            )
            sent += notify_quizzes.tutor_report(
                reader, facts, opening=opening, week=week, actions=actions
            )
    events.log(
        company,
        KEY,
        "report_sent",
        params={"count": sent},
        dedupe_key=f"tutor:report:{week}",
        level="success" if sent else None,
    )
    return sent


# Claude -----------------------------------------------------------------------------------


class Opening(BaseModel):
    text: str = PydanticField(description="Two short sentences in the language asked.")


def _opening(member: Membership, facts: dict) -> str:
    """Claude's opening over `facts`, in `member`'s language; "" without Claude, on any
    failure, or when a number in it isn't one of the facts."""
    company = member.company
    if not availability.status(company).available or availability.fake():
        return ""
    data = scrub_data(facts)
    try:
        result, _call = client.structured(
            KEY,
            company=company,
            membership=member,
            model=settings.AI_MODEL_FAST,
            schema=Opening,
            effort="low",
            max_tokens=MAX_TOKENS,
            system=instructions.system_for(company, KEY, REPORT_SYSTEM),
            user=[
                {
                    "type": "text",
                    "text": f"<language>{member.user.language}</language>\n"
                    f"<facts>\n{json.dumps(data, ensure_ascii=False, sort_keys=True)}\n</facts>",
                }
            ],
        )
    except client.ClaudeError:
        return ""
    text = " ".join(result.text.split())[:OPENING_MAX]
    return text if numbers_ok(text, data) else ""


def numbers_ok(text: str, facts) -> bool:
    """Every number written in `text` is a number of `facts`."""
    known = _numbers(facts)
    return all(int(found) in known for found in re.findall(r"\d+", text))


def _numbers(value) -> set[int]:
    if isinstance(value, bool):
        return set()
    if isinstance(value, int):
        return {abs(value)}
    if isinstance(value, float):
        return {abs(int(value)), abs(round(value))}
    if isinstance(value, str):
        return {int(found) for found in re.findall(r"\d+", value)}
    if isinstance(value, dict):
        value = list(value.values())
    if isinstance(value, list | tuple):
        return set().union(*(_numbers(item) for item in value))
    return set()


# Its page ---------------------------------------------------------------------------------


LOOK_AHEAD_RUNS = 14


def next_report_at(company, state, now: datetime) -> datetime | None:
    """The run that sends the next weekly report (None while it is off)."""
    config = registry.config_of(AGENT, state)
    if not config["weekly_report"]:
        return None
    for moment in runner.next_runs(AGENT, state, company, now, LOOK_AHEAD_RUNS):
        local = _local(company, moment)
        if local.weekday() >= int(config["report_day"]) and not events.already(
            company, f"tutor:report:{week_key(company, moment)}"
        ):
            return moment
    return None


def upcoming(company, state, now: datetime) -> list[tuple[datetime | None, str]]:
    """When the next weekly report goes, today's questions of the day, the open suggestions.
    Counts only."""
    found = []
    if moment := next_report_at(company, state, now):
        found.append((moment, _("Weekly training report")))
    if learning_conf.get_settings(company).daily_question:
        day = daily.today(company, now)
        count = daily.audience(company, day).count()
        at = datetime.combine(
            day, learning_conf.get_settings(company).daily_at, ZoneInfo(company.timezone)
        )
        found.append(
            (
                at if at > now else None,
                ngettext(
                    "Question of the day: %(count)s person",
                    "Question of the day: %(count)s people",
                    count,
                )
                % {"count": count},
            )
        )
    open_count = TutorSuggestion.objects.filter(company=company, state="open").count()
    found.append((None, _("Open suggestions: %(count)s") % {"count": open_count}))
    return found


AGENT = registry.register(
    Agent(
        key=KEY,
        order=60,
        features=(Feature.LEARNING,),
        name=gettext_lazy("Tutor"),
        description=gettext_lazy(
            "Coaches the pharmacy's training: each week managers hear who is ahead and who "
            "needs help and why, with suggestions to act on in one tap (assign a course, a "
            "lesson that is missing, someone who could coach, a thank-you); after a hard test "
            "the person hears which lesson helps. It also writes questions from a page or a "
            "lesson and answers questions about the training."
        ),
        icon="graduation-cap",
        needs_claude=False,
        prompts=(
            Prompt(gettext_lazy("The weekly training report"), REPORT_SYSTEM),
            Prompt(gettext_lazy("Ask the tutor"), CHAT_SYSTEM),
        ),
        default_enabled=True,
        fields=(
            Field("weekly_report", "bool", gettext_lazy("Weekly report"), True),
            Field(
                "report_day",
                "choice",
                gettext_lazy("Report day"),
                "0",
                options=WEEKDAYS,
            ),
            Field("at", "time", gettext_lazy("Send at"), "09:00"),
            Field(
                "nudge_learners",
                "bool",
                gettext_lazy("Nudge after a hard test"),
                True,
                help=gettext_lazy(
                    "The next workday a person who failed a test hears which lesson helps."
                ),
            ),
            Field(
                "suggest",
                "bool",
                gettext_lazy("Make suggestions"),
                True,
                help=gettext_lazy(
                    "Who to assign a course, what lesson is missing, who could coach."
                ),
            ),
            Field(
                "weak_threshold",
                "int",
                gettext_lazy("Weak below"),
                60,
                help=gettext_lazy("A topic counts as weak below this mastery score."),
                min=30,
                max=90,
                unit="%",
            ),
        ),
        schedule=_schedule,
        run_label=gettext_lazy("The tutor's morning"),
        run=run,
        next_run=morning_plan.next_run,
        upcoming=upcoming,
        usage_features=(KEY, "learning_drafts"),
        events={
            "report_sent": EventTemplate(
                ngettext_lazy(
                    "Sent the weekly training report to %(count)s person",
                    "Sent the weekly training report to %(count)s people",
                    "count",
                )
            ),
            "suggestions_made": EventTemplate(
                ngettext_lazy("Made %(count)s suggestion", "Made %(count)s suggestions", "count"),
                level="success",
            ),
            "nudges_sent": EventTemplate(
                ngettext_lazy(
                    "Pointed %(count)s person to a lesson after a hard test",
                    "Pointed %(count)s people to a lesson after a hard test",
                    "count",
                )
            ),
            "questions_written": EventTemplate(
                ngettext_lazy(
                    "Wrote %(count)s question for the bank",
                    "Wrote %(count)s questions for the bank",
                    "count",
                ),
                level="success",
            ),
        },
    )
)
