"""What the Equipment page reads: who holds what (people-centred), what is in stock to give
out, the categories (with the pharmacy's suggestions not made yet), one person's equipment and
its history (Person 360's Equipment tab).

Branch scope (§2.6): the people of the viewer's branches (people who left and still hold
something included), what they hold whatever its branch, and the stock of those branches.
Values (what things cost) only for people who may read the asset register (assets.manage or
finance.view); a deduction's amount only with payroll.view.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Exists, OuterRef, Prefetch, Q

from apps.assets.models import Asset, AssetAssignment, AssetCategory, AssetFile
from apps.console.perms import AnyOf, holds
from apps.core.files import signed_url
from apps.hr import queries as hr_queries
from apps.lifecycle import integrations
from apps.lifecycle.equipment.services import SUGGESTIONS
from apps.lifecycle.models import Termination
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import branch_ref, photo_url

VALUES = AnyOf(Perm.ASSETS_MANAGE, Perm.FINANCE_VIEW)
LIVE = ~Q(status=Asset.Status.DISPOSED)
# Leaving "soon": an agreed last day within this many days.
SOON_DAYS = 14


def sees_values(viewer: Membership) -> bool:
    return holds(viewer, VALUES)


def _photo(file, *, user, company_id: int, check: str) -> str | None:
    if not file:
        return None
    return signed_url(file, user=user, company_id=company_id, check=check)


def _asset_photo(asset: Asset, user) -> str | None:
    photo = next(
        (row for row in asset.files.all() if row.kind == AssetFile.Kind.PHOTO and row.file), None
    )
    if photo is None:
        return None
    return _photo(
        photo.file, user=user, company_id=asset.company_id, check=f"assets.file:{photo.pk}"
    )


def _category(category: AssetCategory) -> dict:
    return {"id": category.pk, "name": category.name, "icon": category.icon, "kind": category.kind}


def _deductions(company, ids: set[int], viewer: Membership) -> dict[int, dict]:
    """{adjustment id: {id, amount (payroll.view), currency, status}} in one query."""
    if not ids or not integrations.payroll_on(company):
        return {}
    from apps.payroll.models import Adjustment

    sees_pay = viewer.has_perm(Perm.PAYROLL_VIEW)
    return {
        row.pk: {
            "id": row.pk,
            "amount": f"{row.amount:.2f}" if sees_pay else None,
            "currency": row.currency,
            "status": row.status,
        }
        for row in Adjustment.objects.filter(company=company, pk__in=ids)
    }


def item_of(
    assignment: AssetAssignment, *, viewer: Membership, values: bool, deductions: dict
) -> dict:
    asset = assignment.asset
    user = viewer.user
    return {
        "assignment_id": assignment.pk,
        "asset_id": asset.pk,
        "number": asset.number,
        "name": asset.name,
        "model": asset.model,
        "serial": asset.serial,
        "notes": asset.notes,
        "category": _category(asset.category),
        "branch": branch_ref(asset.branch),
        "issued_on": assignment.issued_on,
        "condition_out": assignment.condition_out or asset.condition,
        "note_out": assignment.note_out,
        "acknowledged_at": assignment.acknowledged_at,
        "photo_url": _photo(
            assignment.photo_out,
            user=user,
            company_id=asset.company_id,
            check=f"assets.handout:{assignment.pk}",
        )
        or _asset_photo(asset, user),
        "value": asset.cost if values else None,
        "deduction": deductions.get(assignment.deduction_id) if assignment.deduction_id else None,
        "may_write_off": asset.category.kind == AssetCategory.Kind.LOW_VALUE
        or viewer.has_perm(Perm.ASSETS_MANAGE),
    }


def _leavings(company, ids) -> dict[int, dict]:
    found = {}
    for row in Termination.objects.filter(
        company=company,
        membership_id__in=list(ids),
        status__in=(Termination.Status.REQUESTED, Termination.Status.AGREED),
    ).order_by("pk"):
        found[row.membership_id] = {
            "id": row.pk,
            "status": row.status,
            "day": row.last_day or row.wished_last_day,
        }
    return found


def _left_on(company, ids) -> dict[int, date]:
    found = {}
    for row in Termination.objects.filter(
        company=company, membership_id__in=list(ids), status=Termination.Status.COMPLETED
    ).order_by("left_on", "pk"):
        if row.left_on:
            found[row.membership_id] = row.left_on
    return found


def _person(member: Membership) -> dict:
    return {
        "id": member.pk,
        "name": str(member),
        "photo_url": photo_url(member),
        "position": member.position.name if member.position_id else None,
        "home_branch": branch_ref(member.home_branch),
        "status": member.status,
    }


def _open_assignments(company, member_ids) -> list[AssetAssignment]:
    return list(
        AssetAssignment.objects.filter(
            company=company, membership_id__in=list(member_ids), returned_on__isnull=True
        )
        .exclude(asset__status=Asset.Status.DISPOSED)
        .select_related("asset__category", "asset__branch", "asset__company")
        .prefetch_related(
            Prefetch("asset__files", queryset=AssetFile.objects.order_by("-created_at"))
        )
        .order_by("asset__category__order", "asset__name", "pk")
    )


def people(company, viewer: Membership, *, branch: int | None = None) -> dict:
    """Every current person in the viewer's branches with what they hold, and the people who
    left still holding something. Totals for the strip on top."""
    branch_ids = scope.branch_ids(viewer)
    if branch is not None:
        branch_ids = [branch]
    today = hr_queries.today(company)
    current = list(
        hr_queries.people(company, branch_ids=branch_ids)
        .select_related(*RELATIONS)
        .order_by("first_name", "last_name", "pk")
    )
    seen = {member.pk for member in current}
    gone = [
        member
        for member in hr_queries.people(company, branch_ids=branch_ids, statuses=hr_queries.GONE)
        .filter(asset_assignments__returned_on__isnull=True)
        .distinct()
        .select_related(*RELATIONS)
        .order_by("first_name", "last_name", "pk")
        if member.pk not in seen
    ]
    rows = holder_rows(company, viewer, current + gone, today)
    totals = {"people": 0, "items": 0, "unconfirmed": 0, "to_return": 0, "value": Decimal(0)}
    for row in rows:
        items = row["items"]
        if not items:
            continue
        totals["people"] += 1
        totals["items"] += len(items)
        totals["unconfirmed"] += row["unconfirmed"]
        if row["overdue"] or row["leaving"]:
            totals["to_return"] += len(items)
        totals["value"] += sum((item["value"] or Decimal(0) for item in items), Decimal(0))
    values = sees_values(viewer)
    stock = stock_rows(company, viewer, status="stock").count()
    return {
        "today": today,
        "people": rows,
        "totals": {**totals, "value": totals["value"] if values else None, "in_stock": stock},
        "can": can(company, viewer),
    }


RELATIONS = ("user", "position", "home_branch")


def holder_rows(company, viewer: Membership, members: list[Membership], today: date) -> list[dict]:
    """Each person with what they hold now (one query for all of their hand-outs)."""
    ids = [member.pk for member in members]
    held = _open_assignments(company, ids)
    values = sees_values(viewer)
    deductions = _deductions(
        company, {row.deduction_id for row in held if row.deduction_id}, viewer
    )
    by_person: dict[int, list[AssetAssignment]] = defaultdict(list)
    for row in held:
        by_person[row.membership_id].append(row)
    leavings = _leavings(company, ids)
    left = _left_on(company, [member.pk for member in members if member.status in hr_queries.GONE])
    rows = []
    for member in members:
        items = [
            item_of(row, viewer=viewer, values=values, deductions=deductions)
            for row in by_person.get(member.pk, [])
        ]
        gone_now = member.status in hr_queries.GONE
        leaving = leavings.get(member.pk)
        soon = bool(
            leaving
            and leaving["day"] is not None
            and leaving["day"] <= today + timedelta(days=SOON_DAYS)
        )
        value = sum((item["value"] or Decimal(0) for item in items), Decimal(0))
        rows.append(
            {
                "person": _person(member),
                "leaving": leaving,
                "left_on": left.get(member.pk) if gone_now else None,
                "items": items,
                "value": value if values else None,
                "unconfirmed": sum(1 for item in items if item["acknowledged_at"] is None),
                "overdue": len(items) if gone_now else 0,
                "leaving_soon": soon and bool(items),
            }
        )
    return rows


def holder(company, viewer: Membership, member: Membership) -> dict:
    """One person's row (after a change, and on their Person 360 tab)."""
    member = Membership.objects.select_related(*RELATIONS).get(pk=member.pk)
    return holder_rows(company, viewer, [member], hr_queries.today(company))[0]


