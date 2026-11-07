"""What stock gives the shared registries: the command palette, "Needs you", sidebar badges,
the morning brief, Excel exports, private files, "Get started", the portfolio card and "Copy
setup from another company". Every provider applies the caller's branch scope."""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Q
from django.utils.translation import gettext as _

from apps.console.perms import AllOf, AnyOf, holds
from apps.console.registry import QueueAction, QueueItem, SearchHit
from apps.core.money import format_money
from apps.inventory import conf, engine, queries
from apps.inventory.models import (
    GoodsReceipt,
    PricingRule,
    Product,
    ProductCategory,
    RecallNotice,
    RxRecord,
    StockBatch,
    StockMovement,
    StockTransfer,
    SupplierProfile,
    WriteOff,
    WriteOffFile,
)
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm

READ = AnyOf(Perm.SALES_VIEW, Perm.STOCK_MANAGE, Perm.STOCK_OPERATE)
OPERATE = AnyOf(Perm.STOCK_OPERATE, Perm.STOCK_MANAGE)
MANAGE = Perm.STOCK_MANAGE
CONTROLLED = Perm.STOCK_CONTROLLED
FACTS = AllOf(READ, Perm.FINANCE_VIEW)


def _scope(member: Membership) -> list[int] | None:
    return scope.branch_ids(member)


def _url(company_id: int, path: str) -> str:
    return f"/c/{company_id}/stock/{path}"


def _cost(member: Membership) -> bool:
    return member.has_perm(Perm.FINANCE_VIEW)


# The command palette ---------------------------------------------------------------------------


def search_products(member: Membership, q: str, limit: int) -> list[SearchHit]:
    rows = queries.lookup(member.company, q, branch_ids=_scope(member), limit=limit)
    return [
        SearchHit(
            type="inventory.product",
            id=row["id"],
            title=row["name"],
            subtitle=" · ".join(
                part
                for part in (
                    row["inn"],
                    _("Prescription") if row["rx_required"] else "",
                    _("%(count)s parts") % {"count": f"{row['quantity'].normalize():f}"}
                    if row["quantity"] is not None
                    else "",
                )
                if part
            ),
            url=_url(member.company_id, f"products?product={row['id']}"),
        )
        for row in rows
    ]


def search_batches(member: Membership, q: str, limit: int) -> list[SearchHit]:
    q = (q or "").strip()
    if len(q) < 3:
        return []
    rows = (
        queries.stock_rows(member.company, branch_ids=_scope(member))
        .filter(batch__series__icontains=q)
        .select_related("batch__product", "branch")[:limit]
    )
    return [
        SearchHit(
            type="inventory.batch",
            id=stock.pk,
            title=_("Series %(series)s: %(product)s")
            % {"series": stock.batch.series, "product": stock.batch.product.name},
            subtitle=f"{stock.branch.name} · {stock.batch.expires_on:%d.%m.%Y}",
            url=_url(member.company_id, f"levels?product={stock.batch.product_id}"),
        )
        for stock in rows
    ]


def search_receipts(member: Membership, q: str, limit: int) -> list[SearchHit]:
    q = (q or "").strip()
    if not q:
        return []
    rows = queries.receipts(member.company, branch_ids=_scope(member)).filter(
        Q(number__icontains=q) | Q(supplier_invoice_number__icontains=q)
    )[:limit]
    return [
        SearchHit(
            type="inventory.receipt",
            id=row.pk,
            title=_("Receipt %(number)s") % {"number": row.number or row.supplier_invoice_number},
            subtitle=f"{row.supplier.name} · {row.supplier_invoice_date:%d.%m.%Y}",
            url=_url(member.company_id, f"receipts/{row.pk}"),
        )
        for row in rows
    ]


# Needs you -----------------------------------------------------------------------------------


def receipts_to_post_count(member: Membership) -> int:
    return queries.to_post(member.company, branch_ids=_scope(member)).count()


