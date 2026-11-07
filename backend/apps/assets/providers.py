"""What fixed assets give the shared registries: the offboarding step, "Get started", the
command palette, the company calendar, private files and the Excel register."""

from datetime import date, timedelta

from django.db.models import Q
from django.utils.translation import gettext as _

from apps.assets import posting, queries
from apps.assets.models import Asset, AssetCategory, AssetFile, Permit
from apps.console.perms import AnyOf, holds
from apps.console.registry import CalendarItem, FieldSpec, OffboardStep, SearchHit
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm

READ = AnyOf(Perm.ASSETS_MANAGE, Perm.FINANCE_VIEW)
MANAGE = Perm.ASSETS_MANAGE
CHOICE_RETURNED, CHOICE_LOST, CHOICE_KEEP = "returned", "lost", "keep"


def _branch_ids(member: Membership) -> list[int] | None:
    return scope.branch_ids(member)


def _url(asset: Asset) -> str:
    return f"/c/{asset.company_id}/assets/items/{asset.pk}"


# Offboarding -----------------------------------------------------------------------------------


def offboard_preview(membership: Membership) -> OffboardStep:
    """What the leaver holds, each with a choice: handed back, not handed back (written off as
    lost), or left with them for now."""
    held = list(
        Asset.objects.for_company(membership.company)
        .filter(custodian=membership)
        .exclude(status=Asset.Status.DISPOSED)
        .order_by("number")
    )
    if not held:
        return OffboardStep(
            lines=[_("Holds no company equipment.")], blockers=[], fields=[], defaults={}
        )
    lines = [f"{asset.number} {asset.name}" for asset in held]
    choices = (
        (CHOICE_RETURNED, _("Handed back")),
        (CHOICE_LOST, _("Not handed back: write it off as lost")),
        (CHOICE_KEEP, _("Leave it with them for now")),
    )
    fields = [
        FieldSpec(
            name=f"asset_{asset.pk}",
            label=f"{asset.number} {asset.name}",
            kind="choice",
            required=True,
            choices=choices,
        )
        for asset in held
    ]
    return OffboardStep(
        lines=lines,
        blockers=[],
        fields=fields,
        defaults={f"asset_{asset.pk}": CHOICE_RETURNED for asset in held},
    )


def on_member_left(membership: Membership, *, terminated_on: date | None, details: dict, by):
    """Apply the step's answers: take back what was handed back, write off what wasn't."""
    from apps.assets import services

    answers = (details or {}).get("assets") or {}
    day = terminated_on or posting.local_today(membership.company)
    for asset in Asset.objects.for_company(membership.company).filter(custodian=membership):
        answer = answers.get(f"asset_{asset.pk}", CHOICE_KEEP)
        if answer == CHOICE_RETURNED:
            services.take_back(asset, by=by, on=day, note=_("Handed back when they left."))
        elif answer == CHOICE_LOST:
            # Posted months are history: a last day recorded late (before them) is written off
            # on the first day the books allow, or `dispose` refuses and nothing is written off.
            posted = asset.entries.order_by("-month").values_list("month", flat=True).first()
            services.dispose(
                asset,
                by=by,
                on=max(day, posted) if posted else day,
                kind=Asset.Disposal.LOST,
                reason=_("Not handed back when %(person)s left.") % {"person": membership},
            )


# The morning brief (the owner bot's /today) -----------------------------------------------------


def brief_section(company, day: date, now, branch_ids: list[int] | None) -> dict | None:
    """What the equipment needs today: services and instrument checks due or overdue, and
    warranties and insurance ending within the warning days. Nothing when all is well."""
    from apps.assets import conf

    ahead = day + timedelta(days=conf.get_settings(company).remind_days)
    live = queries.scoped(company, branch_ids=branch_ids).exclude(status=Asset.Status.DISPOSED)
    counts = (
        (
            _("Services due: %(count)d"),
            live.exclude(status=Asset.Status.SUSPENDED).filter(next_service_on__lte=day),
        ),
        (_("Instrument checks due: %(count)d"), live.filter(next_verification_on__lte=day)),
        (
            _("Warranties ending soon: %(count)d"),
            live.filter(warranty_until__gte=day, warranty_until__lte=ahead),
        ),
        (
            _("Insurance ending soon: %(count)d"),
            live.filter(Q(insurance_until__gte=day) & Q(insurance_until__lte=ahead)),
        ),
    )
    lines = [text % {"count": count} for text, rows in counts if (count := rows.count())]
    if not lines:
        return None
    return {"title": _("Equipment"), "lines": lines}


# Get started ------------------------------------------------------------------------------------


def register_done(company) -> bool:
    return Asset.objects.for_company(company).exists()


# The command palette -----------------------------------------------------------------------------


def search(member: Membership, q: str, limit: int) -> list[SearchHit]:
    rows = queries.register(member.company, branch_ids=_branch_ids(member), q=q)[:limit]
    return [
        SearchHit(
            type="assets.asset",
            id=asset.pk,
            title=f"{asset.number} {asset.name}",
            subtitle=" · ".join(
                part
                for part in (asset.category.name, asset.branch.name if asset.branch else "")
                if part
            ),
            url=_url(asset),
        )
        for asset in rows
    ]


