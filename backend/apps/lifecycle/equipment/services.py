"""What the Equipment page changes, through the assets services (`apps.assets.services`: issue,
take back, dispose, create), never around them.

- `issue_many`: one or more things to one person in one go, with one photo of them and one
  notice in the staff bot ("You were given 3 things: …"); they confirm in the app.
- `give_back`: it came back (its condition, a photo, a note; damaged: optionally written off),
  or it is lost (written off as lost); either way a deduction can be proposed with it.
- `propose_deduction`: a fine on this month's pay through payroll (`payroll.services.
  propose_fine`, via `apps.lifecycle.integrations`), linked to the hand-out; payroll's managers
  approve it as usual. Only while the person still works here (payroll's rule).
- `add_items`: low-value things to give out ("10 lab coats" become ten numbered items, a size
  as their note, no inventory number to type), or one device with its serial and cost.
- `add_category`: a category of the company, or one of the pharmacy's suggestions.

Who: `assets.manage` or `hr.manage` (the view checks). A device (a fixed asset: it depreciates
in Finance) is added and written off only with `assets.manage`. Every change is audited on the
person too (`EquipmentAction`) and bumps `lifecycle.equipment`.
"""

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import partial

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.assets import notify as asset_notices
from apps.assets import services as assets
from apps.assets.models import Asset, AssetAssignment, AssetCategory
from apps.audit import services as audit
from apps.console import pulse
from apps.console.perms import AnyOf
from apps.core.exceptions import DomainError
from apps.hr import queries as hr_queries
from apps.lifecycle import integrations
from apps.lifecycle.equipment.audit_actions import EquipmentAction
from apps.members.models import Membership
from apps.members.permissions import Perm

PULSE = "lifecycle.equipment"
# Who runs the equipment: asset managers and HR managers.
MANAGE = AnyOf(Perm.ASSETS_MANAGE, Perm.HR_MANAGE)
MAX_ITEMS = 100  # at most this many made in one go ("100 badges")
MAX_ISSUE = 30  # at most this many given in one go
LOW = AssetCategory.Kind.LOW_VALUE
RETURNED, LOST = "returned", "lost"

# What a pharmacy gives its people (`add_category(suggestion=…)`): key, name, kind, icon, and
# for devices their useful life (months) and Tax Code group.
SUGGESTIONS = (
    ("lab_coat", gettext_lazy("Lab coats"), LOW, "shirt", None, ""),
    ("badge", gettext_lazy("Badges"), LOW, "id-card", None, ""),
    ("key", gettext_lazy("Keys"), LOW, "key-round", None, ""),
    ("cash_key", gettext_lazy("Cash-box keys"), LOW, "key-square", None, ""),
    ("phone", gettext_lazy("Phones"), AssetCategory.Kind.FIXED, "smartphone", 36, "V"),
    ("tablet", gettext_lazy("Tablets"), AssetCategory.Kind.FIXED, "tablet", 36, "V"),
    (
        "scanner",
        gettext_lazy("Barcode scanners"),
        AssetCategory.Kind.FIXED,
        "scan-barcode",
        60,
        "III",
    ),
)
SUGGESTION_CODES = {row[0]: row for row in SUGGESTIONS}


def bump(company_id: int) -> None:
    transaction.on_commit(partial(pulse.bump, company_id, PULSE, "assets"))


def _audit(action: str, person: Membership, by: Membership, **details) -> None:
    audit.record(
        action,
        company_id=person.company_id,
        actor=by.user if by is not None else None,
        target=person,
        required_perm=Perm.HR_VIEW,
        **details,
    )


def _today(company) -> date:
    return hr_queries.today(company)


def _day(company, on: date | None) -> date:
    day = on or _today(company)
    if day > _today(company):
        raise DomainError(_("The day can't be in the future."))
    return day


