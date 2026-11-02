"""The automatic bonuses and fines (`AdjustmentRule`, docs/PLAN-OWNER.md §3.13, §14.11): a plain
module the services, the run and the Celery jobs use.

A rule reads one metric of a person's month (or of the month so far, for daily rules) and turns
it into an amount:

- `once`: when `metric op threshold` holds, `amount` (or `amount` % of the base);
- `per_unit`: `amount` for each unit above `free_units` (a threshold, when set, gates it);
- `tiered`: the best tier the metric reaches (`tiers`: thresholds with their own amounts);

capped by `cap`. A percent rule takes `amount` % of the metric itself for money metrics
(`sales.net`: 1 % of 48 000 000 net sales is 480 000) and of the person's month's pay for the
others. Task metrics count only for people with at least `min_tasks` tasks.

What a rule proposes is an `Adjustment` with a `rule_key` (`r<rule>:m<member>:<month or day>`):
evaluating again never doubles. A monthly rule keeps one adjustment a person a month: while
nobody decided it (or it was approved automatically) it follows the metric, and it is voided
when the metric no longer earns it. A daily rule proposes, each day, what the month so far
earns beyond what it already proposed. Decided rows never change.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from apps.core.money import quantize
from apps.payroll import conf, periods, queries
from apps.payroll.models import Adjustment, AdjustmentRule, Compensation

logger = logging.getLogger(__name__)

ZERO = Decimal(0)
HUNDRED = Decimal(100)
Metric = AdjustmentRule.Metric
Mode = AdjustmentRule.Mode
Op = AdjustmentRule.Op
TASK_METRICS = {
    Metric.TASKS_ON_TIME_PERCENT,
    Metric.TASKS_DONE,
    Metric.TASKS_LATE,
    Metric.TASKS_MISSED,
    Metric.TASKS_REMINDERS_PER_TASK,
    Metric.TASKS_AVG_DELAY,
}
MONEY_METRICS = {Metric.SALES_NET}


# Metrics --------------------------------------------------------------------------------


@dataclass
class Facts:
    """One person's numbers over a range, for every metric."""

    values: dict[str, Decimal | None] = field(default_factory=dict)
    task_total: int = 0


def facts(company, start: date, end: date, member_ids, *, now: datetime | None = None):
    """{member id: Facts} from `start` to `end` (both included)."""
    from apps.attendance import queries as attendance
    from apps.attendance.models import AttendanceRecord
    from apps.reports import kpis

    now = now or timezone.now()
    ids = set(member_ids)
    found = {member_id: Facts() for member_id in ids}
    report = kpis.team(company, start, end + timedelta(days=1), now, branch_ids=None)
    for member, score in report.rows:
        if member.pk not in found:
            continue
        values = found[member.pk].values
        found[member.pk].task_total = score.total
        values[Metric.TASKS_ON_TIME_PERCENT] = (
            Decimal(str(score.on_time_exact)) if score.on_time_exact is not None else None
        )
        values[Metric.TASKS_DONE] = Decimal(score.done)
        values[Metric.TASKS_LATE] = Decimal(score.late)
        values[Metric.TASKS_MISSED] = Decimal(score.missed)
        values[Metric.TASKS_REMINDERS_PER_TASK] = (
            (Decimal(score.reminders) / Decimal(score.total)).quantize(Decimal("0.01"))
            if score.total
            else None
        )
        values[Metric.TASKS_AVG_DELAY] = (
            Decimal(score.avg_delay_minutes) if score.avg_delay_minutes is not None else None
        )
    summary = attendance.period_summary(company, start, end, branch_ids=None, member_ids=list(ids))
    early = {}
    for member_id in (
        attendance.records_between(company, start, end, branch_ids=None)
        .filter(membership_id__in=ids, early_leave_minutes__gt=0)
        .filter(status__in=AttendanceRecord.ATTENDED)
        .values_list("membership_id", flat=True)
    ):
        early[member_id] = early.get(member_id, 0) + 1
    for member_id in ids:
        values = found[member_id].values
        row = summary.get(member_id)
        values[Metric.LATE_ARRIVALS] = Decimal(row.late_arrivals if row else 0)
        values[Metric.LATE_MINUTES] = Decimal(row.late_minutes if row else 0)
        values[Metric.ABSENCES] = Decimal(row.absent_days if row else 0)
        values[Metric.EARLY_LEAVES] = Decimal(early.get(member_id, 0))
        values[Metric.HOURS] = (
            (Decimal(row.worked_minutes) / Decimal(60)).quantize(Decimal("0.01")) if row else ZERO
        )
        values[Metric.SALES_NET] = ZERO
    if company.has_feature("sales"):
        from apps.sales import queries as sales

        for row in sales.cashier_scorecard(company, start, end, branch_ids=None):
            member_id = (row.get("member") or {}).get("id")
            if member_id in found:
                found[member_id].values[Metric.SALES_NET] = quantize(Decimal(row["net"]))
    return found