def can(company, viewer: Membership) -> dict:
    return {
        "values": sees_values(viewer),
        "devices": viewer.has_perm(Perm.ASSETS_MANAGE),
        "deduct": integrations.payroll_on(company),
        "pay": viewer.has_perm(Perm.PAYROLL_VIEW),
        "register": viewer.has_perm(Perm.ASSETS_MANAGE),
    }


def personal_categories(company):
    """The categories of things people are given: low-value ones (uniforms, keys), the
    equipment suggestions (phones, tablets, scanners), and any category something was ever
    given out of (the manager's laptop, the courier's scooter). Never the register's fridges,
    shelves or renovation."""
    from apps.lifecycle.equipment.services import SUGGESTION_CODES

    handed = AssetAssignment.objects.filter(company=company, asset__category=OuterRef("pk"))
    return (
        AssetCategory.objects.for_company(company)
        .exclude(kind=AssetCategory.Kind.INTANGIBLE)
        .filter(
            Q(kind=AssetCategory.Kind.LOW_VALUE)
            | Q(system_code__in=list(SUGGESTION_CODES))
            | Exists(handed)
        )
    )


def stock_rows(company, viewer: Membership, *, status: str = "stock", branch: int | None = None):
    """Things people are given (`personal_categories`) in the viewer's branches: in stock
    (nobody holds them, not under repair), given out, or all that are still the company's."""
    branch_ids = scope.branch_ids(viewer)
    rows = Asset.objects.for_company(company).filter(
        LIVE, category__in=personal_categories(company)
    )
    if branch_ids is not None:
        rows = rows.filter(branch_id__in=branch_ids)
    if branch is not None:
        rows = rows.filter(branch_id=branch)
    if status == "stock":
        rows = rows.filter(custodian__isnull=True).exclude(status=Asset.Status.REPAIR)
    elif status == "out":
        rows = rows.filter(custodian__isnull=False)
    return rows


