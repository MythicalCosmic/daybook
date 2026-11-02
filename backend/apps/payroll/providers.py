"""What payroll hands to the shared registries (wired in `hooks.py`): "Needs you" items, the
team directory's salary field, the setup step and the payslip file check."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _l
from rest_framework import serializers

from apps.console.registry import QueueAction, QueueItem
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.payroll import periods, queries
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
    ("person", _l("Person")),
    ("position", _l("Position")),
    ("branch", _l("Branch")),
    ("month", _l("Month")),
    ("pay_type", _l("Pay type")),
    ("scheduled_days", _l("Working days"), "number"),
    ("paid_days", _l("Paid days"), "number"),
    ("base_pay", _l("Base pay"), "money"),
    ("extra", _l("Overtime, nights, holidays"), "money"),
    ("bonuses", _l("Bonuses"), "money"),
    ("fines", _l("Fines and deductions"), "money"),
    ("taxes", _l("Taxes withheld"), "money"),
    ("advances", _l("Advances repaid"), "money"),
    ("reimbursements", _l("Expenses paid back"), "money"),
    ("gross", _l("Earned"), "money"),
    ("net", _l("To be paid"), "money"),
    ("currency", _l("Currency")),
    ("status", _l("Status")),
    ("paid_at", _l("Paid"), "datetime"),
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
