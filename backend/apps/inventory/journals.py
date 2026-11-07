"""The printed stock documents (`apps.core.pdf.render_pdf`, templates in `templates/inventory/`):

- the destruction act of a write-off ("Yo‘q qilish dalolatnomasi" / "Акт уничтожения", §14.4 row
  30): every field the act needs, its lines with series, expiry and value;
- the controlled-substance register of a month, one page per medicine laid out like the paper
  books (narcotics; psychotropics and precursors; strong-acting), which stay the legal record;
- the prescription log and the invalid-prescription log of a month.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.utils import timezone, translation
from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError
from apps.core.money import format_money, quantize
from apps.core.pdf import render_pdf
from apps.inventory import engine, register
from apps.inventory.models import Product, RxRecord, StockMovement, WriteOff

KINDS = ("rx", "rx_invalid", "controlled")


def _qty(value) -> str:
    value = Decimal(value or 0)
    return f"{value.normalize():f}" if value == value.to_integral_value() else f"{value:.3f}"


def packs_and_parts(product, quantity) -> str:
    """ "3 qadoq 1 blister": whole packs and the parts left over."""
    quantity = Decimal(quantity or 0)
    count = max(product.units_per_pack, 1)
    if count == 1:
        return _("%(packs)s packs") % {"packs": _qty(quantity)}
    packs, rest = divmod(quantity, count)
    label = product.part_label or _("parts")
    if not rest:
        return _("%(packs)s packs") % {"packs": _qty(packs)}
    if not packs:
        return f"{_qty(rest)} {label}"
    return _("%(packs)s packs %(rest)s %(label)s") % {
        "packs": _qty(packs),
        "rest": _qty(rest),
        "label": label,
    }


def act_pdf(writeoff: WriteOff, *, language: str) -> bytes:
    company = writeoff.company
    with translation.override(language):
        lines = []
        for line in writeoff.lines.select_related("batch__product__manufacturer"):
            batch = line.batch
            product = batch.product
            lines.append(
                {
                    "product": product.name,
                    "manufacturer": product.manufacturer.name if product.manufacturer else "",
                    "series": batch.series,
                    "expires_on": batch.expires_on.strftime("%d.%m.%Y"),
                    "quantity": packs_and_parts(product, line.quantity),
                    "unit_cost": format_money(batch.unit_cost, company.base_currency, language),
                    "value": format_money(line.value, company.base_currency, language),
                }
            )
        destroyed = company.format_datetime(writeoff.destroyed_at) if writeoff.destroyed_at else ""
        context = {
            "company": company,
            "title": _("Destruction act %(number)s") % {"number": writeoff.number},
            "printed_on": timezone.localtime(timezone.now(), engine.zone_of(company)).strftime(
                "%d.%m.%Y"
            ),
            "writeoff": writeoff,
            "branch": writeoff.branch,
            "reason": writeoff.get_reason_display(),
            "method": writeoff.get_method_display() if writeoff.method else "",
            "destroyed": destroyed,
            "approved_on": writeoff.approved_at.astimezone(engine.zone_of(company)).strftime(
                "%d.%m.%Y"
            )
            if writeoff.approved_at
            else "",
            "commission": writeoff.commission or [],
            "lines": lines,
            "total": format_money(writeoff.value, company.base_currency, language),
            "sent_to": writeoff.sent_to or [],
            "photos": writeoff.files.filter(kind__in=("photo", "video")).count(),
        }
    return render_pdf("inventory/writeoff_act.html", context, language=language)


def pdf(kind: str, *, branch, month: date, product=None, language: str) -> bytes:
    if kind not in KINDS:
        raise DomainError(_("Pick a journal: prescriptions, invalid prescriptions or controlled."))
    month = register.month_start(month)
    if kind == "controlled":
        return controlled_pdf(branch, month, product=product, language=language)
    return rx_pdf(branch, month, invalid=kind == "rx_invalid", language=language)


BOOKS = (
    ("narcotic", (Product.ControlClass.NARCOTIC,)),
    ("psychotropic", (Product.ControlClass.PSYCHOTROPIC, Product.ControlClass.PRECURSOR)),
    ("strong", (Product.ControlClass.STRONG,)),
)


def _book_title(key: str) -> str:
    return {
        "narcotic": _("Register of narcotic medicines"),
        "psychotropic": _("Register of psychotropic medicines and precursors"),
        "strong": _("Register of strong-acting medicines"),
    }[key]


OPERATIONS = {
    StockMovement.Kind.OPENING: lambda: _("Opening stock"),
    StockMovement.Kind.RECEIPT: lambda: _("Received"),
    StockMovement.Kind.TRANSFER_IN: lambda: _("Received by transfer"),
    StockMovement.Kind.SALE: lambda: _("Dispensed"),
    StockMovement.Kind.REFUND: lambda: _("Returned by a customer"),
    StockMovement.Kind.TRANSFER_OUT: lambda: _("Sent by transfer"),
    StockMovement.Kind.WRITEOFF: lambda: _("Written off"),
    StockMovement.Kind.COUNT_ADJUSTMENT: lambda: _("Count adjustment"),
}


def _operation(kind: str) -> str:
    label = OPERATIONS.get(kind)
    return label() if label is not None else kind


def controlled_pdf(branch, month: date, *, product=None, language: str) -> bytes:
    company = branch.company
    start, end = register._bounds(company, month)
    with translation.override(language):
        rows = register.rows(branch, month, product=product)
        products = {
            item.pk: item
            for item in Product.objects.filter(pk__in=[row["product_id"] for row in rows])
        }
        books = []
        for key, classes in BOOKS:
            pages = []
            for row in rows:
                item = products[row["product_id"]]
                if item.control_class not in classes:
                    continue
                balance = row["opening"]
                entries = []
                movements = (
                    StockMovement.objects.filter(
                        branch=branch, product=item, at__gte=start, at__lt=end
                    )
                    .exclude(kind__in=(StockMovement.Kind.QUARANTINE, StockMovement.Kind.RELEASE))
                    .select_related("batch")
                    .order_by("at", "pk")
                )
                for movement in movements:
                    balance += movement.quantity
                    entries.append(
                        {
                            "day": movement.at.astimezone(engine.zone_of(company)).strftime(
                                "%d.%m.%Y"
                            ),
                            "operation": _operation(movement.kind),
                            "document": _document(movement),
                            "series": movement.batch.series if movement.batch_id else "",
                            "received": _qty(movement.quantity) if movement.quantity > 0 else "",
                            "issued": _qty(-movement.quantity) if movement.quantity < 0 else "",
                            "balance": _qty(balance),
                        }
                    )
                pages.append(
                    {
                        "product": item.name,
                        "inn": item.inn,
                        "unit": item.part_label or _("parts"),
                        "row": {
                            name: _qty(row[name])
                            for name in (
                                "opening",
                                "received",
                                "issued",
                                "written_off",
                                "adjusted",
                                "closing",
                            )
                        },
                        "counted": _qty(row["counted"]) if row["counted"] is not None else "",
                        "difference": _qty(row["difference"])
                        if row["difference"] is not None
                        else "",
                        "unrecorded": row["unrecorded_issues"],
                        "entries": entries,
                    }
                )
            if pages:
                books.append({"title": _book_title(key), "pages": pages})
        context = {
            "company": company,
            "title": _("Controlled-substance register"),
            "branch": branch.name,
            "month": month.strftime("%m.%Y"),
            "books": books,
            "printed_on": timezone.localtime(timezone.now(), engine.zone_of(company)).strftime(
                "%d.%m.%Y"
            ),
        }
    return render_pdf("inventory/controlled_register.html", context, language=language)


def _document(movement: StockMovement) -> str:
    from apps.inventory.models import GoodsReceipt, StockTransfer, WriteOff

    model = {
        "inventory.goodsreceipt": GoodsReceipt,
        "inventory.stocktransfer": StockTransfer,
        "inventory.writeoff": WriteOff,
    }.get(movement.document_type)
    if model is None or movement.document_id is None:
        return ""
    found = model.objects.filter(pk=movement.document_id).first()
    return str(found) if found is not None else ""


def rx_pdf(branch, month: date, *, invalid: bool, language: str) -> bytes:
    company = branch.company
    start, end = register._bounds(company, month)
    status = RxRecord.Status.INVALID if invalid else RxRecord.Status.DISPENSED
    with translation.override(language):
        rows = []
        for record in (
            RxRecord.objects.filter(
                branch=branch, status=status, recorded_at__gte=start, recorded_at__lt=end
            )
            .select_related("product", "batch")
            .order_by("recorded_at", "pk")
        ):
            rows.append(
                {
                    "day": record.recorded_at.astimezone(engine.zone_of(company)).strftime(
                        "%d.%m.%Y"
                    ),
                    "number": record.prescription_number or record.e_prescription_id,
                    "prescribed_on": record.prescribed_on.strftime("%d.%m.%Y")
                    if record.prescribed_on
                    else "",
                    "prescriber": record.prescriber,
                    "facility": record.facility,
                    "product": record.product.name,
                    "series": record.batch.series if record.batch_id else "",
                    "quantity": packs_and_parts(record.product, record.quantity),
                    "kind": record.get_rx_kind_display(),
                    "reason": record.invalid_reason,
                    "notified": company.format_datetime(record.facility_notified_at)
                    if record.facility_notified_at
                    else "",
                }
            )
        context = {
            "company": company,
            "title": _("Invalid prescriptions log") if invalid else _("Prescription log"),
            "branch": branch.name,
            "month": month.strftime("%m.%Y"),
            "rows": rows,
            "invalid": invalid,
            "printed_on": timezone.localtime(timezone.now(), engine.zone_of(company)).strftime(
                "%d.%m.%Y"
            ),
        }
    return render_pdf("inventory/rx_journal.html", context, language=language)


def money(value) -> Decimal:
    return quantize(value)


def _maker(product) -> str:
    maker = product.manufacturer
    if maker is None:
        return ""
    return f"{maker.name}, {maker.country}" if maker.country else maker.name


def price_tags_pdf(branch, products, *, language: str) -> bytes:
    """Price tags for the shelf, with a signature line (§14.4 row 16), at the price the branch
    sells next (its earliest-expiring batch on sale, else the list price). Prescription items
    aren't displayed to the public: they go on a counter list marked so, with their legal
    maximum."""
    from apps.inventory import conf, pricing

    company = branch.company
    settings = conf.get_settings(company)
    today = engine.local_today(company)
    currency = company.base_currency
    tags, counter = [], []
    with translation.override(language):
        for product in products:
            stocks = engine.fefo_stocks(branch, product, today)
            batch = stocks[0].batch if stocks else None
            price = batch.retail_price if batch is not None else product.sale_price
            part = ""
            if product.units_per_pack > 1:
                amount = pricing.part_price(product, batch, settings=settings)
                part = _("%(price)s per %(part)s") % {
                    "price": format_money(amount, currency, language),
                    "part": product.part_label or _("part"),
                }
            row = {
                "name": product.name,
                "maker": _maker(product),
                "price": format_money(price, currency, language),
                "part": part,
            }
            if product.rx_required:
                cost = batch.unit_cost if batch is not None else None
                cap = pricing.price_ceiling(product, cost, settings)
                row["cap"] = format_money(cap, currency, language) if cap else ""
                counter.append(row)
            else:
                tags.append(row)
        context = {
            "company": company,
            "title": _("Price tags"),
            "branch": branch.name,
            "tags": tags,
            "counter": counter,
            "printed_on": today.strftime("%d.%m.%Y"),
        }
    return render_pdf("inventory/price_tags.html", context, language=language)
