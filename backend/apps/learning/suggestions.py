"""The tutor's suggestions (package Q2; docs/PLAN-LEARNING.md §4.10).

Worked out weekly (the tutor's run) and after each closed check round, kept as
`TutorSuggestion` (one open per person, kind, topic and course), worded when read:

- `assign`: weak in a rated topic that a published course covers (or a course holding a
  published lesson of the topic), not finished nor open; accepting assigns the course (Q1's
  `assign`, source "tutor").
- `lesson_needed`: two or more people weak in a topic nothing published covers (company-wide);
  the dashboard then opens a new lesson.
- `overdue`: late with mandatory training for `escalate_after_days` or more; the dashboard
  opens their page.
- `mentor`: strong (90 or more over 10 answers or more) where others are weak: could coach them.
- `praise`: the week's top three learners with 30 points or more: say thanks.

A suggestion resolves itself (`done`) when its reason goes away: the course finished or given,
the topic no longer weak, no longer late, the week over. Accepting and dismissing are audited.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.audit import services as audit
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.learning import conf, queries, skills
from apps.learning.audit_actions import QuizAction
from apps.learning.models import LIVE, Assignment, Course, TutorSuggestion
from apps.learning.services import ensure_manager
from apps.members import scope
from apps.members.models import Membership
from apps.recognition.models import PointsEntry

logger = logging.getLogger(__name__)

PULSE_KEY = "learning.suggestions"
Kind = TutorSuggestion.Kind
State = TutorSuggestion.State
OPEN = State.OPEN
# Mentors: this strong over this many answers.
MENTOR_SCORE = 90
MENTOR_ANSWERS = 10
# Praise: the week's top learners, with at least this many points.
PRAISE_TOP = 3
PRAISE_POINTS = 30
# A topic nothing covers needs this many weak people for a "lesson needed".
LESSON_NEEDED_PEOPLE = 2
OPEN_COURSE = (Assignment.State.ASSIGNED, Assignment.State.IN_PROGRESS)


def week_start(company, now: datetime) -> datetime:
    """Monday 00:00 of the company's week."""
    zone = ZoneInfo(company.timezone)
    local = timezone.localtime(now, zone)
    return datetime.combine(local.date() - timedelta(days=local.weekday()), time.min, zone)


def weak_threshold(company) -> int:
    """The tutor's `weak_threshold` (the dashboard's setting), else the matrix's band."""
    from apps.ai.agents import registry

    agent = registry.get("tutor")
    if agent is None:
        return skills.WEAK
    from apps.ai.models import AgentState

    state = AgentState.objects.filter(company=company, key="tutor").first()
    return int(registry.config_of(agent, state).get("weak_threshold", skills.WEAK))


# Working them out --------------------------------------------------------------------------


def _people(company) -> dict[int, Membership]:
    return {
        member.pk: member
        for member in Membership.objects.for_company(company)
        .filter(status=Membership.Status.APPROVED)
        .select_related("user")
    }


def _covering_course(company, topic_id: int) -> Course | None:
    """The first published course about the topic: one of its own steps, or holding one of the
    topic's published lessons."""
    courses = list(queries.courses_for_topic(company, topic_id))
    if courses:
        return courses[0]
    for lesson in queries.lessons_for_topic(company, topic_id):
        course = Course.objects.filter(company=company, steps__lesson=lesson).filter(LIVE).first()
        if course is not None:
            return course
    return None


def _taken(member_id: int, course: Course) -> bool:
    """Whether the person has the course open or finished (its current cycle)."""
    return Assignment.objects.filter(
        membership_id=member_id,
        course=course,
        state__in=(*OPEN_COURSE, Assignment.State.COMPLETED),
    ).exists()


def _want(found: dict, key: tuple, kind: str, **fields) -> None:
    found[key] = {"kind": kind, **fields}


