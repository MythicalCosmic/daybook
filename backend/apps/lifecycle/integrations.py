"""What the people lifecycle reads and calls in other apps (docs/PLAN-OWNER.md §13.4), in one
place. Payroll, assets, tasks, attendance and HR are imported inside the functions: payroll
reads the lifecycle's unpaid days, and a company without one of those modules gets a clear
`DomainError` (a write) or nothing (a read) instead.

    fine = integrations.propose_fine(member, by=hr, amount=Decimal("200000"),
                                     reason="Saqlash sharoiti buzildi", source="discipline")
"""

from datetime import date, datetime
from decimal import Decimal

from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError


def propose_fine(membership, *, by, amount: Decimal, reason: str, source: str):
    """`payroll.services.propose_fine`: a proposed fine for `membership` (an Adjustment)."""
    if not membership.company.has_feature("payroll"):
        raise DomainError(_("Payroll is off for this company: give the warning without a fine."))
    from apps.payroll import services as payroll

    return payroll.propose_fine(membership, by=by, amount=amount, reason=reason, source=source)


def fine_summary(company, fine_id: int | None) -> dict | None:
    """{id, amount, currency, status} of a proposed fine, or None (no fine, or payroll can't
    say). Only for people who may see pay."""
    if not fine_id:
        return None
    from apps.payroll.models import Adjustment

    row = Adjustment.objects.filter(company=company, pk=fine_id).first()
    if row is None:
        return None
    return {
        "id": row.pk,
        "amount": f"{row.amount:.2f}",
        "currency": row.currency,
        "status": row.status,
    }


# Pay (payroll) ---------------------------------------------------------------------------------


def payroll_on(company) -> bool:
    return company.has_feature("payroll")


def current_pay(membership, *, on: date) -> dict | None:
    """{amount, currency, pay_type} of the pay setup in force on `on`, or None (no setup, or
    payroll is off). Only for people who may see pay."""
    if not payroll_on(membership.company):
        return None
    from apps.payroll import queries

    row = queries.compensation(membership, on=on)
    if row is None:
        return None
    return {"amount": f"{row.amount:.2f}", "currency": row.currency, "pay_type": row.pay_type}


def pay_types() -> tuple[str, ...]:
    from apps.payroll.models import PayType

    return tuple(PayType.values)


def payroll_currency(company) -> str:
    from apps.payroll import conf

    return conf.get_settings(company).currency


def propose_pay_change(membership, *, by, setup: dict, effective_on: date, reason: str):
    """`payroll.services.propose_pay_change`: the new pay setup from `effective_on`."""
    if not payroll_on(membership.company):
        raise DomainError(_("Payroll is off for this company, so the pay can't change here."))
    from apps.payroll import services as payroll

    return payroll.propose_pay_change(
        membership, by=by, setup=setup, effective_on=effective_on, reason=reason
    )


def final_run(membership) -> dict | None:
    """The person's final payslip in payroll: {id, status, period, last_day, net, currency},
    or None (none prepared, or payroll is off)."""
    if not payroll_on(membership.company):
        return None
    from apps.payroll.models import PayrollRun

    run = (
        PayrollRun.objects.filter(
            company_id=membership.company_id, membership=membership, kind=PayrollRun.Kind.FINAL
        )
        .exclude(status=PayrollRun.Status.CANCELLED)
        .order_by("-pk")
        .first()
    )
    if run is None:
        return None
    totals = run.totals or {}
    net = totals.get("net")
    return {
        "id": run.pk,
        "status": run.status,
        "period": run.period.isoformat(),
        "last_day": run.last_day.isoformat() if run.last_day else None,
        "net": f"{Decimal(str(net)):.2f}" if net not in (None, "") else None,
        "currency": totals.get("currency") or membership.company.base_currency,
    }


def has_pay(membership, *, on: date) -> bool:
    if not payroll_on(membership.company):
        return False
    from apps.payroll import queries

    return queries.compensation(membership, on=on) is not None


# Equipment (assets), tasks, shifts, contracts ---------------------------------------------------


def held_assets(membership) -> list[tuple[int, str]]:
    """(asset id, "number name") of the company equipment the person holds now."""
    held = held_assets_for(membership.company, [membership.pk]).get(membership.pk, {})
    return list(held.items())


def held_assets_for(company, member_ids) -> dict[int, dict[int, str]]:
    """{member id: {asset id: "number name"}} of what each of them holds now, in number order."""
    if not company.has_feature("assets"):
        return {}
    from apps.assets.models import Asset

    rows = (
        Asset.objects.filter(company=company, custodian_id__in=list(member_ids))
        .exclude(status=Asset.Status.DISPOSED)
        .order_by("number", "pk")
    )
    found: dict[int, dict[int, str]] = {}
    for asset in rows:
        found.setdefault(asset.custodian_id, {})[asset.pk] = f"{asset.number} {asset.name}"
    return found


def open_task_count(membership) -> int:
    return open_task_counts(membership.company, [membership.pk]).get(membership.pk, 0)


def open_task_counts(company, member_ids) -> dict[int, int]:
    """{member id: tasks given to them that are still to do}: routine tasks are left out (they
    are made again for whoever works the day), and so is work waiting for a check."""
    from django.db.models import Count

    from apps.tasks.models import Task

    rows = (
        Task.objects.filter(
            company=company,
            assignee_id__in=list(member_ids),
            kind=Task.Kind.ASSIGNED,
            status__in=Task.OPEN_STATUSES,
        )
        .values("assignee_id")
        .annotate(count=Count("pk"))
    )
    return {row["assignee_id"]: row["count"] for row in rows}


def last_shift_end(membership, day: date) -> datetime | None:
    """When the person's last planned shift starting on `day` ends (a night shift: the next
    morning), or None (no shifts, or attendance is off)."""
    if not membership.company.has_feature("attendance"):
        return None
    from apps.attendance import queries

    ends = [
        shift.ends_at
        for shift in queries.shifts_between(
            membership.company, day, day, branch_ids=None, member_id=membership.pk, drafts=False
        )
    ]
    return max(ends) if ends else None


def offboard_blockers(membership) -> list[str]:
    """What would stop the offboarding now (cash held, an open till…), from every module's
    step of the offboarding wizard."""
    from apps.members import services as members

    preview = members.offboard_preview(membership, by=None)
    return [str(line) for step in preview["steps"] for line in step.get("blockers") or []]


def amend_contract_position(membership, *, by, position, effective_on: date, reason: str) -> bool:
    """The contract in force follows a new position (`hr.contracts.amend`); False when they
    have no contract in force."""
    from apps.hr import contracts

    contract = contracts.active_contract(membership)
    if contract is None or contract.position_id == (position.pk if position else None):
        return False
    contracts.amend(
        contract,
        by=by,
        effective_on=effective_on,
        changes={"position": position},
        reason=reason,
    )
    return True


def hired_on(membership) -> date | None:
    """The first day of their current time here (HR's profile, else the membership)."""
    from apps.hr.queries import employment_dates

    return employment_dates(membership.company, [membership.pk]).get(membership.pk, (None, None))[0]
