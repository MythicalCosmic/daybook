"""Who hears about assets, through the inbox (`apps.inbox.services.notify`).

To the person (the staff bot, with a way into the app): something was given to them, to
confirm. To the people who manage assets (`assets.manage` who see the asset's branch, and the
person accountable for it): a warranty, an official instrument check, insurance or a service
coming up or overdue. Once per asset, date and step: `dedupe_key` holds all three.
"""

from datetime import date

from django.utils.translation import gettext as _

from apps.assets.models import Asset, AssetAssignment
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
