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
YES = {"1", "yes", "true", "ha", "да", "+", "x", "rx", "✓"}
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
