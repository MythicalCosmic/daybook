"""Who hears what about sales and cash (docs/PLAN-OWNER.md §1.7, §10.2).

Every function here runs after the change committed (services queue them with
`transaction.on_commit`; the operational scan calls them directly). They take ids, read fresh
rows and send through `apps.inbox.services.notify` (in-app plus Telegram per the kind and the
person's preferences) and `apps.groups.services.broadcast` (the company's "Kassa" groups).

Managers of a branch are the approved members holding `sales.manage` whose branch scope covers
it, plus the branch's own manager; owners hold every permission, so they are always among them.
Alerts the scan repeats every few minutes carry a dedupe key, so each goes out once.
"""

import logging

from django.utils import translation
from django.utils.translation import gettext_lazy as _

from apps.groups.models import GroupEvent
from apps.groups.services import broadcast
from apps.inbox.models import Notification
from apps.inbox.services import NotificationAction, notify
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.sales import bot_messages as msg
from apps.sales.models import CashMovement, CashShift

logger = logging.getLogger(__name__)

RECEIVED = NotificationAction("received", _("Received"), "primary")
NOT_RECEIVED = NotificationAction("not_received", _("Not received"), "danger")
VERIFY = NotificationAction("verify", _("Verify"), "primary")


# Recipients ------------------------------------------------------------------------------


def managers(company, branch_id: int | None) -> list[Membership]:
    """People who run sales at the branch (or company-wide when `branch_id` is None)."""
    people = (
        Membership.objects.filter(company=company, status=Membership.Status.APPROVED)
        .select_related("role", "user", "company")
        .prefetch_related("branches")
    )
    found = []
    branch_manager_id = None
    if branch_id is not None:
        from apps.companies.models import Branch

        branch_manager_id = (
            Branch.objects.filter(pk=branch_id).values_list("manager_id", flat=True).first()
        )
    for person in people:
        if person.pk == branch_manager_id or (
            person.has_perm(Perm.SALES_MANAGE)
            and (branch_id is None or scope.allows(scope.branch_ids(person), branch_id))
        ):
            found.append(person)
    return found


def owners(company) -> list[Membership]:
    return list(
        Membership.objects.filter(
            company=company, status=Membership.Status.APPROVED, role__is_owner=True
        ).select_related("user", "role", "company")
    )


def already_sent(company_id: int, dedupe_key: str) -> bool:
    return Notification.objects.filter(company_id=company_id, dedupe_key=dedupe_key).exists()


def shift_url(shift: CashShift) -> str:
    return f"/c/{shift.company_id}/sales/shifts?shift={shift.pk}"


def cash_url(company_id: int) -> str:
    return f"/c/{company_id}/sales/cash"


def _shift(pk: int) -> CashShift | None:
    return (
        CashShift.objects.select_related("company", "branch", "register", "cashier__user")
        .filter(pk=pk)
        .first()
    )


def _movement(pk: int) -> CashMovement | None:
    return (
        CashMovement.objects.select_related(
            "company", "branch", "register", "shift", "receiver__user", "created_by__user"
        )
        .filter(pk=pk)
        .first()
    )


def _net(shift: CashShift):
    return sum((p.sales - p.refunds for p in shift.payments.all()), 0)


# Shifts --------------------------------------------------------------------------------


