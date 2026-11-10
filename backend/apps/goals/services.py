"""Business logic of business goals: every write, shared by the API and Celery.

Each service takes `by: Membership` (`None` means the system), audits its changes with
`apps.audit.services.record`, and keeps the goal's last evaluation (`refresh`). The weekly beat
(`weekly`) adds a point to every live goal's series, closes the goals whose period ended
(achieved or missed) and tells the owners when a goal turns for the worse (at risk, then off
track), once per turn.
"""

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.core.exceptions import DomainError
from apps.goals import bot_messages, progress
from apps.goals.audit_actions import GoalsAction
from apps.goals.metrics import METRICS
from apps.goals.models import Goal, GoalPoint
from apps.members.models import Membership
from apps.members.permissions import Perm

logger = logging.getLogger(__name__)

NOTIFY_KIND = "goals.at_risk"
MAX_DAYS = 2 * 366
WORSE = (Goal.State.AT_RISK, Goal.State.OFF_TRACK)
EDITABLE = ("title", "target", "starts_on", "ends_on", "owner", "note")


def local_today(company, now: datetime | None = None) -> date:
    return timezone.localtime(now or timezone.now(), ZoneInfo(company.timezone)).date()


# Writes ----------------------------------------------------------------------------------------


@transaction.atomic
def create_goal(
    company,
    *,
    by: Membership,
    title: str,
    metric: str,
    target,
    starts_on: date,
    ends_on: date,
    branch=None,
    owner: Membership | None = None,
    note: str = "",
) -> Goal:
    _need_actor(company, by)
    spec = METRICS.get(metric)
    if spec is None:
        raise DomainError(_("Pick what the goal measures."))
    if not spec.available(company):
        raise DomainError(_("Switch on the module this goal measures first."))
    if branch is not None and not spec.branchable:
        raise DomainError(_("This goal is for the whole company."))
    _same_company(company, branch, owner)
    goal = Goal(
        company=company,
        title=_title(title),
        metric=metric,
        target=_target(spec, target),
        starts_on=starts_on,
        ends_on=ends_on,
        branch=branch,
        owner=owner,
        note=(note or "").strip()[:500],
        created_by=by.user,
    )
    _check_period(goal)
    goal.save()
    refresh(goal)
    _audit(
        GoalsAction.GOAL_CREATED,
        goal,
        by,
        metric=metric,
        target_value=str(goal.target),
        period=[starts_on.isoformat(), ends_on.isoformat()],
        branch=goal.branch_id,
    )
    return goal


@transaction.atomic
def update_goal(goal: Goal, *, by: Membership, **fields) -> Goal:
    """Change the title, target, period, owner or note. What it measures and where stay: a new
    measure is a new goal."""
    goal = Goal.objects.select_for_update().select_related("company").get(pk=goal.pk)
    company = goal.company
    _need_actor(company, by)
    unknown = set(fields) - set(EDITABLE)
    if unknown:
        raise ValueError(f"Unknown fields {sorted(unknown)}.")
    if goal.status == Goal.Status.ARCHIVED:
        raise DomainError(_("Bring the goal back before changing it."))
    spec = METRICS[goal.metric]
    before = _snapshot(goal)
    if "title" in fields:
        goal.title = _title(fields["title"])
    if "target" in fields:
        goal.target = _target(spec, fields["target"])
    if "starts_on" in fields:
        goal.starts_on = fields["starts_on"]
    if "ends_on" in fields:
        goal.ends_on = fields["ends_on"]
    if "owner" in fields:
        _same_company(company, fields["owner"])
        goal.owner = fields["owner"]
    if "note" in fields:
        goal.note = (fields["note"] or "").strip()[:500]
    _check_period(goal)
    if before["starts_on"] != goal.starts_on.isoformat():
        goal.baseline = None  # measured again from the new first day
        goal.points.all().delete()
    if goal.status in (Goal.Status.ACHIEVED, Goal.Status.MISSED):
        goal.status = Goal.Status.ACTIVE  # judged again on the new terms
    goal.save()
    refresh(goal)
    changes = {
        key: [before[key], value] for key, value in _snapshot(goal).items() if before[key] != value
    }
    if changes:
        _audit(GoalsAction.GOAL_UPDATED, goal, by, changes=changes)
    return goal