def _money(value, *, name: str) -> Decimal:
    try:
        amount = Decimal(str(value).replace(" ", "").replace(",", ".")).quantize(Decimal("0.01"))
    except InvalidOperation, ValueError, TypeError:
        raise DomainError(_("%(field)s: give an amount.") % {"field": name}) from None
    if not amount.is_finite() or amount < 0:
        raise DomainError(_("%(field)s: give an amount above zero.") % {"field": name})
    return amount


def may_add_devices(member: Membership) -> bool:
    """Devices are fixed assets (they depreciate in Finance): asset managers add them."""
    return member.has_perm(Perm.ASSETS_MANAGE)


def may_write_off(member: Membership, asset: Asset) -> bool:
    """A low-value thing (a lab coat, a key) by whoever runs the equipment; a device only by an
    asset manager (its value leaves the books)."""
    return asset.category.kind == LOW or member.has_perm(Perm.ASSETS_MANAGE)


# Giving out ----------------------------------------------------------------------------------


@transaction.atomic
def issue_many(
    company,
    *,
    by: Membership,
    person: Membership,
    items: list[Asset],
    on: date | None = None,
    condition: str = "",
    note: str = "",
    photo=None,
) -> list[AssetAssignment]:
    """Give `items` to `person` in one go: one photo for all of them (stored once), one notice.
    Nothing is given when one of them can't be (somebody holds it, it was disposed of)."""
    if not items:
        raise DomainError(_("Pick what to give."))
    if len(items) > MAX_ISSUE:
        raise DomainError(_("Give at most %(count)s things at a time.") % {"count": MAX_ISSUE})
    if person.company_id != company.pk or person.status != Membership.Status.APPROVED:
        raise DomainError(_("%(person)s isn't an active member.") % {"person": person})
    day = _day(company, on)
    stored = assets.handout_photo(photo) if photo is not None else None
    made: list[AssetAssignment] = []
    for asset in sorted(items, key=lambda item: item.number):
        if asset.company_id != company.pk:
            raise DomainError(_("Pick something of this company."))
        assignment = assets.issue(
            asset,
            by=by,
            membership=person,
            on=day,
            condition=condition,
            note=note,
            photo=stored,
            notify=False,
        )
        if stored is not None and not isinstance(stored, str):
            stored = assignment.photo_out.name  # the rest share the stored file
        made.append(assignment)
    ids = [row.pk for row in made]
    transaction.on_commit(partial(asset_notices.issued_many, ids))
    _audit(
        EquipmentAction.ISSUED,
        person,
        by,
        items=[asset.number for asset in items][:30],
        on=day.isoformat(),
        photo=bool(photo),
    )
    bump(company.pk)
    return made


# Coming back ---------------------------------------------------------------------------------


@transaction.atomic
def give_back(
    assignment: AssetAssignment,
    *,
    by: Membership,
    outcome: str = RETURNED,
    on: date | None = None,
    condition: str = "",
    note: str = "",
    photo=None,
    write_off: bool = False,
    deduction=None,
    reason: str = "",
) -> AssetAssignment:
    """It came back (`returned`, in `condition`; a damaged one can be written off at once), or
    it didn't (`lost`: written off as lost). `deduction` (an amount) also proposes a fine on
    the person's pay for it, with `reason`."""
    assignment = (
        AssetAssignment.objects.select_for_update(of=("self",))
        .select_related("asset__category", "asset__company", "membership__company", "company")
        .get(pk=assignment.pk)
    )
    if assignment.returned_on is not None:
        raise DomainError(_("It was already handed back."))
    asset, person = assignment.asset, assignment.membership
    company = asset.company
    day = _day(company, on)
    note = " ".join(str(note or "").split())[:300]
    if outcome not in (RETURNED, LOST):
        raise DomainError(_("Say whether it came back or was lost."))
    if deduction not in (None, ""):
        # Checked first: a refusal (they have left, payroll is off) changes nothing.
        _check_deduction(person, _money(deduction, name=_("Deduction")))
    if outcome == LOST:
        if not may_write_off(by, asset):
            raise PermissionDenied(_("Only people who manage assets write off a device."))
        why = note or _("Not handed back by %(person)s.") % {"person": person}
        assets.dispose(
            asset, by=by, on=_disposal_day(asset, day), kind=Asset.Disposal.LOST, reason=why
        )
        assignment.refresh_from_db()
        _audit(EquipmentAction.LOST, person, by, item=asset.number, on=day.isoformat())
    else:
        if write_off and condition != Asset.Condition.DAMAGED:
            raise DomainError(_("Only something damaged is written off when it comes back."))
        if write_off and not may_write_off(by, asset):
            raise PermissionDenied(_("Only people who manage assets write off a device."))
        stored = assets.handout_photo(photo) if photo is not None else None
        assets.take_back(asset, by=by, on=day, condition=condition, note=note, photo=stored)
        assignment.refresh_from_db()
        _audit(
            EquipmentAction.RETURNED,
            person,
            by,
            item=asset.number,
            on=day.isoformat(),
            condition=assignment.condition_in,
        )
        if write_off:
            assets.dispose(
                asset,
                by=by,
                on=_disposal_day(asset, day),
                kind=Asset.Disposal.WRITTEN_OFF,
                reason=note or _("Came back damaged from %(person)s.") % {"person": person},
            )
            _audit(EquipmentAction.WRITTEN_OFF, person, by, item=asset.number)
    if deduction not in (None, ""):
        propose_deduction(assignment, by=by, amount=deduction, reason=reason)
    bump(company.pk)
    return assignment