def wanted(company, now: datetime) -> dict[tuple, dict]:
    """Every suggestion the facts call for now, by (member, kind, topic, course)."""
    threshold = weak_threshold(company)
    people = _people(company)
    found_mastery = skills.mastery(company, member_ids=list(people))
    weak: dict[int, list[tuple[int, skills.Mastery]]] = {}
    strong: dict[int, list[tuple[int, skills.Mastery]]] = {}
    for (member_id, topic_id), value in found_mastery.items():
        if value.score is None:
            continue
        if value.score < threshold:
            weak.setdefault(topic_id, []).append((member_id, value))
        if value.score >= MENTOR_SCORE and value.answers >= MENTOR_ANSWERS:
            strong.setdefault(topic_id, []).append((member_id, value))
    found: dict[tuple, dict] = {}
    for topic_id, rows in weak.items():
        course = _covering_course(company, topic_id)
        if course is None:
            if len(rows) >= LESSON_NEEDED_PEOPLE:
                _want(
                    found,
                    (None, Kind.LESSON_NEEDED, topic_id, None),
                    Kind.LESSON_NEEDED,
                    params={"weak": len(rows)},
                )
            continue
        for member_id, value in rows:
            if _taken(member_id, course):
                continue
            _want(
                found,
                (member_id, Kind.ASSIGN, topic_id, course.pk),
                Kind.ASSIGN,
                score=value.score,
                params={"score": value.score, "answers": value.answers},
            )
    for topic_id, rows in strong.items():
        others = [member_id for member_id, _value in weak.get(topic_id, [])]
        for member_id, value in rows:
            coached = [other for other in others if other != member_id]
            if coached:
                _want(
                    found,
                    (member_id, Kind.MENTOR, topic_id, None),
                    Kind.MENTOR,
                    score=value.score,
                    params={"score": value.score, "weak": len(coached)},
                )
    learning = conf.get_settings(company)
    late_days = max(learning.escalate_after_days, 1)
    for late in queries.compliance(company, branch_ids=None, now=now).late:
        if late.days_late >= late_days and late.membership_id in people:
            _want(
                found,
                (late.membership_id, Kind.OVERDUE, None, late.course_id),
                Kind.OVERDUE,
                params={"days": late.days_late},
            )
    week = (
        PointsEntry.objects.filter(
            company=company, at__gte=week_start(company, now), membership_id__in=list(people)
        )
        .values("membership_id")
        .annotate(total=Sum("points"))
        .order_by("-total", "membership_id")[:PRAISE_TOP]
    )
    for row in week:
        if row["total"] >= PRAISE_POINTS:
            _want(
                found,
                (row["membership_id"], Kind.PRAISE, None, None),
                Kind.PRAISE,
                params={"points": row["total"]},
            )
    return found


def refresh(company, now: datetime | None = None) -> tuple[int, int]:
    """Make the suggestions the facts call for and resolve the open ones whose reason went;
    (made, resolved)."""
    now = now or timezone.now()
    found = wanted(company, now)
    made = resolved = 0
    with transaction.atomic():
        current = {
            (row.membership_id, row.kind, row.topic_id, row.course_id): row
            for row in TutorSuggestion.objects.select_for_update().filter(
                company=company, state=OPEN
            )
        }
        for key, row in current.items():
            if key not in found:
                row.state = State.DONE
                row.decided_at = now
                row.save(update_fields=["state", "decided_at", "updated_at"])
                resolved += 1
            else:
                fresh = found[key]
                row.params = fresh.get("params", {})
                row.score = fresh.get("score")
                row.save(update_fields=["params", "score", "updated_at"])
        decided = set(
            TutorSuggestion.objects.filter(
                company=company,
                state__in=(State.ACCEPTED, State.DISMISSED),
                decided_at__gte=week_start(company, now),
            ).values_list("membership_id", "kind", "topic_id", "course_id")
        )
        for key, fresh in found.items():
            if key in current or key in decided:
                continue  # open already, or a manager decided it this week
            member_id, kind, topic_id, course_id = key
            try:
                with transaction.atomic():
                    TutorSuggestion.objects.create(
                        company=company,
                        membership_id=member_id,
                        kind=kind,
                        topic_id=topic_id,
                        course_id=course_id,
                        score=fresh.get("score"),
                        params=fresh.get("params", {}),
                    )
                made += 1
            except IntegrityError:
                continue
    if made or resolved:
        company_id = company.pk
        transaction.on_commit(lambda: pulse.bump(company_id, PULSE_KEY))
    return made, resolved


def tutor_on(company) -> bool:
    """The tutor works out suggestions only where it runs: AI on, the agent on, `suggest` on."""
    from apps.ai import agents
    from apps.ai import conf as ai_conf

    if not conf.is_on(company) or not ai_conf.ai_on(company):
        return False
    agent = agents.get("tutor")
    if agent is None:
        return False
    state = agents.state_of(company, "tutor")
    return state.enabled and bool(agents.config_of(agent, state).get("suggest", True))


def after_check_round(round_) -> int:
    """After a closed check round: the suggestions, when the tutor is on."""
    company = round_.company
    if not tutor_on(company):
        return 0
    made, _resolved = refresh(company)
    return made


# Reading ----------------------------------------------------------------------------------


def visible(viewer: Membership, *, state: str | None = OPEN):
    """The suggestions `viewer` may see: about the people they see; company-wide ones only
    with every branch in sight."""
    rows = TutorSuggestion.objects.filter(company_id=viewer.company_id).select_related(
        "membership__user", "topic", "course", "lesson"
    )
    if state:
        rows = rows.filter(state=state)
    branch_ids = scope.branch_ids(viewer)
    if branch_ids is not None:
        rows = rows.filter(membership__branches__in=branch_ids).distinct()
    return rows.order_by("-created_at", "-pk")