def shift_closed(shift_id: int) -> None:
    """A closed shift waits in Needs you; a difference above tolerance is critical; the
    company's cash groups get one line."""
    shift = _shift(shift_id)
    if shift is None:
        return
    from apps.sales.conf import get_settings

    settings = get_settings(shift.company)
    net = _net(shift)
    people = [m for m in managers(shift.company, shift.branch_id) if m.pk != shift.cashier_id]
    cashier = str(shift.cashier)
    notify(
        people,
        "sales.shift_closed",
        title=lambda m: msg.closed_title(cashier, shift.code, net),
        body=lambda m: msg.closed_body(shift.branch.name, shift.difference),
        url=shift_url(shift),
        target=shift,
        actor=shift.closed_by,
        actions=[VERIFY],
        dedupe_key=f"sales.closed:{shift.pk}",
    )
    if shift.difference is not None and abs(shift.difference) > settings.cash_tolerance:
        notify(
            people,
            "sales.cash_difference",
            title=lambda m: msg.difference_title(shift.code, shift.difference),
            body=lambda m: msg.difference_body(
                cashier, shift.branch.name, shift.final_count, shift.expected_cash
            ),
            url=shift_url(shift),
            target=shift,
            actor=shift.cashier,
            dedupe_key=f"sales.difference:{shift.pk}:{shift.difference}",
        )
    with translation.override(shift.company.default_language):
        text = msg.group_shift_closed(shift.code, shift.branch.name, cashier, net, shift.difference)
    broadcast(shift.company_id, GroupEvent.CASH, text, branch_id=shift.branch_id)


def float_difference(shift_id: int) -> None:
    shift = _shift(shift_id)
    if shift is None or shift.expected_float is None:
        return
    difference = shift.opening_float - shift.expected_float
    notify(
        managers(shift.company, shift.branch_id),
        "sales.cash_difference",
        title=lambda m: msg.float_title(shift.code, difference),
        body=lambda m: msg.float_body(
            str(shift.cashier), shift.register.name, shift.opening_float, shift.expected_float
        ),
        url=shift_url(shift),
        target=shift,
        actor=shift.cashier,
        dedupe_key=f"sales.float:{shift.pk}",
    )


def shift_verified(shift_id: int) -> None:
    shift = _shift(shift_id)
    if shift is None:
        return
    notify(
        [shift.cashier],
        "sales.shift_verified",
        title=lambda m: msg.verified_title(shift.code),
        body=lambda m: msg.verified_body(shift.difference),
        app_screen=f"kassa.shift:{shift.pk}",
        target=shift,
        actor=shift.verified_by,
    )


def shift_disputed(shift_id: int, by_id: int) -> None:
    shift = _shift(shift_id)
    if shift is None:
        return
    manager = Membership.objects.filter(pk=by_id).first()
    reason = shift.note
    notify(
        [shift.cashier],
        "sales.shift_disputed",
        title=lambda m: msg.disputed_title(shift.code),
        body=lambda m: msg.disputed_body(str(manager) if manager else "", reason),
        app_screen=f"kassa.shift:{shift.pk}",
        target=shift,
        actor=manager,
    )


def ai_mismatch(shift_id: int) -> None:
    shift = _shift(shift_id)
    if shift is None:
        return
    notify(
        managers(shift.company, shift.branch_id),
        "sales.ai_mismatch",
        title=lambda m: msg.ai_mismatch_title(shift.code),
        body=lambda m: msg.ai_mismatch_body(),
        url=shift_url(shift),
        target=shift,
        dedupe_key=f"sales.ai:{shift.pk}",
    )


# Movements -----------------------------------------------------------------------------


def handover_sent(movement_id: int) -> None:
    """The receiver gets [Received] [Not received] in Telegram; in the dashboard the handover
    waits in their Needs you, in the mini app on Kassa's "Received?" card."""
    movement = _movement(movement_id)
    if movement is None or movement.status != "pending":
        return
    cashier = str(movement.created_by)
    till = str(movement.register)
    notify(
        [movement.receiver],
        "sales.handover",
        title=lambda m: msg.handover_title(cashier, movement.amount, movement.currency),
        body=lambda m: msg.handover_body(till, movement.reason),
        url=cash_url(movement.company_id),
        app_screen="kassa",
        target=movement,
        actor=movement.created_by,
        actions=[RECEIVED, NOT_RECEIVED],
    )