# One rule, one person -------------------------------------------------------------------


def holds(value: Decimal, op: str, threshold: Decimal) -> bool:
    return {
        Op.GTE: value >= threshold,
        Op.GT: value > threshold,
        Op.LTE: value <= threshold,
        Op.LT: value < threshold,
    }[op]


def tiers(rule: AdjustmentRule) -> list[tuple[Decimal, Decimal]]:
    """[(threshold, amount)] of a tiered rule, best first for its direction."""
    found = []
    for tier in rule.tiers or []:
        try:
            found.append((Decimal(str(tier["threshold"])), Decimal(str(tier["amount"]))))
        except KeyError, TypeError, InvalidOperation:
            continue
    descending = rule.op in (Op.GTE, Op.GT)
    return sorted(found, key=lambda pair: pair[0], reverse=descending)


@dataclass
class Outcome:
    amount: Decimal
    value: Decimal
    units: Decimal | None = None
    tier: Decimal | None = None


def outcome(rule: AdjustmentRule, value: Decimal | None, base: Decimal | None) -> Outcome | None:
    """What `rule` gives for a metric `value` (None: nothing). `base` is what a percent rule
    takes its percent of (the metric for money metrics, a month's pay otherwise)."""
    if value is None:
        return None

    def money(amount: Decimal) -> Decimal | None:
        if rule.amount_type == AdjustmentRule.AmountType.PERCENT:
            if base is None:
                return None
            return quantize(base * amount / HUNDRED)
        return quantize(amount)

    units = None
    tier = None
    if rule.mode == Mode.ONCE:
        if rule.threshold is None or rule.amount is None:
            return None
        if not holds(value, rule.op, rule.threshold):
            return None
        amount = money(rule.amount)
    elif rule.mode == Mode.PER_UNIT:
        if rule.amount is None:
            return None
        if rule.threshold is not None and not holds(value, rule.op, rule.threshold):
            return None
        units = value - (rule.free_units or ZERO)
        if units <= 0:
            return None
        per_unit = money(rule.amount)
        amount = quantize(per_unit * units) if per_unit is not None else None
    else:
        chosen = next(((t, a) for t, a in tiers(rule) if holds(value, rule.op, t)), None)
        if chosen is None:
            return None
        tier = chosen[0]
        amount = money(chosen[1])
    if amount is None or amount <= 0:
        return None
    if rule.cap is not None:
        amount = min(amount, rule.cap)
    return Outcome(amount=amount, value=value, units=units, tier=tier)