def receipts_to_post(member: Membership, limit: int) -> list[QueueItem]:
    rows = queries.to_post(member.company, branch_ids=_scope(member)).order_by("submitted_at")[
        :limit
    ]
    return [
        QueueItem(
            kind="inventory.receipts_to_post",
            id=row.pk,
            title=_("Receipt %(invoice)s from %(supplier)s")
            % {
                "invoice": row.supplier_invoice_number or f"#{row.pk}",
                "supplier": row.supplier.name,
            },
            subtitle=f"{row.branch.name} · {row.supplier_invoice_date:%d.%m.%Y}",
            created_at=row.submitted_at or row.created_at,
            url=_url(member.company_id, f"receipts/{row.pk}"),
            actions=(
                QueueAction(
                    key="post",
                    label=_("Post"),
                    style="primary",
                    method="POST",
                    endpoint=f"stock/receipts/{row.pk}/post/",
                ),
            ),
        )
        for row in rows
    ]


def _waiting_writeoffs(member: Membership):
    return queries.writeoffs(member.company, branch_ids=_scope(member)).filter(
        status=WriteOff.Status.PROPOSED
    )


def writeoffs_count(member: Membership) -> int:
    return _waiting_writeoffs(member).count()


def writeoffs_to_approve(member: Membership, limit: int) -> list[QueueItem]:
    rows = _waiting_writeoffs(member).order_by("created_at")[:limit]
    return [
        QueueItem(
            kind="inventory.writeoffs_to_approve",
            id=row.pk,
            title=_("Write-off at %(branch)s: %(reason)s")
            % {"branch": row.branch.name, "reason": row.get_reason_display()},
            subtitle=row.note[:120],
            created_at=row.created_at,
            url=_url(member.company_id, f"write-offs/{row.pk}"),
            actions=(
                QueueAction(
                    key="approve",
                    label=_("Approve"),
                    style="primary",
                    method="POST",
                    endpoint=f"stock/write-offs/{row.pk}/approve/",
                ),
            ),
        )
        for row in rows
    ]


def _disputed(member: Membership):
    return queries.transfers(member.company, branch_ids=_scope(member)).filter(
        status=StockTransfer.Status.DISPUTED
    )


def disputed_count(member: Membership) -> int:
    return _disputed(member).count()


def disputed_transfers(member: Membership, limit: int) -> list[QueueItem]:
    rows = _disputed(member).order_by("received_at")[:limit]
    return [
        QueueItem(
            kind="inventory.transfers_disputed",
            id=row.pk,
            title=_("Transfer %(number)s arrived short") % {"number": row.number or f"#{row.pk}"},
            subtitle=f"{row.from_branch.name} → {row.to_branch.name}",
            created_at=row.received_at,
            url=_url(member.company_id, f"transfers/{row.pk}"),
            actions=(),
        )
        for row in rows
    ]


# Badges ----------------------------------------------------------------------------------------


def expiring_count(member: Membership) -> int:
    company = member.company
    return len(
        queries.expiring(
            company, branch_ids=_scope(member), within_days=30, as_of=engine.local_today(company)
        )
    )


def low_count(member: Membership) -> int:
    return queries.low_count(member.company, branch_ids=_scope(member))


# The morning brief -----------------------------------------------------------------------------


def brief_section(company, day, now, branch_ids) -> dict | None:
    """What stock needs today, in retail values (no costs: the brief is read by anyone with
    stock access). Nothing when all is well."""
    lines = []
    language = company.default_language
    soon = queries.expiring_value(company, branch_ids=branch_ids, within_days=30, as_of=day)
    if soon["count"]:
        lines.append(
            _("Expiring within 30 days: %(count)d batches, %(amount)s")
            % {
                "count": soon["count"],
                "amount": format_money(soon["retail_value"], company.base_currency, language),
            }
        )
    if soon["expired_count"]:
        lines.append(
            _("Expired, still on stock: %(count)d batches") % {"count": soon["expired_count"]}
        )
    if low := queries.low_count(company, branch_ids=branch_ids):
        lines.append(_("Below their minimum: %(count)d items") % {"count": low})
    if missing := queries.mandatory_missing(company, branch_ids=branch_ids, day=day):
        lines.append(_("Mandatory medicines missing: %(count)d") % {"count": len(missing)})
    if waiting := queries.to_post(company, branch_ids=branch_ids).count():
        lines.append(_("Receipts waiting for posting: %(count)d") % {"count": waiting})
    if recalls := queries.recalls_open(company).count():
        lines.append(_("Open recalls: %(count)d") % {"count": recalls})
    if not lines:
        return None
    return {"title": _("Stock"), "lines": lines}