@transaction.atomic
def archive_goal(goal: Goal, *, by: Membership) -> Goal:
    goal = Goal.objects.select_for_update().select_related("company").get(pk=goal.pk)
    _need_actor(goal.company, by)
    if goal.status != Goal.Status.ARCHIVED:
        goal.status = Goal.Status.ARCHIVED
        goal.save(update_fields=["status", "updated_at"])
        _audit(GoalsAction.GOAL_ARCHIVED, goal, by)
    return goal


@transaction.atomic
def restore_goal(goal: Goal, *, by: Membership) -> Goal:
    goal = Goal.objects.select_for_update().select_related("company").get(pk=goal.pk)
    _need_actor(goal.company, by)
    if goal.status == Goal.Status.ARCHIVED:
        goal.status = Goal.Status.ACTIVE
        goal.save(update_fields=["status", "updated_at"])
        refresh(goal)
        _audit(GoalsAction.GOAL_RESTORED, goal, by)
    return goal


@transaction.atomic
def delete_goal(goal: Goal, *, by: Membership) -> None:
    _need_actor(goal.company, by)
    _audit(GoalsAction.GOAL_DELETED, goal, by, metric=goal.metric)
    goal.delete()


# Evaluating ------------------------------------------------------------------------------------


def refresh(goal: Goal, today: date | None = None) -> progress.Evaluation:
    """Evaluate the goal as of `today` and keep the result on it (and its day-one baseline)."""
    today = today or local_today(goal.company)
    if (
        goal.baseline is None
        and METRICS[goal.metric].kind == "level"
        and goal.starts_on <= today
        and METRICS[goal.metric].available(goal.company)
    ):
        goal.baseline = progress.baseline_of(goal)
    result = progress.evaluate(goal, today)
    goal.value = result.value
    goal.forecast = result.forecast
    goal.progress = result.progress
    goal.state = result.state
    goal.computed_at = timezone.now()
    fields = ["baseline", "value", "forecast", "progress", "state", "computed_at"]
    if goal.status == Goal.Status.ACTIVE and result.state in (
        Goal.State.ACHIEVED,
        Goal.State.MISSED,
    ):
        goal.status = result.state  # the period is over
        fields.append("status")
    if goal.state not in WORSE and goal.notified_state:
        goal.notified_state = ""  # back on track: a new turn for the worse is told again
        fields.append("notified_state")
    Goal.objects.filter(pk=goal.pk).update(**{field: getattr(goal, field) for field in fields})
    return result


def record_point(goal: Goal, today: date) -> GoalPoint:
    """Evaluate and add today's point to the series (one per day)."""
    result = refresh(goal, today)
    point, _created = GoalPoint.objects.update_or_create(
        goal=goal,
        on=today,
        defaults={"value": result.value, "forecast": result.forecast, "state": result.state},
    )
    return point


def weekly(now: datetime | None = None) -> int:
    """The weekly beat: a point for every live goal, owners told of each turn for the worse.
    Returns how many goals it looked at."""
    now = now or timezone.now()
    count = 0
    goals = (
        Goal.objects.filter(status=Goal.Status.ACTIVE, company__is_active=True)
        .select_related("company", "owner__user", "branch")
        .order_by("company_id", "pk")
    )
    for goal in goals:
        try:
            with transaction.atomic():
                today = local_today(goal.company, now)
                if today < goal.starts_on:
                    continue
                point = record_point(goal, today)
                count += 1
                if point.state in WORSE and point.state != goal.notified_state:
                    if _worse(goal.notified_state, point.state):
                        _notify(goal, point)
                    Goal.objects.filter(pk=goal.pk).update(notified_state=point.state)
        except Exception:  # one goal's trouble never stops the others
            logger.exception("Weekly goal check failed for goal %s", goal.pk)
    return count


RANK = {"": 0, Goal.State.AT_RISK: 1, Goal.State.OFF_TRACK: 2}


def _worse(told: str, now: str) -> bool:
    """`now` is worse than what the owners were last told (nothing, at risk, off track)."""
    return RANK.get(now, 0) > RANK.get(told, 0)