def items(
    company, viewer: Membership, *, status: str = "stock", branch: int | None = None
) -> list[dict]:
    values = sees_values(viewer)
    open_by_asset = {}
    rows = list(
        stock_rows(company, viewer, status=status, branch=branch)
        .select_related("category", "branch", "custodian__user", "company")
        .prefetch_related(Prefetch("files", queryset=AssetFile.objects.order_by("-created_at")))
        .order_by("category__order", "category__name", "name", "number")[:2000]
    )
    held = [row.pk for row in rows if row.custodian_id]
    if held:
        open_by_asset = {
            row.asset_id: row
            for row in AssetAssignment.objects.filter(asset_id__in=held, returned_on__isnull=True)
        }
    user = viewer.user
    out = []
    for asset in rows:
        assignment = open_by_asset.get(asset.pk)
        out.append(
            {
                "id": asset.pk,
                "number": asset.number,
                "name": asset.name,
                "model": asset.model,
                "serial": asset.serial,
                "notes": asset.notes,
                "category": _category(asset.category),
                "branch": branch_ref(asset.branch),
                "status": asset.status,
                "condition": asset.condition,
                "value": asset.cost if values else None,
                "holder": {
                    "id": asset.custodian.pk,
                    "name": str(asset.custodian),
                    "photo_url": photo_url(asset.custodian),
                }
                if asset.custodian_id
                else None,
                "issued_on": assignment.issued_on if assignment else None,
                "acknowledged_at": assignment.acknowledged_at if assignment else None,
                "photo_url": _asset_photo(asset, user),
            }
        )
    return out