# Get started -----------------------------------------------------------------------------------


def catalogue_done(company) -> bool:
    return Product.objects.for_company(company).filter(is_active=True).exists()


def opening_done(company) -> bool:
    return StockMovement.objects.for_company(company).exists()


def suppliers_done(company) -> bool:
    return SupplierProfile.objects.for_company(company).exists()


# The portfolio card ----------------------------------------------------------------------------


def company_facts(company, range, member: Membership) -> dict:
    day = engine.local_today(company)
    branch_ids = _scope(member)
    soon = queries.expiring_value(company, branch_ids=branch_ids, within_days=30, as_of=day)
    return {
        "expiring_30d_value": str(soon["value"]),
        "low_items": queries.low_count(company, branch_ids=branch_ids),
    }


# Copy setup ------------------------------------------------------------------------------------


def copy_categories(source, target, by: Membership) -> int:
    made = 0
    parents = {}
    for category in ProductCategory.objects.for_company(source).order_by(
        "parent_id", "order", "pk"
    ):
        parent = parents.get(category.parent_id)
        if category.parent_id and parent is None:
            continue
        found, created = ProductCategory.objects.get_or_create(
            company=target,
            name=category.name,
            parent=parent,
            defaults={"order": category.order},
        )
        parents[category.pk] = found
        made += int(created)
    return made


def copy_pricing(source, target, by: Membership) -> int:
    from apps.inventory import services

    made = 0
    settings = conf.get_settings(source)
    services.update_settings(
        target,
        by=by,
        **{field: getattr(settings, field) for field in services.SETTINGS_FIELDS},
    )
    names = {category.name: category for category in ProductCategory.objects.for_company(target)}
    for rule in PricingRule.objects.for_company(source).select_related("category"):
        category = names.get(rule.category.name) if rule.category_id else None
        if rule.category_id and category is None:
            continue
        PricingRule.objects.create(
            company=target,
            category=category,
            cost_from=rule.cost_from,
            cost_to=rule.cost_to,
            markup_percent=rule.markup_percent,
            order=rule.order,
            is_active=rule.is_active,
        )
        made += 1
    return made + 1


# Private files ----------------------------------------------------------------------------------


def _viewer(user, company_id: int) -> Membership | None:
    return (
        Membership.objects.filter(
            company_id=company_id, user=user, status=Membership.Status.APPROVED
        )
        .select_related("role", "company")
        .first()
    )


def _sees(viewer: Membership, branch_ids) -> bool:
    seen = scope.branch_ids(viewer)
    return seen is None or any(branch_id in seen for branch_id in branch_ids)


def may_open_receipt_file(user, company_id: int, receipt_id: int) -> bool:
    receipt = GoodsReceipt.objects.filter(company_id=company_id, pk=receipt_id).first()
    viewer = _viewer(user, company_id)
    return (
        receipt is not None
        and viewer is not None
        and holds(viewer, READ)
        and _sees(viewer, [receipt.branch_id])
    )


def may_open_writeoff_act(user, company_id: int, writeoff_id: int) -> bool:
    writeoff = WriteOff.objects.filter(company_id=company_id, pk=writeoff_id).first()
    viewer = _viewer(user, company_id)
    return (
        writeoff is not None
        and viewer is not None
        and holds(viewer, READ)
        and _sees(viewer, [writeoff.branch_id])
    )


def may_open_writeoff_file(user, company_id: int, file_id: int) -> bool:
    row = (
        WriteOffFile.objects.filter(writeoff__company_id=company_id, pk=file_id)
        .select_related("writeoff")
        .first()
    )
    viewer = _viewer(user, company_id)
    return (
        row is not None
        and viewer is not None
        and holds(viewer, READ)
        and _sees(viewer, [row.writeoff.branch_id])
    )


def may_open_recall_file(user, company_id: int, recall_id: int) -> bool:
    recall = RecallNotice.objects.filter(company_id=company_id, pk=recall_id).first()
    viewer = _viewer(user, company_id)
    return recall is not None and viewer is not None and holds(viewer, READ)


