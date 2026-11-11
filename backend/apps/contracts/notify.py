"""Who hears about a contract's dates, through the inbox (`apps.inbox.services.notify`): the
people who manage money (`finance.manage` with `finance.view`) and see the contract's branch,
and the person looking after it. The owner bot carries the Telegram copy (an owner kind).

    ending     its last day is near ("soon", from the warning days) or today ("today")
    notice     an auto-renewing contract's notice deadline is near or today, with two buttons:
               keep it renewing, or give notice (it then ends on its end date)
    renewed    it renewed by itself (the morning after)

Plain sentences without emoji: they go to Telegram as they are.
"""

from datetime import date

from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.contracts.models import BusinessContract
from apps.core.exceptions import DomainError
from apps.inbox import services as inbox
from apps.inbox.services import NotificationAction
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import members_with_perm

KIND = "contracts.dates"
KEEP, STOP = "keep", "stop"


def _day(day: date) -> str:
    return day.strftime("%d.%m.%Y")


def _name(contract: BusinessContract) -> str:
    return f"{contract.title} ({contract.branch.name})" if contract.branch_id else contract.title


def url(contract: BusinessContract) -> str:
    return f"/c/{contract.company_id}/contracts/{contract.pk}"


def may_manage(member: Membership, contract: BusinessContract) -> bool:
    """`finance.view` and `finance.manage`, and the contract's branch in sight."""
    if not (member.has_perm(Perm.FINANCE_VIEW) and member.has_perm(Perm.FINANCE_MANAGE)):
        return False
    return scope.allows(scope.branch_ids(member), contract.branch_id)


def people(contract: BusinessContract) -> list[Membership]:
    found: list[Membership] = []
    candidates = members_with_perm(contract.company, Perm.FINANCE_MANAGE).select_related(
        "user", "role", "company"
    )
    for candidate in candidates:
        if may_manage(candidate, contract):
            found.append(candidate)
    responsible = contract.responsible if contract.responsible_id else None
    if (
        responsible is not None
        and responsible.status == Membership.Status.APPROVED
        and all(person.pk != responsible.pk for person in found)
    ):
        found.append(responsible)
    return found


def ending(contract: BusinessContract, step: str, today: date) -> int:
    """Its last day is near (`step` "soon") or today ("today")."""
    recipients = people(contract)
    if not recipients:
        return 0
    left = (contract.ends_on - today).days
    name, day = _name(contract), _day(contract.ends_on)

    def title(person):
        if step == "today":
            return _("Contract ends today: %(contract)s") % {"contract": name}
        return _("Contract ends %(day)s: %(contract)s") % {"day": day, "contract": name}

    def body(person):
        if step == "today":
            return _("Today is its last day. Renewed it? Put the new end date on its page.")
        if contract.kind == BusinessContract.Kind.LEASE:
            text = ngettext(
                "%(count)d day left. Agree the renewal with the landlord in time, or plan the "
                "move.",
                "%(count)d days left. Agree the renewal with the landlord in time, or plan the "
                "move.",
                left,
            )
        else:
            text = ngettext(
                "%(count)d day left. Renew it or find a new one in time.",
                "%(count)d days left. Renew it or find a new one in time.",
                left,
            )
        return text % {"count": left}

    sent = inbox.notify(
        recipients,
        KIND,
        title=title,
        body=body,
        url=url(contract),
        target=contract,
        severity="warning" if step == "today" else None,
        dedupe_key=f"contracts.end:{contract.pk}:{contract.ends_on.isoformat()}:{step}",
    )
    return len(sent)


def notice(contract: BusinessContract, step: str, today: date) -> int:
    """The notice deadline of an auto-renewing contract is near ("soon") or today ("today")."""
    recipients = people(contract)
    if not recipients:
        return 0
    deadline = contract.notice_deadline
    name = _name(contract)
    party = contract.counterparty.name if contract.counterparty_id else ""
    values = {
        "contract": name,
        "day": _day(deadline),
        "renews": _day(contract.ends_on),
        "party": party,
    }

    def title(person):
        if step == "today":
            return _("Notice deadline today: %(contract)s") % values
        return _("Notice deadline %(day)s: %(contract)s") % values

    def body(person):
        if step == "today":
            return (
                _("Last day to give notice. Otherwise it renews by itself after %(renews)s.")
                % values
            )
        if party:
            return (
                _(
                    "It renews by itself after %(renews)s. If you don't want that, tell "
                    "%(party)s in writing by %(day)s."
                )
                % values
            )
        return (
            _(
                "It renews by itself after %(renews)s. If you don't want that, tell the other "
                "side in writing by %(day)s."
            )
            % values
        )

    sent = inbox.notify(
        recipients,
        KIND,
        title=title,
        body=body,
        url=url(contract),
        target=contract,
        severity="warning" if step == "today" else None,
        actions=[
            NotificationAction(KEEP, lambda person: _("Keep it renewing"), "primary"),
            NotificationAction(STOP, lambda person: _("We give notice"), "danger"),
        ],
        dedupe_key=f"contracts.notice:{contract.pk}:{deadline.isoformat()}:{step}",
    )
    return len(sent)


def renewed(contract: BusinessContract) -> int:
    """It renewed by itself: who manages money hears it once, the morning after."""
    recipients = people(contract)
    if not recipients:
        return 0
    values = {"contract": _name(contract), "day": _day(contract.ends_on)}
    sent = inbox.notify(
        recipients,
        KIND,
        title=lambda person: _("Renewed by itself: %(contract)s") % values,
        body=lambda person: _("It now runs until %(day)s.") % values,
        url=url(contract),
        target=contract,
        dedupe_key=f"contracts.renewed:{contract.pk}:{contract.ends_on.isoformat()}",
    )
    return len(sent)


# The buttons of a notice reminder (`inbox.registry.register_action`) ------------------------------


def _contract(notification, by: Membership) -> BusinessContract:
    contract = (
        BusinessContract.objects.filter(
            company_id=notification.company_id, pk=notification.target_id
        )
        .select_related("company", "branch")
        .first()
    )
    if contract is None:
        raise DomainError(_("This contract was deleted."))
    if not may_manage(by, contract):
        raise PermissionDenied(_("You don't have permission to do this."))
    return contract


def keep(notification, by: Membership, reason: str) -> str:
    from apps.contracts import services

    contract = _contract(notification, by)
    services.confirm_renewal(contract, by=by)
    return _("It keeps renewing: until %(day)s, then on.") % {"day": _day(contract.ends_on)}


def stop(notification, by: Membership, reason: str) -> str:
    from apps.contracts import services

    contract = _contract(notification, by)
    services.stop_renewal(contract, by=by)
    return _("Noted: it ends on %(day)s. Tell the other side in writing.") % {
        "day": _day(contract.ends_on)
    }