def categories(company, viewer: Membership) -> dict:
    """The company's categories with how many are in stock and out, and the pharmacy's
    suggestions it has no category for yet (by name, in the company's language)."""
    from django.utils import translation

    branch_ids = scope.branch_ids(viewer)
    live = Q(assets__status__in=[s for s in Asset.Status.values if s != Asset.Status.DISPOSED])
    if branch_ids is not None:
        live &= Q(assets__branch_id__in=branch_ids)
    rows = (
        personal_categories(company)
        .filter(is_active=True)
        .annotate(
            stock=Count(
                "assets",
                filter=live
                & Q(assets__custodian__isnull=True)
                & ~Q(assets__status=Asset.Status.REPAIR),
            ),
            out=Count("assets", filter=live & Q(assets__custodian__isnull=False)),
        )
        .order_by("order", "name")
    )
    names = {row.name.lower() for row in rows}
    codes = set(
        AssetCategory.objects.for_company(company)
        .exclude(system_code="")
        .values_list("system_code", flat=True)
    )
    devices = viewer.has_perm(Perm.ASSETS_MANAGE)
    with translation.override(company.default_language):
        suggestions = [
            {"key": key, "name": str(label), "kind": kind, "icon": icon}
            for key, label, kind, icon, _life, _group in SUGGESTIONS
            if key not in codes
            and str(label).lower() not in names
            and (kind == AssetCategory.Kind.LOW_VALUE or devices)
        ]
    return {
        "categories": [
            {
                **_category(row),
                "stock": row.stock,
                "out": row.out,
                "may_add": row.kind == AssetCategory.Kind.LOW_VALUE or devices,
            }
            for row in rows
        ],
        "suggestions": suggestions,
    }


def history(company, viewer: Membership, member: Membership) -> list[dict]:
    """What the person was given and gave back (or lost), newest first."""
    values = sees_values(viewer)
    rows = list(
        AssetAssignment.objects.filter(company=company, membership=member)
        .select_related("asset__category", "asset__branch", "asset__company", "received_by")
        .prefetch_related(
            Prefetch("asset__files", queryset=AssetFile.objects.order_by("-created_at"))
        )
        .order_by("-issued_on", "-pk")[:200]
    )
    deductions = _deductions(
        company, {row.deduction_id for row in rows if row.deduction_id}, viewer
    )
    user = viewer.user
    out = []
    for row in rows:
        asset = row.asset
        item = item_of(row, viewer=viewer, values=values, deductions=deductions)
        out.append(
            {
                **item,
                "returned_on": row.returned_on,
                "condition_in": row.condition_in,
                "note_in": row.note_in,
                "photo_in_url": _photo(
                    row.photo_in,
                    user=user,
                    company_id=asset.company_id,
                    check=f"assets.handout:{row.pk}",
                ),
                "outcome": outcome(row),
            }
        )
    return out


def outcome(row: AssetAssignment) -> str:
    """How a hand-out ended: held (still), returned, lost (written off as not handed back) or
    written_off (came back damaged and written off, or disposed of while they held it).
    `take_back` always notes the condition it came back in; a disposal closing the hand-out
    leaves it empty."""
    asset = row.asset
    if row.returned_on is None:
        return "held"
    disposed = asset.status == Asset.Status.DISPOSED and asset.disposed_on is not None
    if not row.condition_in:
        return "lost" if disposed and asset.disposal == Asset.Disposal.LOST else "written_off"
    written_off = disposed and asset.disposal == Asset.Disposal.WRITTEN_OFF
    if written_off and asset.disposed_on == row.returned_on:
        return "written_off"  # it came back damaged and was written off with it
    return "returned"
