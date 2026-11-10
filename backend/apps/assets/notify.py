"""Who hears about assets, through the inbox (`apps.inbox.services.notify`).

To the person (the staff bot, with a way into the app): something was given to them, to
confirm. To the people who manage assets (`assets.manage` who see the asset's branch, and the
person accountable for it): a warranty, an official instrument check, insurance or a service
coming up or overdue. Once per asset, date and step: `dedupe_key` holds all three.
"""

from datetime import date

from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.assets.models import Asset, AssetAssignment, Permit
from apps.inbox import services as inbox
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import members_with_perm

ISSUED = "assets.issued"
UPKEEP = "assets.upkeep"
MINE_SCREEN = "assets.mine"


def _day(day: date) -> str:
    return day.strftime("%d.%m.%Y")


def _where(asset: Asset) -> str:
    name = f"{asset.number} {asset.name}"
    return f"{name} ({asset.branch.name})" if asset.branch_id else name


def managers(asset: Asset) -> list[Membership]:
    """`assets.manage` holders who see the asset's branch, and the one accountable for it."""
    found: list[Membership] = []
    candidates = members_with_perm(asset.company, Perm.ASSETS_MANAGE).select_related(
        "user", "role", "company"
    )
    for candidate in candidates:
        seen = scope.branch_ids(candidate)
        if seen is None or (asset.branch_id is not None and asset.branch_id in seen):
            found.append(candidate)
    responsible = asset.responsible if asset.responsible_id else None
    if (
        responsible is not None
        and responsible.status == Membership.Status.APPROVED
        and all(person.pk != responsible.pk for person in found)
    ):
        found.append(responsible)
    return found


def issued(assignment_id: int) -> None:
    assignment = (
        AssetAssignment.objects.select_related("asset", "membership__user", "membership__company")
        .filter(pk=assignment_id, returned_on__isnull=True)
        .first()
    )
    if assignment is None or assignment.membership.status != Membership.Status.APPROVED:
        return
    asset = assignment.asset
    inbox.notify(
        [assignment.membership],
        ISSUED,
        title=lambda person: (
            _("You were given %(asset)s") % {"asset": f"{asset.number} {asset.name}"}
        ),
        body=lambda person: _("Check it and confirm in the app that you have it."),
        app_screen=MINE_SCREEN,
        target=asset,
        dedupe_key=f"assets.issued:{assignment.pk}",
    )


def issued_many(assignment_ids: list[int]) -> None:
    """Several things given to one person at once (a lab coat, a badge and a key): one notice
    naming them all, instead of one each."""
    rows = list(
        AssetAssignment.objects.select_related(
            "asset", "membership__user", "membership__company"
        ).filter(pk__in=assignment_ids, returned_on__isnull=True)
    )
    if not rows:
        return
    if len(rows) == 1:
        issued(rows[0].pk)
        return
    person = rows[0].membership
    if person.status != Membership.Status.APPROVED or any(
        row.membership_id != person.pk for row in rows
    ):
        return
    names = ", ".join(f"{row.asset.number} {row.asset.name}" for row in rows[:6])
    if len(rows) > 6:
        names = f"{names}…"
    inbox.notify(
        [person],
        ISSUED,
        title=lambda member: (
            ngettext(
                "You were given %(count)d thing: %(things)s",
                "You were given %(count)d things: %(things)s",
                len(rows),
            )
            % {"count": len(rows), "things": names}
        ),
        body=lambda member: _("Check them and confirm in the app that you have them."),
        app_screen=MINE_SCREEN,
        target=rows[0].asset,
        dedupe_key=f"assets.issued:{min(row.pk for row in rows)}:{len(rows)}",
    )


UPKEEP_TITLES = {
    "warranty": lambda asset, day: _("Warranty ends %(day)s: %(asset)s"),
    "service": lambda asset, day: _("Service due %(day)s: %(asset)s"),
    "verification": lambda asset, day: _("Instrument check due %(day)s: %(asset)s"),
    "insurance": lambda asset, day: _("Insurance ends %(day)s: %(asset)s"),
}
UPKEEP_BODIES = {
    "warranty": lambda: _("Anything to repair under the warranty? After this day it is paid."),
    "service": lambda: _("Book the service, then mark it done on the asset's page."),
    "verification": lambda: _(
        "An instrument without a valid check can't be used for the storage log: book the check "
        "and record it on the asset's page."
    ),
    "insurance": lambda: _("Renew the insurance, then put the new end date on the asset's page."),
}


def upkeep(asset: Asset, what: str, day: date, step: str) -> int:
    """`what` comes up on `day` (`step`: "soon" or "due")."""
    people = managers(asset)
    if not people:
        return 0
    title = UPKEEP_TITLES[what]
    body = UPKEEP_BODIES[what]
    sent = inbox.notify(
        people,
        UPKEEP,
        title=lambda person: title(asset, day) % {"day": _day(day), "asset": _where(asset)},
        body=lambda person: body(),
        url=f"/c/{asset.company_id}/assets/items/{asset.pk}",
        target=asset,
        severity="warning" if step == "due" else None,
        dedupe_key=f"assets.{what}:{asset.pk}:{day.isoformat()}:{step}",
    )
    return len(sent)


PERMIT = "assets.permit"


def permit_people(permit: Permit) -> list[Membership]:
    """`assets.manage` holders who see the permit's branch, and the one responsible for it."""
    found: list[Membership] = []
    for candidate in members_with_perm(permit.company, Perm.ASSETS_MANAGE).select_related(
        "user", "role", "company"
    ):
        seen = scope.branch_ids(candidate)
        if seen is None or (permit.branch_id is not None and permit.branch_id in seen):
            found.append(candidate)
    responsible = permit.responsible if permit.responsible_id else None
    if (
        responsible is not None
        and responsible.status == Membership.Status.APPROVED
        and all(person.pk != responsible.pk for person in found)
    ):
        found.append(responsible)
    return found


def permit(permit: Permit, step: str, today: date) -> int:
    """`step`: "soon" (within its warning days), "week" (7 days left) or "expired"."""
    people = permit_people(permit)
    if not people:
        return 0
    where = f"{permit.name} ({permit.branch.name})" if permit.branch_id else permit.name
    day = _day(permit.valid_until)

    def title(person):
        if step == "expired":
            return _("Expired %(day)s: %(permit)s") % {"day": day, "permit": where}
        return _("Ends %(day)s: %(permit)s") % {"day": day, "permit": where}

    def body(person):
        if step == "expired":
            return _("Working without it can mean a fine or a closed pharmacy: renew it today.")
        return _("Start the renewal now: the papers take time. Put the new end date on its card.")

    sent = inbox.notify(
        people,
        PERMIT,
        title=title,
        body=body,
        url=f"/c/{permit.company_id}/assets/permits",
        target=permit,
        severity="warning" if step != "soon" else None,
        dedupe_key=f"assets.permit:{permit.pk}:{permit.valid_until.isoformat()}:{step}",
    )
    return len(sent)