def number_text(value: Decimal) -> str:
    """93.50 → "93.5", 48000000.00 → "48000000" (never in exponent form)."""
    text = format(quantize(value), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def reason(rule: AdjustmentRule, result: Outcome) -> str:
    if rule.metric in MONEY_METRICS:
        value = queries.money_text(result.value, conf.get_settings(rule.company).currency)
    else:
        value = number_text(result.value)
    return _("%(rule)s: %(metric)s %(value)s") % {
        "rule": rule.name,
        "metric": AdjustmentRule.Metric(rule.metric).label,
        "value": value,
    }


# Who a rule applies to ------------------------------------------------------------------


def people(company, rule: AdjustmentRule, start: date, end: date) -> dict[int, object]:
    """{member id: membership} the rule applies to: a pay setup in force during the range,
    employed then, in one of the rule's positions (when it names any)."""
    from apps.hr.queries import employment_dates
    from apps.members.models import Membership
    from apps.payroll.services import PAYABLE_STATUSES

    members = Membership.objects.for_company(company).filter(status__in=PAYABLE_STATUSES)
    positions = list(rule.positions.values_list("pk", flat=True))
    if positions:
        members = members.filter(position_id__in=positions)
    members = {member.pk: member for member in members.select_related("user", "position")}
    paid = queries.in_force(list(members), start, end)
    dates = employment_dates(company, list(paid))
    found = {}
    for member_id in paid:
        first, last = dates.get(member_id, (None, None))
        if first is None or first > end or (last is not None and last < start):
            continue
        found[member_id] = members[member_id]
    return found


def _base(member, rule: AdjustmentRule, values: dict, on: date) -> Decimal | None:
    if rule.metric in MONEY_METRICS:
        return values.get(rule.metric)
    return queries.monthly_pay(member, on=on)


@dataclass
class Proposal:
    member: object
    value: Decimal | None
    outcome: Outcome | None


def assess(rule: AdjustmentRule, start: date, end: date, *, now=None) -> list[Proposal]:
    """Every person the rule applies to with their metric and what it gives them."""
    company = rule.company
    members = people(company, rule, start, end)
    if not members:
        return []
    numbers = facts(company, start, end, list(members), now=now)
    found = []
    for member_id, member in sorted(members.items(), key=lambda item: str(item[1])):
        person = numbers[member_id]
        value = person.values.get(rule.metric)
        if rule.metric in TASK_METRICS and person.task_total < rule.min_tasks:
            found.append(Proposal(member, value, None))
            continue
        base = _base(member, rule, person.values, end)
        found.append(Proposal(member, value, outcome(rule, value, base)))
    return found


# Writing --------------------------------------------------------------------------------


def _key(rule: AdjustmentRule, member_id: int, when: date, *, daily: bool) -> str:
    stamp = f"{when:%Y-%m-%d}" if daily else f"{when:%Y-%m}"
    return f"r{rule.pk}:m{member_id}:{stamp}"


def _create(rule, member, period, amount, text, key) -> Adjustment:
    status = Adjustment.Status.APPROVED if rule.auto_approve else Adjustment.Status.PROPOSED
    row = Adjustment.objects.create(
        company=rule.company,
        membership=member,
        period=period,
        kind=rule.kind,
        amount=amount,
        currency=conf.get_settings(rule.company).currency,
        reason=text[:300],
        source=Adjustment.Source.RULE,
        rule=rule,
        rule_key=key,
        status=status,
        decided_at=timezone.now() if rule.auto_approve else None,
    )
    from apps.payroll import notify

    if rule.auto_approve:
        notify.adjustment_approved(row, None)
    else:
        notify.adjustment_proposed(row, None)
    return row


def voided_by_rule(row: Adjustment) -> bool:
    """Voided by its rule (the metric stopped earning it), not by a person."""
    return row.status == Adjustment.Status.VOID and row.decided_by_id is None


def _follows(row: Adjustment, rule: AdjustmentRule) -> bool:
    """A rule adjustment still following its metric: undecided, approved automatically, or
    voided by the rule itself (it comes back when the metric earns it again). What a person
    decided stays."""
    if row.is_locked:
        return False
    if row.status == Adjustment.Status.PROPOSED or voided_by_rule(row):
        return True
    return (
        row.status == Adjustment.Status.APPROVED and rule.auto_approve and row.decided_by_id is None
    )


def _period_open(company, period: date) -> bool:
    """Whether the month's regular run isn't finalized. The run row is locked until the
    transaction ends, so a finalize waits for this evaluation (or this one for it)."""
    from apps.payroll.models import PayrollRun

    run = (
        PayrollRun.objects.select_for_update()
        .filter(company=company, kind=PayrollRun.Kind.REGULAR, period=period)
        .exclude(status=PayrollRun.Status.CANCELLED)
        .first()
    )
    return run is None or run.status not in (PayrollRun.Status.FINALIZED, PayrollRun.Status.PAID)


def evaluate_monthly(company, period, *, by=None, now=None) -> int:
    """Propose (or update) every active monthly rule's adjustments for `period`; returns how
    many rows changed. Reasons are written in the company's language."""
    with translation.override(company.default_language or "uz"):
        return _evaluate_monthly(company, period, now=now)


@transaction.atomic
def _evaluate_monthly(company, period, *, now=None) -> int:
    period = periods.first_day(period)
    if not company.has_feature("payroll") or not _period_open(company, period):
        return 0
    start, end = periods.bounds(period)
    today = periods.today(company, now)
    end = min(end, today)
    if end < start:
        return 0
    changed = 0
    rules = AdjustmentRule.objects.for_company(company).filter(
        is_active=True, evaluate=AdjustmentRule.Evaluate.MONTHLY
    )
    for rule in rules.prefetch_related("positions"):
        existing = {
            row.membership_id: row
            for row in Adjustment.objects.filter(
                company=company, rule=rule, period=period, rule_key__startswith=f"r{rule.pk}:m"
            )
        }
        for proposal in assess(rule, start, end, now=now):
            member = proposal.member
            key = _key(rule, member.pk, period, daily=False)
            row = existing.get(member.pk)
            result = proposal.outcome
            if row is None:
                if result is not None:
                    _create(rule, member, period, result.amount, reason(rule, result), key)
                    changed += 1
                continue
            if not _follows(row, rule):
                continue
            if result is None:
                if voided_by_rule(row):
                    continue
                row.status = Adjustment.Status.VOID
                row.decision_note = _("The rule no longer applies.")
                row.save(update_fields=["status", "decision_note", "updated_at"])
                changed += 1
            elif voided_by_rule(row):
                # The metric earns it again: the rule's own void comes back to life.
                row.status = (
                    Adjustment.Status.APPROVED if rule.auto_approve else Adjustment.Status.PROPOSED
                )
                row.amount = result.amount
                row.reason = reason(rule, result)[:300]
                row.decision_note = ""
                row.decided_at = timezone.now() if rule.auto_approve else None
                row.save(
                    update_fields=[
                        "status",
                        "amount",
                        "reason",
                        "decision_note",
                        "decided_at",
                        "updated_at",
                    ]
                )
                changed += 1
            elif row.amount != result.amount or row.reason != reason(rule, result)[:300]:
                row.amount = result.amount
                row.reason = reason(rule, result)[:300]
                row.save(update_fields=["amount", "reason", "updated_at"])
                changed += 1
    if changed:
        from apps.payroll.services import PULSE_ADJUSTMENTS, PULSE_PENDING, _bump

        _bump(company.pk, PULSE_ADJUSTMENTS, PULSE_PENDING)
    return changed


def evaluate_daily(company, today: date, *, now=None) -> int:
    """Daily rules for the month so far, up to yesterday: each person gets what the month so
    far earns beyond what the rule already proposed this month (one row a day at most)."""
    with translation.override(company.default_language or "uz"):
        return _evaluate_daily(company, today, now=now)


@transaction.atomic
def _evaluate_daily(company, today: date, *, now=None) -> int:
    yesterday = today - timedelta(days=1)
    period = periods.first_day(yesterday)
    if not company.has_feature("payroll") or not _period_open(company, period):
        return 0
    changed = 0
    rules = AdjustmentRule.objects.for_company(company).filter(
        is_active=True, evaluate=AdjustmentRule.Evaluate.DAILY
    )
    for rule in rules.prefetch_related("positions"):
        prefix = f"r{rule.pk}:m"
        for proposal in assess(rule, period, yesterday, now=now):
            member = proposal.member
            key = _key(rule, member.pk, yesterday, daily=True)
            rows = Adjustment.objects.filter(
                company=company,
                rule=rule,
                membership=member,
                period=period,
                rule_key__startswith=prefix,
            )
            if rows.filter(rule_key=key).exists():
                continue
            # What the rule already put to people this month: a fine a manager rejected or
            # voided counts as handled and is never proposed again.
            already = sum((row.amount for row in rows if not voided_by_rule(row)), ZERO)
            due = proposal.outcome.amount if proposal.outcome is not None else ZERO
            if due > already:
                text = reason(rule, proposal.outcome)
                _create(rule, member, period, quantize(due - already), text, key)
                changed += 1
    if changed:
        from apps.payroll.services import PULSE_ADJUSTMENTS, PULSE_PENDING, _bump

        _bump(company.pk, PULSE_ADJUSTMENTS, PULSE_PENDING)
    return changed


def preview(rule: AdjustmentRule, period: date, *, now=None) -> dict:
    """A dry run for `period`: who would get what, and the total (nothing is written)."""
    period = periods.first_day(period)
    start, end = periods.bounds(period)
    end = min(end, periods.today(rule.company, now))
    rows = []
    if end >= start:
        for proposal in assess(rule, start, end, now=now):
            result = proposal.outcome
            rows.append(
                {
                    "member": proposal.member,
                    "value": proposal.value,
                    "amount": result.amount if result else None,
                    "units": result.units if result else None,
                    "tier": result.tier if result else None,
                }
            )
    total = sum((row["amount"] for row in rows if row["amount"]), ZERO)
    return {"period": period, "to": end, "rows": rows, "total": total}


def progress(member, period: date, *, now=None) -> list[dict]:
    """The person's place on each active bonus rule this month (the wallet's progress bars):
    the metric so far, the next threshold and what reaching it gives."""
    company = member.company
    start, end = periods.bounds(period)
    end = min(end, periods.today(company, now))
    if end < start:
        return []
    rules = [
        rule
        for rule in AdjustmentRule.objects.for_company(company)
        .filter(is_active=True, kind=AdjustmentRule.Kind.BONUS)
        .prefetch_related("positions")
        if not rule.positions.exists() or rule.positions.filter(pk=member.position_id).exists()
    ]
    if not rules or not Compensation.objects.filter(membership=member).exists():
        return []
    numbers = facts(company, start, end, [member.pk], now=now)[member.pk]
    found = []
    for rule in rules:
        value = numbers.values.get(rule.metric)
        if value is None:
            continue
        base = _base(member, rule, numbers.values, end)
        current = outcome(rule, value, base)
        target = None
        reward = None
        if rule.mode == Mode.TIERED:
            ahead = [
                (threshold, amount)
                for threshold, amount in reversed(tiers(rule))
                if not holds(value, rule.op, threshold)
            ]
            if ahead:
                target = ahead[0][0]
                reward = outcome(rule, target, base)
        elif rule.mode == Mode.ONCE and rule.threshold is not None and current is None:
            target = rule.threshold
            reward = outcome(rule, target, base)
        found.append(
            {
                "rule": rule.pk,
                "name": rule.name,
                "metric": rule.metric,
                "value": value,
                "earned": current.amount if current else ZERO,
                "target": target,
                "target_amount": reward.amount if reward else None,
                "min_tasks": rule.min_tasks if rule.metric in TASK_METRICS else None,
                "tasks": numbers.task_total if rule.metric in TASK_METRICS else None,
            }
        )
    return found
