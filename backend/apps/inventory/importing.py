"""Importing the catalogue from a spreadsheet (XLSX or CSV), with a dry run first.

The columns are guessed from the header row (English, Uzbek and Russian words a distributor's
or a cash-register program's export uses) and can be given as a map {column: field}. Rows are
matched to the catalogue by barcode (then SKU): a match is updated, the rest are created. A
dry run says what would happen, row by row, and changes nothing.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError
from apps.inventory.audit_actions import InventoryAction as Action
from apps.inventory.models import Manufacturer, Product, ProductCategory

FIELDS = (
    "name",
    "trade_name",
    "inn",
    "barcode",
    "sku",
    "kind",
    "dosage_form",
    "strength",
    "units_per_pack",
    "part_label",
    "manufacturer",
    "country",
    "category",
    "rx_required",
    "control_class",
    "storage",
    "sale_price",
    "reference_price",
    "mandatory_list",
    "socially_significant",
    "registration_number",
    "registration_until",
    "mxik_code",
    "vat_percent",
)
# Header words (lowercase, without spaces) each field is known by.
SYNONYMS = {
    "name": ("name", "nomi", "nomlanishi", "наименование", "название", "товар", "tovar", "product"),
    "trade_name": ("tradename", "brand", "savdonomi", "торговоеназвание", "бренд"),
    "inn": ("inn", "mnn", "xpn", "мнн", "activeingredient", "ta’siretuvchimodda"),
    "barcode": ("barcode", "ean", "shtrixkod", "штрихкод", "штрих-код", "shtrix-kod"),
    "sku": ("sku", "article", "artikul", "артикул", "code", "kod", "код"),
    "kind": ("kind", "type", "turi", "тип"),
    "dosage_form": ("form", "dosageform", "shakli", "форма", "лекарственнаяформа"),
    "strength": ("strength", "dose", "dozasi", "дозировка"),
    "units_per_pack": ("units", "unitsperpack", "parts", "qismlar", "вупаковке", "делимость"),
    "part_label": ("part", "partlabel", "qism", "часть"),
    "manufacturer": ("manufacturer", "maker", "ishlabchiqaruvchi", "производитель"),
    "country": ("country", "mamlakat", "страна"),
    "category": ("category", "group", "toifa", "guruh", "категория", "группа"),
    "rx_required": ("rx", "prescription", "retsept", "рецепт", "порецепту"),
    "control_class": ("control", "controlclass", "nazorat", "контроль"),
    "storage": ("storage", "saqlash", "хранение"),
    "sale_price": ("price", "saleprice", "narx", "narxi", "цена", "розничнаяцена"),
    "reference_price": ("referenceprice", "referentnarx", "референтнаяцена", "предельнаяцена"),
    "mandatory_list": ("mandatory", "majburiy", "обязательный", "обязательныйассортимент"),
    "socially_significant": ("social", "ijtimoiy", "социальнозначимый"),
    "registration_number": ("registration", "regnumber", "ro‘yxat", "регистрационныйномер"),
    "registration_until": ("registrationuntil", "regvalid", "срокрегистрации"),
    "mxik_code": ("mxik", "ikpu", "икпу", "мхик"),
    "vat_percent": ("vat", "qqs", "ндс"),
}
# A check mark typed in a cell counts too; built at run time, since it is read, never sent (the
# bots' no-emoji check reads every string literal).
YES = {"1", "yes", "true", "ha", "да", "+", "x", "rx", chr(0x2713)}
KIND_WORDS = {
    "medicine": ("medicine", "dori", "препарат", "лс"),
    "device": ("device", "tibbiy buyum", "изделие", "мед изделие"),
    "supplement": ("supplement", "bad", "бад", "vitamin", "витамин"),
    "cosmetic": ("cosmetic", "kosmetika", "косметика", "gigiyena", "гигиена"),
    "other": ("other", "boshqa", "прочее"),
}
MAX_ROWS = 20000


def _key(text) -> str:
    return "".join(str(text or "").lower().split()).replace("'", "’").replace("`", "’")


def read_table(upload) -> tuple[list[str], list[list[str]]]:
    """The header and the rows of an XLSX or CSV file (cells as text)."""
    name = getattr(upload, "name", "") or ""
    upload.seek(0)
    data = upload.read()
    if name.endswith(".xlsx") or data[:2] == b"PK":
        from openpyxl import load_workbook

        book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        sheet = book.worksheets[0]
        rows = [
            ["" if cell is None else _cell(cell) for cell in row]
            for row in sheet.iter_rows(values_only=True)
        ]
        book.close()
    else:
        text = None
        for encoding in ("utf-8-sig", "cp1251"):
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise DomainError(_("The file's text can't be read: save it as UTF-8 CSV or XLSX."))
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t") if text.strip() else None
        rows = [row for row in csv.reader(io.StringIO(text), dialect or csv.excel)]
    rows = [row for row in rows if any(str(cell).strip() for cell in row)]
    if not rows:
        raise DomainError(_("The file is empty."))
    if len(rows) > MAX_ROWS + 1:
        raise DomainError(_("At most %(count)s rows at a time.") % {"count": MAX_ROWS})
    header = [str(cell).strip() for cell in rows[0]]
    return header, [[str(cell).strip() for cell in row] for row in rows[1:]]


def _cell(value) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def guess_mapping(header: list[str]) -> dict[str, str]:
    """{column header: field} for the columns whose header names a known field."""
    found: dict[str, str] = {}
    taken = set()
    for column in header:
        key = _key(column)
        for field in FIELDS:
            if field in taken:
                continue
            if key == field or key in SYNONYMS.get(field, ()):
                found[column] = field
                taken.add(field)
                break
    return found


def _decimal(text: str) -> Decimal | None:
    text = (text or "").replace(" ", "").replace("\xa0", "").replace(",", ".")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(text) from exc


def _bool(text: str) -> bool:
    return _key(text) in YES


def _kind(text: str) -> str:
    key = (text or "").strip().lower()
    for kind, words in KIND_WORDS.items():
        if key == kind or key in words:
            return kind
    return Product.Kind.MEDICINE


def _choice(text: str, choices, default: str) -> str:
    key = (text or "").strip().lower()
    return key if key in choices else default


def _row_fields(values: dict[str, str], cache: dict) -> tuple[dict, list[str]]:
    from apps.inventory.services import normalize_inn

    errors: list[str] = []
    fields: dict = {}
    for field, text in values.items():
        if field in ("country",):
            continue
        try:
            if field in ("sale_price", "reference_price", "vat_percent"):
                number = _decimal(text)
                if number is not None:
                    if number < 0:
                        raise ValueError(text)
                    fields[field] = number
            elif field == "units_per_pack":
                number = _decimal(text)
                if number is not None:
                    if number < 1 or number != number.to_integral_value():
                        raise ValueError(text)
                    fields[field] = int(number)
            elif field in ("rx_required", "mandatory_list", "socially_significant"):
                fields[field] = _bool(text)
            elif field == "kind":
                fields[field] = _kind(text)
            elif field == "dosage_form":
                fields[field] = _choice(text, Product.DosageForm.values, "")
            elif field == "control_class":
                fields[field] = _choice(
                    text, Product.ControlClass.values, Product.ControlClass.NONE
                )
            elif field == "storage":
                fields[field] = _choice(text, Product.Storage.values, Product.Storage.ROOM)
            elif field == "registration_until":
                fields[field] = date.fromisoformat(text[:10]) if text else None
            elif field == "inn":
                fields[field] = normalize_inn(text)
            elif field == "manufacturer":
                fields[field] = text[:120]
            elif field == "category":
                fields[field] = text[:100]
            else:
                limit = Product._meta.get_field(field).max_length or 200
                fields[field] = text[:limit]
        except ValueError, TypeError:
            errors.append(
                _("%(field)s: “%(value)s” can't be read") % {"field": field, "value": text}
            )
    if values.get("country"):
        fields["_country"] = values["country"][:2].upper()
    if not fields.get("name"):
        errors.append(_("No name."))
    return fields, errors


@transaction.atomic
def import_products(
    company, upload, *, by, mapping: dict | None = None, dry_run: bool = True
) -> dict:
    """Create and update catalogue rows from a spreadsheet. Returns what happened (or would
    happen, on a dry run): counts and one entry per row."""
    from apps.inventory import services

    header, rows = read_table(upload)
    mapping = {
        column: field
        for column, field in (mapping or guess_mapping(header)).items()
        if field in FIELDS and column in header
    }
    if "name" not in mapping.values():
        raise DomainError(_("Pick the column with the item's name."))
    index = {header.index(column): field for column, field in mapping.items()}
    existing = {
        product.barcode: product
        for product in Product.objects.for_company(company).exclude(barcode="")
    }
    by_sku = {
        product.sku: product for product in Product.objects.for_company(company).exclude(sku="")
    }
    cache: dict = {}
    result = {
        "dry_run": dry_run,
        "columns": header,
        "mapping": mapping,
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "rows": [],
    }
    seen_barcodes: set[str] = set()
    for number, row in enumerate(rows, start=2):
        values = {
            field: row[position] if position < len(row) else "" for position, field in index.items()
        }
        fields, errors = _row_fields(values, cache)
        barcode = fields.get("barcode", "")
        if barcode and barcode in seen_barcodes:
            errors.append(_("The barcode repeats an earlier row."))
        if barcode:
            seen_barcodes.add(barcode)
        match = existing.get(barcode) if barcode else None
        if match is None and fields.get("sku"):
            match = by_sku.get(fields["sku"])
        entry = {
            "row": number,
            "action": "skip" if errors else ("update" if match else "create"),
            "name": fields.get("name", ""),
            "product_id": match.pk if match else None,
            "errors": errors,
        }
        result["rows"].append(entry)
        if errors:
            result["skipped"] += 1
            continue
        result["updated" if match else "created"] += 1
        if dry_run:
            continue
        country = fields.pop("_country", "")
        maker = fields.pop("manufacturer", None)
        group = fields.pop("category", None)
        if maker:
            fields["manufacturer"] = _manufacturer(company, maker, country, cache)
        if group:
            fields["category"] = _category(company, group, cache)
        try:
            with transaction.atomic():
                if match is None:
                    product = services.create_product(company, by=by, **fields)
                    entry["product_id"] = product.pk
                    if product.barcode:
                        existing[product.barcode] = product
                else:
                    services.update_product(match, by=by, **fields)
        except DomainError as exc:
            entry["action"] = "skip"
            entry["errors"] = [str(exc)]
            result["skipped"] += 1
            result["updated" if match else "created"] -= 1
    result["rows"] = result["rows"][:500]
    if not dry_run:
        from apps.inventory.services import _audit, _bump

        _audit(
            Action.PRODUCTS_IMPORTED,
            company.pk,
            by,
            company,
            created=result["created"],
            updated=result["updated"],
            skipped=result["skipped"],
        )
        _bump(company.pk)
    return result


def _manufacturer(company, name: str, country: str, cache: dict) -> Manufacturer:
    key = ("m", name.lower())
    if key not in cache:
        found = Manufacturer.objects.for_company(company).filter(name__iexact=name).first()
        if found is None:
            found = Manufacturer.objects.create(company=company, name=name, country=country)
        cache[key] = found
    return cache[key]


def _category(company, name: str, cache: dict) -> ProductCategory:
    key = ("c", name.lower())
    if key not in cache:
        found = ProductCategory.objects.for_company(company).filter(name__iexact=name).first()
        if found is None:
            found = ProductCategory.objects.create(company=company, name=name)
        cache[key] = found
    return cache[key]


# A distributor's invoice spreadsheet into receipt lines -------------------------------------

LINE_FIELDS = (
    "code",
    "barcode",
    "name",
    "series",
    "expires_on",
    "made_on",
    "packs",
    "unit_cost",
    "vat_percent",
    "rx",
)
LINE_SYNONYMS = {
    "code": ("code", "kod", "код", "itemcode", "kodtovara", "кодтовара", "artikul", "артикул"),
    "barcode": SYNONYMS["barcode"],
    "name": SYNONYMS["name"],
    "series": ("series", "seriya", "серия", "batch", "lot", "партия"),
    "expires_on": (
        "expiry",
        "expires",
        "expireson",
        "yaroqlilikmuddati",
        "срокгодности",
        "годендо",
    ),
    "made_on": ("made", "madeon", "ishlabchiqarilgan", "датапроизводства"),
    "packs": ("packs", "qty", "quantity", "soni", "miqdori", "количество", "кол-во", "кол"),
    "unit_cost": ("price", "cost", "unitcost", "narx", "narxi", "цена", "ценазаед", "цена,сум"),
    "vat_percent": SYNONYMS["vat_percent"],
    "rx": SYNONYMS["rx_required"],
}


def guess_line_mapping(header: list[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    taken = set()
    for column in header:
        key = _key(column)
        for field in LINE_FIELDS:
            if field in taken:
                continue
            if key == field or key in LINE_SYNONYMS.get(field, ()):
                found[column] = field
                taken.add(field)
                break
    return found


def parse_day(text: str) -> date | None:
    """31.12.2027, 2027-12-31, 12.2027 or 12/2027 (the last day of that month)."""
    import calendar

    text = (text or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    parts = text.replace("/", ".").replace("-", ".").split(".")
    try:
        if len(parts) == 3:
            day, month, year = (int(part) for part in parts)
            year += 2000 if year < 100 else 0
            return date(year, month, day)
        if len(parts) == 2:
            month, year = (int(part) for part in parts)
            year += 2000 if year < 100 else 0
            return date(year, month, calendar.monthrange(year, month)[1])
    except ValueError:
        return None
    return None


def _match(company, supplier, values: dict) -> Product | None:
    from apps.inventory import queries
    from apps.inventory.models import ProductCode

    code = values.get("code", "").strip()
    if code:
        found = (
            ProductCode.objects.filter(
                company=company, kind=ProductCode.Kind.SUPPLIER, supplier=supplier, code=code
            )
            .select_related("product")
            .first()
        )
        if found is not None:
            return found.product
    for key in ("barcode", "code"):
        if values.get(key) and (product := queries.match_code(company, values[key])):
            return product
    name = values.get("name", "").strip()
    if name:
        return Product.objects.for_company(company).filter(name__iexact=name).first()
    return None


@transaction.atomic
def import_lines(receipt, upload, *, by, mapping: dict | None = None, dry_run: bool = True) -> dict:
    """A distributor's invoice (XLSX or CSV) into lines of a draft receipt. Rows are matched by
    the distributor's own item code, the barcode, then the exact name; a row that matches
    nothing is listed for the person to pick its item (remember_code then finds it next time).
    The column map is remembered per distributor."""
    from apps.inventory import services
    from apps.inventory.models import GoodsReceipt, SupplierProfile

    if receipt.status not in (GoodsReceipt.Status.DRAFT, GoodsReceipt.Status.SUBMITTED):
        raise DomainError(_("A posted or void receipt can't be changed."))
    header, rows = read_table(upload)
    profile = SupplierProfile.objects.filter(counterparty_id=receipt.supplier_id).first()
    saved = (profile.price_list_mapping or {}).get("invoice") if profile else None
    mapping = mapping or saved or guess_line_mapping(header)
    mapping = {
        column: field
        for column, field in mapping.items()
        if field in LINE_FIELDS and column in header
    }
    if "packs" not in mapping.values() or not {"code", "barcode", "name"} & set(mapping.values()):
        raise DomainError(_("Pick the columns with the item and the number of packs."))
    index = {header.index(column): field for column, field in mapping.items()}
    result = {
        "dry_run": dry_run,
        "columns": header,
        "mapping": mapping,
        "added": 0,
        "unmatched": 0,
        "skipped": 0,
        "rows": [],
    }
    for number, row in enumerate(rows, start=2):
        values = {
            field: row[position] if position < len(row) else "" for position, field in index.items()
        }
        product = _match(receipt.company, receipt.supplier, values)
        errors = []
        packs = unit_cost = vat = None
        try:
            packs = _decimal(values.get("packs", ""))
            unit_cost = _decimal(values.get("unit_cost", "")) or Decimal(0)
            vat = _decimal(values.get("vat_percent", ""))
        except ValueError:
            errors.append(_("A number can't be read."))
        expires_on = parse_day(values.get("expires_on", ""))
        if not packs or packs <= 0:
            errors.append(_("No quantity."))
        if expires_on is None:
            errors.append(_("No expiry date."))
        if not values.get("series", "").strip():
            errors.append(_("No series."))
        entry = {
            "row": number,
            "action": "add",
            "name": values.get("name") or values.get("code") or values.get("barcode") or "",
            "product_id": product.pk if product else None,
            "errors": [str(error) for error in errors],
        }
        if errors:
            entry["action"] = "skip"
            result["skipped"] += 1
        elif product is None:
            entry["action"] = "unmatched"
            result["unmatched"] += 1
        else:
            result["added"] += 1
            if not dry_run:
                try:
                    with transaction.atomic():
                        services.add_line(
                            receipt,
                            by=by,
                            product=product,
                            series=values["series"],
                            expires_on=expires_on,
                            made_on=parse_day(values.get("made_on", "")),
                            packs=packs,
                            unit_cost=unit_cost,
                            vat_percent=vat,
                            supplier_rx=_bool(values["rx"]) if values.get("rx") else None,
                        )
                except DomainError as exc:
                    entry["action"] = "skip"
                    entry["errors"] = [str(exc)]
                    result["added"] -= 1
                    result["skipped"] += 1
        result["rows"].append(entry)
    if not dry_run and profile is not None and mapping != saved:
        profile.price_list_mapping = {**(profile.price_list_mapping or {}), "invoice": mapping}
        profile.save(update_fields=["price_list_mapping", "updated_at"])
    result["rows"] = result["rows"][:500]
    return result


# The regulator's list of rejected series into recalls ---------------------------------------

RECALL_FIELDS = ("series", "name", "barcode", "reason")
RECALL_SYNONYMS = {
    "series": LINE_SYNONYMS["series"],
    "name": (*SYNONYMS["name"], *SYNONYMS["inn"], "dori", "препарат", "наименованиепрепарата"),
    "barcode": SYNONYMS["barcode"],
    "reason": ("reason", "sabab", "причина", "основание", "nomuvofiqlik", "несоответствие"),
}


def guess_recall_mapping(header: list[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    taken = set()
    for column in header:
        key = _key(column)
        for field in RECALL_FIELDS:
            if field in taken:
                continue
            if key == field or key in RECALL_SYNONYMS.get(field, ()):
                found[column] = field
                taken.add(field)
                break
    return found


def _recall_product(company, values: dict) -> Product | None:
    from apps.inventory import queries
    from apps.inventory.services import normalize_inn

    if values.get("barcode") and (product := queries.match_code(company, values["barcode"])):
        return product
    name = (values.get("name") or "").strip()
    if not name:
        return None
    rows = Product.objects.for_company(company)
    return (
        rows.filter(name__iexact=name).first()
        or rows.filter(trade_name__iexact=name).first()
        or rows.filter(inn=normalize_inn(name)).order_by("pk").first()
    )


@transaction.atomic
def import_recalls(
    company,
    upload,
    *,
    by,
    source: str,
    received_on: date,
    reason: str = "",
    mapping: dict | None = None,
    dry_run: bool = True,
) -> dict:
    """The regulator's rejected-series list (XLSX or CSV) into recalls: one per row whose
    medicine is in the catalogue (by barcode, name, trade name or INN), each finding its series
    in every branch. Rows of medicines the company doesn't carry are only counted. A dry run
    says what each row would find and changes nothing."""
    from apps.inventory import services
    from apps.inventory.models import RecallNotice

    header, rows = read_table(upload)
    mapping = mapping or guess_recall_mapping(header)
    mapping = {
        column: field
        for column, field in mapping.items()
        if field in RECALL_FIELDS and column in header
    }
    if "series" not in mapping.values() or not {"name", "barcode"} & set(mapping.values()):
        raise DomainError(_("Pick the columns with the medicine and its series."))
    index = {header.index(column): field for column, field in mapping.items()}
    result = {
        "dry_run": dry_run,
        "columns": header,
        "mapping": mapping,
        "registered": 0,
        "found": 0,
        "not_carried": 0,
        "rows": [],
    }
    for number, row in enumerate(rows, start=2):
        values = {
            field: row[position] if position < len(row) else "" for position, field in index.items()
        }
        series = (values.get("series") or "").strip()
        product = _recall_product(company, values)
        entry = {
            "row": number,
            "name": values.get("name") or values.get("barcode") or "",
            "series": series,
            "product_id": product.pk if product else None,
            "found": 0,
            "action": "skip",
        }
        result["rows"].append(entry)
        if not series:
            continue
        if product is None:
            entry["action"] = "not_carried"
            result["not_carried"] += 1
            continue
        known = RecallNotice.objects.filter(
            company=company,
            product=product,
            series__iexact=series,
            status=RecallNotice.Status.OPEN,
        ).exists()
        if known:
            entry["action"] = "known"
            continue
        held = services._matching_batches(
            company, product=product, inn_or_name="", series=series
        ).filter(stocks__quantity__gt=0)
        entry["found"] = held.distinct().count()
        entry["action"] = "register"
        result["registered"] += 1
        result["found"] += int(entry["found"] > 0)
        if not dry_run:
            services.register_recall(
                company,
                by=by,
                series=series,
                reason=(values.get("reason") or reason or "").strip()[:200]
                or _("On the regulator's list of rejected series"),
                source=source,
                received_on=received_on,
                product=product,
                announce=entry["found"] > 0,
            )
    result["rows"] = result["rows"][:500]
    return result