def may_open_rx_photo(user, company_id: int, record_id: int) -> bool:
    record = RxRecord.objects.filter(company_id=company_id, pk=record_id).first()
    viewer = _viewer(user, company_id)
    return (
        record is not None
        and viewer is not None
        and viewer.has_perm(CONTROLLED)
        and _sees(viewer, [record.branch_id])
    )


def may_open_journal(user, company_id: int, branch_id: int) -> bool:
    """A printed journal or act of a branch: whoever may read stock there (the controlled and
    prescription journals are linked only from stock.controlled screens)."""
    viewer = _viewer(user, company_id)
    return viewer is not None and holds(viewer, READ) and _sees(viewer, [branch_id])


# Excel exports ----------------------------------------------------------------------------------

LEVEL_COLUMNS = (
    ("branch", _("Pharmacy")),
    ("product", _("Medicine")),
    ("inn", _("INN")),
    ("rx", _("Prescription")),
    ("quantity", _("Parts on hand")),
    ("packs", _("Packs")),
    ("shortfall", _("Sold without stock")),
    ("min_qty", _("Minimum")),
    ("max_qty", _("Maximum")),
    ("sale_price", _("Price per pack"), "money"),
)


def level_rows(member: Membership, params: dict):
    for level in queries.levels(member.company, branch_ids=_scope(member)):
        product = level.product
        yield {
            "branch": level.branch.name,
            "product": product.name,
            "inn": product.inn,
            "rx": _("yes") if product.rx_required else "",
            "quantity": level.quantity,
            "packs": (level.quantity / max(product.units_per_pack, 1)).quantize(engine.PART),
            "shortfall": level.shortfall,
            "min_qty": level.min_qty,
            "max_qty": level.max_qty,
            "sale_price": product.sale_price,
        }


BATCH_COLUMNS = (
    ("branch", _("Pharmacy")),
    ("product", _("Medicine")),
    ("series", _("Series")),
    ("expires_on", _("Expiry date"), "date"),
    ("status", _("Status")),
    ("supplier", _("Distributor")),
    ("quantity", _("Parts")),
    ("retail_price", _("Price per pack"), "money"),
    ("unit_cost", _("Cost per pack"), "money"),
    ("value", _("Value at cost"), "money"),
)


def batch_rows(member: Membership, params: dict):
    cost = _cost(member)
    today = engine.local_today(member.company)
    for stock in queries.stock_rows(member.company, branch_ids=_scope(member)):
        batch = stock.batch
        yield {
            "branch": stock.branch.name,
            "product": batch.product.name,
            "series": batch.series,
            "expires_on": batch.expires_on,
            "status": _("Expired")
            if engine.is_expired(batch, today)
            else StockBatch.Status(batch.status).label,
            "supplier": batch.supplier.name if batch.supplier_id else "",
            "quantity": stock.quantity,
            "retail_price": batch.retail_price,
            "unit_cost": batch.unit_cost if cost else None,
            "value": engine.value_of(batch, stock.quantity) if cost else None,
        }


MOVEMENT_COLUMNS = (
    ("at", _("When"), "datetime"),
    ("branch", _("Pharmacy")),
    ("product", _("Medicine")),
    ("series", _("Series")),
    ("kind", _("Movement")),
    ("quantity", _("Parts")),
    ("unit_cost", _("Cost per part"), "money"),
    ("document", _("Document")),
    ("reason", _("Reason")),
)


def movement_rows(member: Membership, params: dict):
    cost = _cost(member)
    today = engine.local_today(member.company)
    start = params.get("from") or today - timedelta(days=30)
    end = params.get("to") or today
    for row in queries.movements(member.company, start, end, branch_ids=_scope(member)):
        yield {
            "at": row.at,
            "branch": row.branch.name,
            "product": row.product.name,
            "series": row.batch.series if row.batch_id else "",
            "kind": StockMovement.Kind(row.kind).label,
            "quantity": row.quantity,
            "unit_cost": row.unit_cost if cost else None,
            "document": f"{row.document_type} {row.document_id or ''}".strip(),
            "reason": row.reason,
        }


EXPIRY_COLUMNS = (
    ("branch", _("Pharmacy")),
    ("product", _("Medicine")),
    ("series", _("Series")),
    ("expires_on", _("Expiry date"), "date"),
    ("days_left", _("Days left")),
    ("quantity", _("Parts")),
    ("retail_value", _("Value at retail"), "money"),
    ("value", _("Value at cost"), "money"),
)