def _disposal_day(asset: Asset, day: date) -> date:
    """The disposal can't come before a posted month of its depreciation: the first day the
    books allow (a fixed asset only; a low-value one has none)."""
    posted = asset.entries.order_by("-month").values_list("month", flat=True).first()
    return max(day, posted) if posted else day


def _check_deduction(person: Membership, amount: Decimal) -> None:
    if not integrations.payroll_on(person.company):
        raise DomainError(_("Payroll is off for this company, so nothing can be deducted."))
    if person.status not in hr_queries.CURRENT:
        raise DomainError(
            _("%(person)s has left: a deduction is proposed before the last day.")
            % {"person": person}
        )
    if amount <= 0:
        raise DomainError(_("Deduction: give an amount above zero."))


@transaction.atomic
def propose_deduction(
    assignment: AssetAssignment, *, by: Membership, amount, reason: str = ""
) -> AssetAssignment:
    """A fine on the person's pay for what was lost or damaged, waiting for payroll's approval.
    One per hand-out (another only once payroll turned the first down)."""
    assignment = (
        AssetAssignment.objects.select_for_update(of=("self",))
        .select_related("asset", "membership__company", "membership__role")
        .get(pk=assignment.pk)
    )
    person, asset = assignment.membership, assignment.asset
    value = _money(amount, name=_("Deduction"))
    _check_deduction(person, value)
    open_one = integrations.fine_summary(person.company, assignment.deduction_id)
    if open_one is not None and open_one["status"] in ("proposed", "approved"):
        raise DomainError(_("A deduction for it is already with payroll."))
    reason = " ".join(str(reason or "").split())[:300] or (
        _("Equipment not handed back or damaged: %(item)s")
        % {"item": f"{asset.number} {asset.name}"}
    )
    fine = integrations.propose_fine(person, by=by, amount=value, reason=reason, source="manual")
    assignment = assets.link_deduction(assignment, by=by, deduction_id=fine.pk)
    _audit(EquipmentAction.DEDUCTION, person, by, item=asset.number, deduction=fine.pk)
    bump(person.company_id)
    return assignment


# Adding things to give out ---------------------------------------------------------------------

NUMBERED = re.compile(r"^(?P<base>.*?)\s*№\s*(?P<n>\d+)$")


def _next_index(company, base: str) -> int:
    """The number after the highest "<base> №N" the company has (so a second batch of lab coats
    continues where the first ended)."""
    top = 0
    for name in (
        Asset.objects.for_company(company)
        .filter(name__istartswith=base)
        .values_list("name", flat=True)
    ):
        found = NUMBERED.match(name)
        if found and found["base"].strip().lower() == base.lower():
            top = max(top, int(found["n"]))
    return top + 1


