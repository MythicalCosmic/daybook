"""What payroll hands to the shared registries (wired in `hooks.py`): "Needs you" items, the
team directory's salary field, the setup step and the payslip file check."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from rest_framework import serializers

from apps.console.registry import CalendarItem, QueueAction, QueueItem
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.payroll import conf, periods, queries
from apps.payroll.models import Adjustment, Compensation, Payslip, PayslipLine


def _decide(path: str, *, reason: bool = False) -> list[QueueAction]:
    return [
        QueueAction("approve", _("Approve"), "primary", "POST", path, body={"approve": True}),
        QueueAction(
            "reject",
            _("Reject"),
            "danger",
            "POST",
            path,
            body={"approve": False},
            needs_reason=reason,
        ),
    ]


def _visible(member: Membership, queryset):
    return queries.people_scope(queryset, scope.branch_ids(member)).exclude(membership=member)


def _money(amount, currency) -> str:
    return queries.money_text(amount, currency)


# Needs you ------------------------------------------------------------------------------


def adjustment_count(member: Membership) -> int:
    return _visible(member, queries.open_proposals(member.company)).count()


def adjustment_items(member: Membership, limit: int) -> list[QueueItem]:
    company = member.company
    rows = (
        _visible(member, queries.open_proposals(company))
        .select_related("membership__user")
        .order_by("created_at")[:limit]
    )
    items = []
    for row in rows:
        label = Adjustment.Kind(row.kind).label
        items.append(
            QueueItem(
                kind="payroll.adjustments",
                id=row.pk,
                title=_("%(kind)s for %(name)s: %(amount)s")
                % {
                    "kind": label,
                    "name": row.membership,
                    "amount": _money(row.amount, row.currency),
                },
                subtitle=row.reason,
                created_at=row.created_at,
                url=f"/c/{company.pk}/payroll/adjustments?adjustment={row.pk}",
                actions=[
                    QueueAction(
                        "approve",
                        _("Approve"),
                        "primary",
                        "POST",
                        f"payroll/adjustments/{row.pk}/approve/",
                    ),
                    QueueAction(
                        "reject",
                        _("Reject"),
                        "danger",
                        "POST",
                        f"payroll/adjustments/{row.pk}/reject/",
                    ),
                ],
            )
        )
    return items


def advance_count(member: Membership) -> int:
    return _visible(member, queries.requested_advances(member.company)).count()


def advance_items(member: Membership, limit: int) -> list[QueueItem]:
    company = member.company
    rows = (
        _visible(member, queries.requested_advances(company))
        .select_related("membership__user")
        .order_by("created_at")[:limit]
    )
    return [
        QueueItem(
            kind="payroll.advances",
            id=row.pk,
            title=_("%(name)s asks for an advance of %(amount)s")
            % {"name": row.membership, "amount": _money(row.amount, row.currency)},
            subtitle=row.reason,
            created_at=row.created_at,
            url=f"/c/{company.pk}/payroll/advances?advance={row.pk}",
            actions=_decide(f"payroll/advances/{row.pk}/decide/"),
        )
        for row in rows
    ]


def dispute_count(member: Membership) -> int:
    return _visible(member, queries.open_disputes(member.company)).count()


def dispute_items(member: Membership, limit: int) -> list[QueueItem]:
    company = member.company
    rows = (
        _visible(member, queries.open_disputes(company))
        .select_related("membership__user")
        .order_by("disputed_at")[:limit]
    )
    return [
        QueueItem(
            kind="payroll.disputes",
            id=row.pk,
            title=_("%(name)s disputes a fine of %(amount)s")
            % {"name": row.membership, "amount": _money(row.amount, row.currency)},
            subtitle=row.dispute_text,
            created_at=row.disputed_at,
            url=f"/c/{company.pk}/payroll/adjustments?adjustment={row.pk}",
            actions=[
                QueueAction(
                    "answer",
                    _("Answer"),
                    "primary",
                    "POST",
                    f"payroll/adjustments/{row.pk}/answer-dispute/",
                    needs_reason=True,
                ),
            ],
        )
        for row in rows
    ]


# The team directory and Person 360 header -----------------------------------------------


def person_fields(company, member_ids: list[int], now: datetime) -> dict[int, dict]:
    """`{"salary": {amount, currency, pay_type} | None}` per person (payroll.view only)."""
    current = queries.current_compensations(member_ids, periods.today(company, now))
    found = {}
    for member_id in member_ids:
        row = current.get(member_id)
        found[member_id] = {
            "salary": {
                "amount": str(row.amount),
                "currency": row.currency,
                "pay_type": row.pay_type,
            }
            if row is not None
            else None
        }
    return found


# The run as a spreadsheet (for the accountant and the bank) ------------------------------


class RunExportParams(serializers.Serializer):
    run = serializers.IntegerField()


RUN_COLUMNS = [
    ("person", gettext_lazy("Person")),
    ("position", gettext_lazy("Position")),
    ("branch", gettext_lazy("Branch")),
    ("month", gettext_lazy("Month")),
    ("pay_type", gettext_lazy("Pay type")),
    ("scheduled_days", gettext_lazy("Working days"), "number"),
    ("paid_days", gettext_lazy("Paid days"), "number"),
    ("base_pay", gettext_lazy("Base pay"), "money"),
    ("extra", gettext_lazy("Overtime, nights, holidays"), "money"),
    ("bonuses", gettext_lazy("Bonuses"), "money"),
    ("fines", gettext_lazy("Fines and deductions"), "money"),
    ("taxes", gettext_lazy("Taxes withheld"), "money"),
    ("advances", gettext_lazy("Advances repaid"), "money"),
    ("reimbursements", gettext_lazy("Expenses paid back"), "money"),
    ("gross", gettext_lazy("Earned"), "money"),
    ("net", gettext_lazy("To be paid"), "money"),
    ("currency", gettext_lazy("Currency")),
    ("status", gettext_lazy("Status")),
    ("paid_at", gettext_lazy("Paid on"), "datetime"),
]


def run_rows(member: Membership, params: dict):
    """One row per payslip of the run, for the people the exporter sees."""
    from apps.payroll.models import PayrollRun, PayType

    run = PayrollRun.objects.for_company(member.company).filter(pk=params.get("run")).first()
    if run is None:
        return
    payslips = queries.people_scope(
        run.payslips.select_related(
            "membership__user", "membership__position", "membership__home_branch"
        ).prefetch_related("lines"),
        scope.branch_ids(member),
    ).order_by("membership__first_name", "membership__last_name", "pk")
    month = queries.month_label(run.period)
    Kind = PayslipLine.Kind
    statuses = dict(Payslip.Status.choices)
    for payslip in payslips:
        lines = list(payslip.lines.all())

        def total(*kinds, lines=lines):
            return sum((line.amount for line in lines if line.kind in kinds), Decimal(0))

        person = payslip.membership
        yield {
            "person": str(person),
            "position": person.position.name if person.position_id else "",
            "branch": person.home_branch.name if person.home_branch_id else "",
            "month": month,
            "pay_type": str(PayType(payslip.pay_type).label),
            "scheduled_days": payslip.scheduled_days,
            "paid_days": payslip.paid_days,
            "base_pay": payslip.base_pay,
            "extra": total(Kind.OVERTIME, Kind.NIGHT_WORK, Kind.HOLIDAY_WORK, Kind.PIECE),
            "bonuses": total(Kind.BONUS, Kind.ALLOWANCE, Kind.TASK_REWARD),
            "fines": total(Kind.FINE, Kind.DEDUCTION),
            "taxes": total(Kind.INCOME_TAX, Kind.INPS),
            "advances": total(Kind.ADVANCE),
            "reimbursements": total(Kind.REIMBURSEMENT),
            "gross": payslip.gross,
            "net": payslip.net,
            "currency": payslip.currency,
            "status": str(statuses.get(payslip.status, payslip.status)),
            "paid_at": payslip.paid_at,
        }


# Briefings, portfolio cards and the company calendar ------------------------------------


def next_pay_day(company, today: date) -> date:
    settings_row = conf.get_settings(company)
    this_month = date(today.year, today.month, settings_row.pay_day)
    if this_month >= today:
        return this_month
    following = periods.next_period(today)
    return following.replace(day=settings_row.pay_day)


def brief_section(company, day, now, branch_ids) -> dict | None:
    """Payroll for briefings and `/today`: what waits for a decision, and last month's pay
    while it isn't paid (with the pay day)."""
    pending = {
        "adjustments": queries.people_scope(queries.open_proposals(company), branch_ids).count(),
        "disputes": queries.people_scope(queries.open_disputes(company), branch_ids).count(),
        "advances": queries.people_scope(queries.requested_advances(company), branch_ids).count(),
    }
    last = periods.previous_period(day)
    summary = queries.run_summary(company, last, branch_ids=branch_ids)
    run = None
    if summary is not None and summary["status"] != "paid":
        run = {
            "month": last.isoformat(),
            "status": summary["status"],
            "people": summary["people"],
            "net": f"{summary['net']:.2f}",
            "currency": summary["currency"],
        }
    if not any(pending.values()) and run is None:
        return None
    return {"pending": pending, "run": run, "pay_day": next_pay_day(company, day).isoformat()}