def expiry_rows(member: Membership, params: dict):
    cost = _cost(member)
    company = member.company
    for row in queries.expiring(
        company,
        branch_ids=_scope(member),
        within_days=int(params.get("within") or 90),
        as_of=engine.local_today(company),
    ):
        yield {
            "branch": row["branch"],
            "product": row["product"],
            "series": row["series"],
            "expires_on": row["expires_on"],
            "days_left": row["days_left"],
            "quantity": row["quantity"],
            "retail_value": row["retail_value"],
            "value": row["value"] if cost else None,
        }


WRITEOFF_COLUMNS = (
    ("number", _("Act")),
    ("branch", _("Pharmacy")),
    ("reason", _("Reason")),
    ("status", _("Status")),
    ("approved_at", _("Approved"), "datetime"),
    ("destroyed_at", _("Destroyed"), "datetime"),
    ("product", _("Medicine")),
    ("series", _("Series")),
    ("quantity", _("Parts")),
    ("value", _("Value at cost"), "money"),
)


def writeoff_rows(member: Membership, params: dict):
    cost = _cost(member)
    rows = queries.writeoffs(member.company, branch_ids=_scope(member)).exclude(
        status=WriteOff.Status.VOID
    )
    for writeoff in rows.prefetch_related("lines__batch__product"):
        for line in writeoff.lines.all():
            yield {
                "number": writeoff.number,
                "branch": writeoff.branch.name,
                "reason": writeoff.get_reason_display(),
                "status": writeoff.get_status_display(),
                "approved_at": writeoff.approved_at,
                "destroyed_at": writeoff.destroyed_at,
                "product": line.batch.product.name,
                "series": line.batch.series,
                "quantity": line.quantity,
                "value": line.value if cost else None,
            }


RX_COLUMNS = (
    ("recorded_at", _("When"), "datetime"),
    ("branch", _("Pharmacy")),
    ("product", _("Medicine")),
    ("quantity", _("Parts")),
    ("number", _("Prescription")),
    ("prescribed_on", _("Prescribed"), "date"),
    ("prescriber", _("Prescriber")),
    ("facility", _("Facility")),
    ("kind", _("Kind")),
    ("status", _("Status")),
    ("reason", _("What was wrong")),
)


def rx_rows(member: Membership, params: dict):
    rows = RxRecord.objects.for_company(member.company).select_related("branch", "product")
    seen = _scope(member)
    if seen is not None:
        rows = rows.filter(branch_id__in=seen)
    for record in rows.order_by("-recorded_at")[:20000]:
        yield {
            "recorded_at": record.recorded_at,
            "branch": record.branch.name,
            "product": record.product.name,
            "quantity": record.quantity,
            "number": record.prescription_number or record.e_prescription_id,
            "prescribed_on": record.prescribed_on,
            "prescriber": record.prescriber,
            "facility": record.facility,
            "kind": record.get_rx_kind_display(),
            "status": record.get_status_display(),
            "reason": record.invalid_reason,
        }


CONTROLLED_COLUMNS = (
    ("branch", _("Pharmacy")),
    ("month", _("Month")),
    ("product", _("Medicine")),
    ("opening", _("Opening")),
    ("received", _("Received")),
    ("issued", _("Issued")),
    ("written_off", _("Written off")),
    ("closing", _("Closing")),
    ("counted", _("Counted")),
    ("difference", _("Difference")),
    ("reported_on", _("Reported"), "date"),
)


def controlled_rows(member: Membership, params: dict):
    from apps.inventory.models import ControlledPeriod

    rows = ControlledPeriod.objects.for_company(member.company).select_related("branch", "product")
    seen = _scope(member)
    if seen is not None:
        rows = rows.filter(branch_id__in=seen)
    for period in rows.order_by("-month", "branch__name", "product__name"):
        yield {
            "branch": period.branch.name,
            "month": period.month.strftime("%m.%Y"),
            "product": period.product.name,
            "opening": period.opening,
            "received": period.received,
            "issued": period.issued,
            "written_off": period.written_off,
            "closing": period.closing,
            "counted": period.counted,
            "difference": period.difference,
            "reported_on": period.reported_on,
        }
