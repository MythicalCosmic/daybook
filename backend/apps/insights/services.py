"""Business logic of insights: every write, shared by the API, the bots and Celery.

Each service takes `by: Membership` (`None` means the system), checks that `by` may see the
insight, audits with `apps.audit.services.record`, closes the insight's Telegram buttons
(`inbox.services.settle`) and bumps the `insights.open` pulse key after commit.
"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.audit import services as audit
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.insights import access, conf, texts
from apps.insights.audit_actions import InsightAction
from apps.insights.models import Insight, InsightSettings
from apps.members.models import Membership

PULSE = "insights.open"
SEEN = gettext_lazy("Seen")
DISMISSED = gettext_lazy("Dismissed")
RESOLVED = gettext_lazy("Resolved")
TASK_MADE = gettext_lazy("Made a task")
DUE_AT = time(18, 0)  # a task made for a day is due at the end of its working day


def _bump(company_id: int) -> None:
    transaction.on_commit(lambda: pulse.bump(company_id, PULSE))


def _check(insight: Insight, by: Membership) -> Insight:
    if by is None or not access.can_see(by, insight):
        raise PermissionDenied(_("You don't have access to this."))
    return Insight.objects.select_for_update().get(pk=insight.pk)


def _record(action: str, insight: Insight, by: Membership, **details) -> None:
    audit.record(
        action,
        company_id=insight.company_id,
        actor=by.user,
        target=insight,
        kind=insight.kind,
        **details,
    )


def _settle(insight: Insight, outcome, by: Membership) -> None:
    from apps.inbox import services as inbox

    inbox.settle(insight, outcome=outcome, by=by)


@transaction.atomic
def acknowledge(insight: Insight, *, by: Membership) -> Insight:
    """Seen: it stays on the list (still true), quieter, until it resolves."""
    insight = _check(insight, by)
    if insight.status == Insight.Status.ACKNOWLEDGED:
        return insight
    if insight.status != Insight.Status.OPEN:
        raise DomainError(_("This insight is no longer open."))
    insight.status = Insight.Status.ACKNOWLEDGED
    insight.acknowledged_by = by.user
    insight.acknowledged_at = timezone.now()
    insight.save(update_fields=["status", "acknowledged_by", "acknowledged_at", "updated_at"])
    _record(InsightAction.ACKNOWLEDGED, insight, by)
    _settle(insight, SEEN, by)
    _bump(insight.company_id)
    return insight


@transaction.atomic
def dismiss(insight: Insight, *, by: Membership, reason: str = "") -> Insight:
    """Not worth acting on: hidden until it goes away and happens again."""
    insight = _check(insight, by)
    if insight.status not in Insight.LIVE:
        raise DomainError(_("This insight is no longer open."))
    insight.status = Insight.Status.DISMISSED
    insight.dismissed_by = by.user
    insight.dismissed_at = timezone.now()
    insight.dismissed_reason = (reason or "").strip()[:300]
    insight.save(
        update_fields=["status", "dismissed_by", "dismissed_at", "dismissed_reason", "updated_at"]
    )
    _record(InsightAction.DISMISSED, insight, by, reason=insight.dismissed_reason)
    _settle(insight, DISMISSED, by)
    _bump(insight.company_id)
    return insight


@transaction.atomic
def resolve(insight: Insight, *, by: Membership) -> Insight:
    """Dealt with. If the numbers still show it a day later, it opens again."""
    insight = _check(insight, by)
    if insight.status not in Insight.LIVE:
        raise DomainError(_("This insight is no longer open."))
    insight.status = Insight.Status.RESOLVED
    insight.resolved_at = timezone.now()
    insight.save(update_fields=["status", "resolved_at", "updated_at"])
    _record(InsightAction.RESOLVED, insight, by)
    _settle(insight, RESOLVED, by)
    _bump(insight.company_id)
    return insight


def _due_at(company, day: date | None) -> datetime | None:
    if day is None:
        return None
    return datetime.combine(day, DUE_AT, tzinfo=ZoneInfo(company.timezone))


@transaction.atomic
def make_task(
    insight: Insight,
    *,
    by: Membership,
    assignee: Membership | None = None,
    due_on: date | None = None,
    title: str = "",
):
    """A task from the insight (to `by`, or to `assignee` when `by` may give work), its
    explanation and suggested action as the description. The insight counts as seen."""
    from apps.tasks import services as tasks

    insight = _check(insight, by)
    if insight.status not in Insight.LIVE:
        raise DomainError(_("This insight is no longer open."))
    if insight.task_id is not None and insight.task.status not in ("done", "cancelled"):
        raise DomainError(_("A task for this insight already exists."))
    if assignee is not None and assignee.company_id != insight.company_id:
        raise DomainError(_("Pick someone from this company."))
    words = texts.of(insight)
    description = "\n\n".join(part for part in (words.explanation, words.action) if part)
    task = tasks.create_task(
        by=by,
        title=(title or words.title).strip()[:200],
        description=description,
        assignee=assignee,
        due_at=_due_at(insight.company, due_on),
        priority="high" if insight.severity == Insight.Severity.CRITICAL else "normal",
    )
    insight.task = task
    fields = ["task", "updated_at"]
    if insight.status == Insight.Status.OPEN:
        insight.status = Insight.Status.ACKNOWLEDGED
        insight.acknowledged_by = by.user
        insight.acknowledged_at = timezone.now()
        fields += ["status", "acknowledged_by", "acknowledged_at"]
    insight.save(update_fields=fields)
    _record(InsightAction.TASK_MADE, insight, by, task=task.pk)
    _settle(insight, TASK_MADE, by)
    _bump(insight.company_id)
    return task


SETTINGS_FIELDS = (
    "disabled_kinds",
    "sensitivity",
    "quiet_from",
    "quiet_to",
    "notify_critical_via_bot",
    "min_cash_buffer",
    "expense_alert_min_amount",
)


@transaction.atomic
def update_settings(company, *, by: Membership, **changes) -> InsightSettings:
    row = conf.get_settings(company)
    row = InsightSettings.objects.select_for_update().get(pk=row.pk)
    unknown = set(changes) - set(SETTINGS_FIELDS)
    if unknown:
        raise ValueError(f"Not insight settings: {sorted(unknown)}")
    if "disabled_kinds" in changes:
        kinds = sorted(set(changes["disabled_kinds"]))
        wrong = [kind for kind in kinds if kind not in Insight.Kind.values]
        if wrong:
            raise DomainError(_("Unknown kinds: %(kinds)s") % {"kinds": ", ".join(wrong)})
        changes["disabled_kinds"] = kinds
    before = {name: _plain(getattr(row, name)) for name in changes}
    for name, value in changes.items():
        setattr(row, name, value)
    row.save()
    after = {name: _plain(getattr(row, name)) for name in changes}
    changed = {name: [before[name], after[name]] for name in changes if before[name] != after[name]}
    if changed:
        audit.record(
            InsightAction.SETTINGS_CHANGED,
            company_id=company.pk,
            actor=by.user,
            target=row,
            changes=changed,
        )
        _bump(company.pk)
    return row


def _plain(value):
    if isinstance(value, time):
        return value.strftime("%H:%M")
    if isinstance(value, list):
        return list(value)
    return None if value is None else str(value) if not isinstance(value, bool) else value


@transaction.atomic
def check_now(company, *, by: Membership) -> dict:
    """Run the rules at once (the cockpit's "Check now")."""
    from apps.insights import engine

    result = engine.run(company)
    audit.record(
        InsightAction.CHECKED,
        company_id=company.pk,
        actor=by.user,
        target=conf.get_settings(company),
        **{key: value for key, value in result.items() if value},
    )
    return result