def recipients(goal: Goal) -> list[Membership]:
    """The company's owners and the goal's owner, if they may still see it."""
    from apps.goals import queries

    people = list(
        Membership.objects.filter(
            company=goal.company, status=Membership.Status.APPROVED, role__is_owner=True
        ).select_related("user", "role", "company")
    )
    if goal.owner_id and goal.owner.status == Membership.Status.APPROVED:
        people.append(goal.owner)
    seen, found = set(), []
    for person in people:
        if person.pk in seen or not queries.can_see(person, goal):
            continue
        seen.add(person.pk)
        found.append(person)
    return found


def _notify(goal: Goal, point: GoalPoint) -> None:
    from apps.inbox.services import notify

    people = recipients(goal)
    if not people:
        return
    spec = METRICS[goal.metric]
    currency = goal.company.base_currency

    def title(person: Membership) -> str:
        with translation.override(person.user.language):
            return bot_messages.worse_title(point.state, goal.title)

    def body(person: Membership) -> str:
        language = (person.user.language or "uz")[:2]
        with translation.override(language):
            return bot_messages.worse_body(
                spec,
                value=point.value,
                forecast=point.forecast,
                target=goal.target,
                ends_on=goal.ends_on,
                currency=currency,
                language=language,
            )

    notify(
        people,
        NOTIFY_KIND,
        title=title,
        body=body,
        url=f"/c/{goal.company_id}/goals?goal={goal.pk}",
        target=goal,
        severity="critical" if point.state == Goal.State.OFF_TRACK else "warning",
        dedupe_key=f"goals:{goal.pk}:{point.state}:{point.on.isoformat()}",
    )


# Helpers -----------------------------------------------------------------------------------------


def _need_actor(company, by: Membership | None) -> None:
    if not isinstance(by, Membership):
        raise ValueError("A goal is changed by a person: pass by=<Membership>.")
    if by.company_id != company.pk:
        raise DomainError(_("Everything in a goal must belong to the same company."))


def _same_company(company, *objects) -> None:
    for obj in objects:
        if obj is not None and obj.company_id != company.pk:
            raise DomainError(_("Everything in a goal must belong to the same company."))


def _title(value) -> str:
    title = (value or "").strip()[:200]
    if not title:
        raise DomainError(_("Give the goal a name."))
    return title


def _target(spec, value) -> Decimal:
    try:
        target = Decimal(str(value)).quantize(Decimal("0.01"))
    except InvalidOperation, TypeError, ValueError:
        raise DomainError(_("Enter the target as a number.")) from None
    if not target.is_finite() or target < 0 or target > Decimal("9999999999999999.99"):
        raise DomainError(_("Enter the target as a number."))
    if spec.unit == "percent" and target > 100:
        raise DomainError(_("A percent target is at most 100."))
    if spec.better == "up" and target <= 0:
        raise DomainError(_("The target must be more than zero."))
    return target


def _check_period(goal: Goal) -> None:
    if goal.ends_on < goal.starts_on:
        raise DomainError(_("The goal ends before it starts."))
    if (goal.ends_on - goal.starts_on).days > MAX_DAYS:
        raise DomainError(_("A goal runs for two years at most."))


def _snapshot(goal: Goal) -> dict:
    return {
        "title": goal.title,
        "target": str(goal.target),
        "starts_on": goal.starts_on.isoformat(),
        "ends_on": goal.ends_on.isoformat(),
        "owner": goal.owner_id,
        "note": goal.note,
    }


def _audit(action, goal: Goal, by: Membership | None, **details) -> None:
    """Only people who see the goal's numbers see its history (a profit target needs
    finance.view)."""
    audit.record(
        action,
        company_id=goal.company_id,
        actor=by.user if by is not None else None,
        target=goal,
        required_perm=METRICS[goal.metric].perm or Perm.REPORTS_VIEW,
        title=goal.title,
        **details,
    )


__all__ = [
    "archive_goal",
    "create_goal",
    "delete_goal",
    "record_point",
    "refresh",
    "restore_goal",
    "update_goal",
    "weekly",
]