def text(row: TutorSuggestion) -> str:
    """The suggestion in the reader's words (the active language)."""
    name = str(row.membership) if row.membership_id else ""
    topic = row.topic.name if row.topic_id else ""
    course = row.course.title if row.course_id else ""
    params = row.params or {}
    if row.kind == Kind.ASSIGN:
        return _(
            "%(name)s is weak in this topic: %(topic)s (%(score)s %%). Assign «%(course)s»."
        ) % {
            "name": name,
            "topic": topic,
            "score": params.get("score", row.score or 0),
            "course": course,
        }
    if row.kind == Kind.LESSON_NEEDED:
        count = params.get("weak", 0)
        return ngettext(
            "%(count)s person is weak in a topic nothing teaches yet: %(topic)s. Add a lesson.",
            "%(count)s people are weak in a topic nothing teaches yet: %(topic)s. Add a lesson.",
            count,
        ) % {"count": count, "topic": topic}
    if row.kind == Kind.OVERDUE:
        days = params.get("days", 0)
        return ngettext(
            "%(name)s is %(days)s day late with «%(course)s».",
            "%(name)s is %(days)s days late with «%(course)s».",
            days,
        ) % {"name": name, "days": days, "course": course}
    if row.kind == Kind.MENTOR:
        count = params.get("weak", 0)
        return ngettext(
            "%(name)s knows %(topic)s well (%(score)s %%) and could coach %(count)s "
            "colleague weak in it.",
            "%(name)s knows %(topic)s well (%(score)s %%) and could coach %(count)s "
            "colleagues weak in it.",
            count,
        ) % {"name": name, "topic": topic, "score": params.get("score", 0), "count": count}
    if row.kind == Kind.PRAISE:
        return _("%(name)s earned %(points)s points this week: say thanks.") % {
            "name": name,
            "points": params.get("points", 0),
        }
    return row.get_kind_display()


# Deciding ---------------------------------------------------------------------------------


def _decide(row: TutorSuggestion, state: str, action: str, by: Membership | None) -> None:
    row.state = state
    row.decided_by = by
    row.decided_at = timezone.now()
    row.save(update_fields=["state", "decided_by", "decided_at", "updated_at"])
    audit.record(
        action,
        company_id=row.company_id,
        actor=by.user if by is not None else None,
        target=row,
        kind=row.kind,
        member=row.membership_id,
    )
    company_id = row.company_id
    transaction.on_commit(lambda: pulse.bump(company_id, PULSE_KEY))


def resolve_removed(sender, instance, **kwargs) -> None:
    """`pre_delete` of a topic or a course: its open suggestions are resolved first (their
    reason went), so emptying their link never makes two open ones alike: one open suggestion
    per person, kind, topic and course, and the constraint counts two empty links as equal (a
    reset of the demo deleted the topics and met it)."""
    field = "course" if sender is Course else "topic"
    now = timezone.now()
    TutorSuggestion.objects.filter(**{field: instance}, state=OPEN).update(
        state=State.DONE, decided_at=now, updated_at=now
    )


@transaction.atomic
def accept(row: TutorSuggestion, *, by: Membership | None) -> TutorSuggestion:
    """Take the suggestion: an `assign` one assigns its course (Q1's `assign`, source tutor);
    the others are marked taken (the dashboard opens what they point to)."""
    ensure_manager(by)
    row = (
        TutorSuggestion.objects.select_for_update(of=("self",))
        .select_related("course", "membership")
        .get(pk=row.pk)
    )
    if row.state != OPEN:
        raise DomainError(_("This suggestion was already decided."))
    if row.kind == Kind.ASSIGN:
        if row.course_id is None or row.membership_id is None:
            raise DomainError(_("This suggestion has nothing to assign."))
        from apps.learning import courses

        courses.assign(row.course, [row.membership], by=by, source=Assignment.Source.TUTOR)
    _decide(row, State.ACCEPTED, QuizAction.SUGGESTION_ACCEPTED, by)
    return row


@transaction.atomic
def dismiss(row: TutorSuggestion, *, by: Membership | None) -> TutorSuggestion:
    ensure_manager(by)
    row = TutorSuggestion.objects.select_for_update().get(pk=row.pk)
    if row.state != OPEN:
        raise DomainError(_("This suggestion was already decided."))
    _decide(row, State.DISMISSED, QuizAction.SUGGESTION_DISMISSED, by)
    return row


def accept_all_assign(viewer: Membership) -> int:
    """The report's "Assign suggested": every open `assign` suggestion `viewer` sees."""
    done = 0
    for row in visible(viewer).filter(kind=Kind.ASSIGN):
        try:
            accept(row, by=viewer)
            done += 1
        except DomainError:
            continue
    return done


def assign_suggested(notification, by: Membership, reason: str) -> str:
    """The weekly report's "Assign suggested" button: every open `assign` suggestion `by`
    sees (registered for the inbox kind `learning.tutor_report`)."""
    count = accept_all_assign(by)
    if not count:
        return _("Nothing is left to assign.")
    return ngettext("Assigned %(count)s course.", "Assigned %(count)s courses.", count) % {
        "count": count
    }