# The company calendar ----------------------------------------------------------------------------

CALENDAR_TITLES = {
    "service": lambda asset: _("Service: %(asset)s"),
    "verification": lambda asset: _("Instrument check: %(asset)s"),
    "warranty": lambda asset: _("Warranty ends: %(asset)s"),
    "insurance": lambda asset: _("Insurance ends: %(asset)s"),
}
CALENDAR_COLORS = {
    "service": "chart-3",
    "verification": "warning",
    "warranty": "chart-5",
    "insurance": "chart-7",
}


def calendar_events(company, start: date, end: date, member: Membership) -> list[CalendarItem]:
    items = []
    rows = (
        queries.scoped(company, branch_ids=_branch_ids(member))
        .exclude(status=Asset.Status.DISPOSED)
        .select_related("branch")
    )
    for asset in rows:
        for what, day in (
            ("service", asset.next_service_on),
            ("verification", asset.next_verification_on),
            ("warranty", asset.warranty_until),
            ("insurance", asset.insurance_until),
        ):
            if day is None or not start <= day <= end:
                continue
            items.append(
                CalendarItem(
                    id=f"{what}:{asset.pk}",
                    kind=f"assets.{what}",
                    title=CALENDAR_TITLES[what](asset) % {"asset": f"{asset.number} {asset.name}"},
                    start=day,
                    end=None,
                    all_day=True,
                    color=CALENDAR_COLORS[what],
                    url=_url(asset),
                )
            )
    return items


# Files ----------------------------------------------------------------------------------------


def may_open_file(user, company_id: int, file_id: int) -> bool:
    """`assets.file`: whoever may read the register in the asset's branch, and the person
    holding the asset (its photos only)."""
    row = (
        AssetFile.objects.filter(company_id=company_id, pk=file_id).select_related("asset").first()
    )
    if row is None:
        return False
    viewer = (
        Membership.objects.filter(
            company_id=company_id, user=user, status=Membership.Status.APPROVED
        )
        .select_related("role", "company")
        .first()
    )
    if viewer is None:
        return False
    asset = row.asset
    if asset.custodian_id == viewer.pk and row.kind == AssetFile.Kind.PHOTO:
        return True
    if not holds(viewer, READ):
        return False
    seen = scope.branch_ids(viewer)
    return seen is None or (asset.branch_id is not None and asset.branch_id in seen)


# The Excel register ----------------------------------------------------------------------------

REGISTER_COLUMNS = (
    ("number", _("Inventory number")),
    ("name", _("Name")),
    ("category", _("Category")),
    ("kind", _("Kind")),
    ("branch", _("Branch")),
    ("status", _("Status")),
    ("condition", _("Condition")),
    ("serial", _("Serial number")),
    ("purchased_on", _("Bought"), "date"),
    ("in_service_on", _("In service from"), "date"),
    ("cost", _("Cost"), "money"),
    ("accumulated", _("Depreciation so far"), "money"),
    ("book_value", _("Book value"), "money"),
    ("monthly", _("Last month's depreciation"), "money"),
    ("life_months", _("Useful life, months")),
    ("method", _("Method")),
    ("custodian", _("Held by")),
    ("responsible", _("Accountable")),
    ("warranty_until", _("Warranty until"), "date"),
    ("next_service_on", _("Next service"), "date"),
    ("next_verification_on", _("Next instrument check"), "date"),
)


def register_rows(member: Membership, params: dict):
    rows = queries.register(
        member.company,
        branch_ids=_branch_ids(member),
        include_disposed=bool(params.get("disposed")),
    )
    for asset in rows:
        yield {
            "number": asset.number,
            "name": asset.name,
            "category": asset.category.name,
            "kind": AssetCategory.Kind(asset.category.kind).label,
            "branch": asset.branch.name if asset.branch else "",
            "status": Asset.Status(asset.status).label,
            "condition": Asset.Condition(asset.condition).label,
            "serial": asset.serial,
            "purchased_on": asset.purchased_on,
            "in_service_on": asset.in_service_on,
            "cost": asset.cost + asset.added,
            "accumulated": asset.accumulated + asset.written_down,
            "book_value": asset.book,
            "monthly": asset.last_amount,
            "life_months": asset.life_months or "",
            "method": asset.get_method_display(),
            "custodian": str(asset.custodian) if asset.custodian else "",
            "responsible": str(asset.responsible) if asset.responsible else "",
            "warranty_until": asset.warranty_until,
            "next_service_on": asset.next_service_on,
            "next_verification_on": asset.next_verification_on,
        }


def may_open_permit(user, company_id: int, permit_id: int) -> bool:
    """`assets.permit`: whoever may read the register in the permit's branch."""
    permit = Permit.objects.filter(company_id=company_id, pk=permit_id).first()
    viewer = (
        Membership.objects.filter(
            company_id=company_id, user=user, status=Membership.Status.APPROVED
        )
        .select_related("role", "company")
        .first()
    )
    if permit is None or viewer is None or not holds(viewer, READ):
        return False
    seen = scope.branch_ids(viewer)
    return seen is None or (permit.branch_id is not None and permit.branch_id in seen)