def company_facts(company, range_, member: Membership) -> dict:
    """`payroll` portfolio facts: the next pay day and what it will pay (the finalized run,
    else this month's estimate)."""
    today = periods.today(company)
    pay_day = next_pay_day(company, today)
    period = periods.previous_period(pay_day)
    summary = queries.run_summary(company, period, branch_ids=scope.branch_ids(member))
    if summary is not None:
        amount = summary["net"]
    else:
        amount = queries.projected_cost(company, period, branch_ids=scope.branch_ids(member))["net"]
    return {"next_run_on": pay_day.isoformat(), "next_run_amount": f"{amount:.2f}"}


def calendar_events(company, start, end, member) -> list[CalendarItem]:
    """Pay days and advance days in the range."""
    settings_row = conf.get_settings(company)
    items = []
    period = periods.first_day(start)
    while period <= end:
        for day, kind, title in (
            (settings_row.pay_day, "payroll.pay_day", _("Pay day")),
            (settings_row.advance_day, "payroll.advance_day", _("Advance day")),
        ):
            if not day:
                continue
            when = period.replace(day=day)
            if start <= when <= end:
                items.append(
                    CalendarItem(
                        id=f"{kind}:{when.isoformat()}",
                        kind=kind,
                        title=str(title),
                        start=when,
                        end=None,
                        all_day=True,
                        color="success" if kind == "payroll.pay_day" else "info",
                        url="payroll",
                    )
                )
        period = periods.next_period(period)
    return items


# Get started ----------------------------------------------------------------------------


def setup_done(company) -> bool:
    """Done once anyone working here has a pay setup."""
    return Compensation.objects.for_company(company).exists()


# Files ----------------------------------------------------------------------------------


def payslip_check(user, company_id: int, payslip_id: int) -> bool:
    """A payslip PDF opens for its own person (published or paid) and for payroll.view
    holders who see that person."""
    payslip = (
        Payslip.objects.for_company(company_id)
        .select_related("membership")
        .filter(pk=payslip_id)
        .first()
    )
    if payslip is None:
        return False
    if payslip.membership.user_id == user.pk:
        return payslip.status != Payslip.Status.DRAFT
    viewer = (
        Membership.objects.select_related("role", "company")
        .filter(company_id=company_id, user=user, status=Membership.Status.APPROVED)
        .first()
    )
    if viewer is None or not viewer.has_perm(Perm.PAYROLL_VIEW):
        return False
    branches = scope.branch_ids(viewer)
    return branches is None or payslip.membership.branches.filter(pk__in=branches).exists()