@transaction.atomic
def add_items(
    company,
    *,
    by: Membership,
    category: AssetCategory,
    name: str,
    quantity: int = 1,
    branch=None,
    note: str = "",
    cost=None,
    serial: str = "",
    model: str = "",
) -> list[Asset]:
    """Things to give out. Low-value ones in any number: more than one become "<name> №1…"
    (continuing the company's numbering), each with its own inventory number and `note` (a
    size). A device (a fixed asset) one at a time, with its cost, serial and model."""
    if category.company_id != company.pk:
        raise DomainError(_("Pick a category of this company."))
    name = " ".join(str(name or "").split())[:110]
    if not name:
        raise DomainError(_("Say what it is."))
    try:
        quantity = int(quantity)
    except TypeError, ValueError:
        raise DomainError(_("Give how many.")) from None
    if not 1 <= quantity <= MAX_ITEMS:
        raise DomainError(_("Add 1 to %(count)s at a time.") % {"count": MAX_ITEMS})
    device = category.kind != LOW
    if device and not may_add_devices(by):
        raise PermissionDenied(_("Devices are added by people who manage assets."))
    if device and quantity != 1:
        raise DomainError(_("Add devices one at a time, each with its serial number."))
    price = _money(cost, name=_("Cost")) if cost not in (None, "") else Decimal(0)
    if device and price <= 0:
        raise DomainError(_("Give what it cost."))
    today = _today(company)
    fields = {"branch": branch, "notes": " ".join(str(note or "").split())[:500]}
    if device:
        fields |= {
            "serial": " ".join(str(serial or "").split())[:64],
            "model": " ".join(str(model or "").split())[:80],
            "purchased_on": today,
            "in_service_on": today,
        }
    first = _next_index(company, name) if quantity > 1 else None
    made = []
    for index in range(quantity):
        label = f"{name} №{first + index}" if first is not None else name
        made.append(
            assets.create_asset(company, by=by, category=category, name=label, cost=price, **fields)
        )
    _audit(
        EquipmentAction.ADDED,
        by,
        by,
        category=category.name,
        count=quantity,
        items=[asset.number for asset in made][:30],
    )
    bump(company.pk)
    return made


@transaction.atomic
def add_category(
    company, *, by: Membership, suggestion: str = "", name: str = "", kind: str = LOW, icon=""
) -> AssetCategory:
    """One of the pharmacy's suggestions (in the company's language) or a category of its own.
    A device category (a fixed asset kind) only for asset managers."""
    if suggestion:
        if suggestion not in SUGGESTION_CODES:
            raise DomainError(_("Pick one of the suggestions."))
        _key, label, kind, icon, life, group = SUGGESTION_CODES[suggestion]
        from django.utils import translation

        with translation.override(company.default_language):
            name = str(label)
        fields = {"kind": kind, "icon": icon}
        if kind != LOW:
            from apps.assets.defaults import TAX_GROUPS

            fields |= {"life_months": life, "tax_group": group, "tax_rate": TAX_GROUPS[group][0]}
    else:
        if kind not in (LOW, AssetCategory.Kind.FIXED):
            raise DomainError(_("Pick a kind from the list."))
        fields = {"kind": kind, "icon": str(icon or "")[:40]}
        if kind != LOW:
            fields["life_months"] = 36
    if fields["kind"] != LOW and not may_add_devices(by):
        raise PermissionDenied(_("Devices are added by people who manage assets."))
    rows = AssetCategory.objects.for_company(company)
    existing = (rows.filter(system_code=suggestion).first() if suggestion else None) or rows.filter(
        name__iexact=name.strip()
    ).first()
    if existing is not None:
        return existing
    category = assets.create_category(company, by=by, name=name, **fields)
    if suggestion:
        # Remembered by its key, so a renamed "Lab coats" is never suggested again.
        AssetCategory.objects.filter(pk=category.pk).update(system_code=suggestion)
        category.system_code = suggestion
    bump(company.pk)
    return category
