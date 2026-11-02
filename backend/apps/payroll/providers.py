"""What payroll hands to the shared registries (wired in `hooks.py`): "Needs you" items, the
team directory's salary field, the setup step and the payslip file check."""

from __future__ import annotations

from datetime import datetime

from django.utils.translation import gettext as _

from apps.console.registry import QueueAction, QueueItem
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.payroll import periods, queries
from apps.payroll.models import Adjustment, Compensation, Payslip


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