def handover_declined(movement_id: int) -> None:
    movement = _movement(movement_id)
    if movement is None:
        return
    people = {m.pk: m for m in owners(movement.company)}
    for person in managers(movement.company, movement.branch_id):
        people.setdefault(person.pk, person)
    people.pop(movement.receiver_id, None)
    receiver, cashier, till = (
        str(movement.receiver),
        str(movement.created_by),
        str(movement.register),
    )
    notify(
        list(people.values()),
        "sales.handover_declined",
        title=lambda m: msg.handover_declined_title(movement.amount, movement.currency),
        body=lambda m: msg.handover_declined_body(receiver, cashier, till, movement.decline_reason),
        url=cash_url(movement.company_id),
        target=movement,
        actor=movement.receiver,
        dedupe_key=f"sales.declined:{movement.pk}",
    )


def handover_late(movement_id: int, hours: int) -> None:
    movement = _movement(movement_id)
    if movement is None or movement.status != "pending":
        return
    key = f"sales.handover_late:{movement.pk}"
    if already_sent(movement.company_id, key):
        return
    people = {m.pk: m for m in managers(movement.company, movement.branch_id)}
    people.pop(movement.created_by_id, None)
    cashier, receiver = str(movement.created_by), str(movement.receiver)
    notify(
        list(people.values()),
        "sales.handover_late",
        title=lambda m: msg.handover_late_title(movement.amount, movement.currency, hours),
        body=lambda m: msg.handover_late_body(cashier, receiver, movement.branch.name),
        url=cash_url(movement.company_id),
        target=movement,
        dedupe_key=key,
    )


def big_payout(movement_id: int) -> None:
    movement = _movement(movement_id)
    if movement is None or movement.voided_at is not None:
        return
    people = [
        m for m in managers(movement.company, movement.branch_id) if m.pk != movement.created_by_id
    ]
    person, till = str(movement.created_by), str(movement.register)
    notify(
        people,
        "sales.big_payout",
        title=lambda m: msg.big_payout_title(movement.amount, movement.currency),
        body=lambda m: msg.big_payout_body(person, till, movement.reason),
        url=cash_url(movement.company_id),
        target=movement,
        actor=movement.created_by,
        dedupe_key=f"sales.payout:{movement.pk}",
    )


# Operational (from the scan) -------------------------------------------------------------


def branch_not_opened(branch, day, opens_at: str, minutes: int) -> bool:
    key = f"sales.not_opened:{branch.pk}:{day.isoformat()}"
    if already_sent(branch.company_id, key):
        return False
    notify(
        managers(branch.company, branch.pk),
        "sales.branch_not_opened",
        title=lambda m: msg.not_opened_title(branch.name),
        body=lambda m: msg.not_opened_body(opens_at, minutes),
        url=f"/c/{branch.company_id}/sales",
        target=branch,
        dedupe_key=key,
    )
    return True


def shift_not_closed(shift: CashShift, closes_at: str) -> bool:
    key = f"sales.not_closed:{shift.pk}"
    if already_sent(shift.company_id, key):
        return False
    cashier = str(shift.cashier)
    people = [m for m in managers(shift.company, shift.branch_id) if m.pk != shift.cashier_id]
    notify(
        people,
        "sales.shift_not_closed",
        title=lambda m: msg.not_closed_title(shift.code),
        body=lambda m: msg.not_closed_body(cashier, shift.branch.name, closes_at),
        url=shift_url(shift),
        target=shift,
        dedupe_key=key,
    )
    notify(
        [shift.cashier],
        "sales.till_open",
        title=lambda m: msg.till_open_title(),
        body=lambda m: msg.till_open_body(shift.code, shift.branch.name),
        app_screen="kassa",
        target=shift,
        dedupe_key=key,
    )
    return True


def cash_over_limit(branch, day, amount) -> bool:
    key = f"sales.over_limit:{branch.pk}:{day.isoformat()}"
    if already_sent(branch.company_id, key):
        return False
    notify(
        managers(branch.company, branch.pk),
        "sales.cash_over_limit",
        title=lambda m: msg.over_limit_title(branch.name, amount),
        body=lambda m: msg.over_limit_body(branch.cash_limit),
        url=cash_url(branch.company_id),
        target=branch,
        dedupe_key=key,
    )
    return True
