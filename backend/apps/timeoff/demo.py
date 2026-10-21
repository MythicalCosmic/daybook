"""Demo data of time off (apps/core/demo_plan.py): leave around today across both pharmacies
(approved, waiting, sick leave written down afterwards, a revoked day and refusals), so the
month calendar and "Needs you" look like a real pharmacy's.

The pharmacies work on public holidays (Yunusobod never closes), so Demo Dorixona has no company
holidays; the distributor's warehouse closes on them.
"""

from datetime import date, timedelta

from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.core import demo_plan
from apps.timeoff.audit_actions import TimeOffAuditAction
from apps.timeoff.models import Holiday, TimeOff


def seed(company, people, now) -> None:
    """Add demo rows to `company`. `people` maps owner, manager, worker, madina, jasur
    and nigora to their memberships."""
    _seed(company, people, now)


def seed_small(company, people, now) -> None:
    """The distributor's holidays and a little leave. `people`: owner, manager, worker and
    cashier."""
    _seed(company, people, now)


def _seed(company, people, now) -> None:
    story = demo_plan.Plan(company, people, now)
    if story.small:
        for year in (story.today.year, story.today.year + 1):
            for (month, day), name in demo_plan.PUBLIC_HOLIDAYS.items():
                Holiday.objects.get_or_create(
                    company=company, date=date(year, month, day), defaults={"name": name}
                )
        for day, name in demo_plan.LUNAR_HOLIDAYS.items():
            Holiday.objects.get_or_create(company=company, date=day, defaults={"name": name})

    for row in story.time_off:
        member = story.member(row.who)
        if member is None:
            continue  # someone the module's own tests don't have
        start, end = story.day(row.first), story.day(row.last)
        clash = TimeOff.objects.filter(
            membership=member,
            status__in=(TimeOff.Status.PENDING, TimeOff.Status.APPROVED),
            first_day__lte=end,
            last_day__gte=start,
        )
        if row.status in ("approved", "pending") and clash.exists():
            continue  # the core demo already made it
        decider = story.member(row.decided_by) if row.decided_by else None
        if row.decided_by and decider is None:
            decider = people["manager"]
        asked = now - timedelta(days=row.asked, hours=3)
        decided = asked + timedelta(hours=20) if row.status != "pending" else None
        recorded = decider if row.recorded else None
        if row.recorded:  # written down afterwards, the day they came back
            asked = decided = min(now, story.at(end + timedelta(days=1), demo_plan.H(9, 10)))
        time_off = TimeOff.objects.create(
            company=company,
            membership=member,
            first_day=start,
            last_day=end,
            status=row.status,
            reason=row.reason,
            decided_by=decider.user if decider and row.status != "pending" else None,
            decided_at=min(decided, now) if decided else None,
            recorded_by=recorded,
        )
        TimeOff.objects.filter(pk=time_off.pk).update(created_at=min(asked, now))
        if row.status == "approved" and decider is not None:
            action = TimeOffAuditAction.RECORDED if recorded else AuditLog.Action.TIME_OFF_APPROVED
            _audit_at(
                action,
                company,
                decider.user,
                time_off,
                min(decided, now),
                first_day=start.isoformat(),
                last_day=end.isoformat(),
            )
        if row.revoked_from is not None:
            revoked_at = now - timedelta(days=1, hours=2)
            owner = people["owner"]
            TimeOff.objects.filter(pk=time_off.pk).update(
                last_day=story.day(row.revoked_from - 1),
                revoked_at=revoked_at,
                revoked_by=owner.user,
                revoke_reason=row.revoke_reason,
            )
            _audit_at(
                TimeOffAuditAction.REVOKED,
                company,
                owner.user,
                time_off,
                revoked_at,
                cancelled_from=story.day(row.revoked_from).isoformat(),
                cancelled_to=end.isoformat(),
                reason=row.revoke_reason,
            )


def _audit_at(action, company, actor, target, when, **details) -> None:
    entry = audit.record(action, company_id=company.pk, actor=actor, target=target, **details)
    AuditLog.objects.filter(pk=entry.pk).update(created_at=when)
