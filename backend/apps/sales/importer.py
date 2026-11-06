"""Reading a cash-register program's export (docs/PLAN-OWNER.md §14.7): CSV or XLSX in, one
`Row` per sale line out, read through an import profile's column map.

Pure reading: nothing here writes to the database, so the column mapper's preview and the
background import read files the same way. Cash-register programs differ in everything, so
every choice is the profile's: the encoding (UTF-8, else Windows-1251), the delimiter (found from
the file when empty), the row holding the column names, the date format (the usual ones when
empty) and what a quantity counts when the file has no unit column. Numbers may be written the
Russian way ("1 234,50"); a negative quantity or total is a refund.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError

MAX_ROWS = 200_000
PREVIEW_ROWS = 20
CENT = Decimal("0.01")
ENCODINGS = ("utf-8-sig", "cp1251")
DELIMITERS = ";,\t|"

DATE_FORMATS = (
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %H:%M",
    "%d.%m.%Y",
    "%d.%m.%y %H:%M:%S",
    "%d.%m.%y %H:%M",
    "%d.%m.%y",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
)
TIME_FORMATS = ("%H:%M:%S", "%H:%M")

# What the column mapper proposes for a header it recognizes (lowercase, trimmed): the words the
# programs used by pharmacies in Uzbekistan print, in Russian, Uzbek and English.
SYNONYMS = {
    "receipt": (
        "номер чека",
        "№ чека",
        "чек №",
        "чек",
        "номер документа",
        "chek",
        "chek raqami",
        "receipt",
        "receipt number",
        "check",
    ),
    "sold_at": (
        "дата и время",
        "дата/время",
        "дата время",
        "дата продажи",
        "время продажи",
        "sana va vaqt",
        "date and time",
        "datetime",
        "sold at",
    ),
    "date": ("дата", "sana", "date"),
    "time": ("время", "vaqt", "time"),
    "register": ("касса", "номер кассы", "kassa", "register", "till", "pos"),
    "cashier": ("кассир", "продавец", "фармацевт", "сотрудник", "kassir", "sotuvchi", "cashier"),
    "code": (
        "штрихкод",
        "штрих-код",
        "штрих код",
        "баркод",
        "код товара",
        "код",
        "ean",
        "shtrix kod",
        "shtrixkod",
        "barcode",
        "code",
        "item code",
        "sku",
    ),
    "name": (
        "наименование",
        "наименование товара",
        "товар",
        "препарат",
        "название",
        "nomi",
        "mahsulot",
        "dori",
        "name",
        "product",
        "item",
    ),
    "quantity": (
        "количество",
        "кол-во",
        "кол.",
        "кол",
        "soni",
        "miqdori",
        "miqdor",
        "quantity",
        "qty",
    ),
    "unit": ("ед.", "ед", "ед. изм.", "ед.изм.", "единица", "o‘lchov", "unit"),
    "price": ("цена", "цена продажи", "narx", "narxi", "price", "unit price"),
    "discount": ("скидка", "сумма скидки", "chegirma", "discount"),
    "total": ("сумма", "итого", "сумма продажи", "к оплате", "summa", "jami", "total", "amount"),
    "payment": (
        "оплата",
        "тип оплаты",
        "вид оплаты",
        "способ оплаты",
        "to‘lov",
        "to‘lov turi",
        "payment",
        "payment method",
    ),
    "refund": ("возврат", "qaytarish", "refund", "return"),
    "refund_of": ("чек продажи", "исходный чек", "основание", "asos chek", "original receipt"),
    "series": ("серия", "seriya", "series", "batch", "lot"),
    "rx_number": (
        "рецепт",
        "номер рецепта",
        "№ рецепта",
        "retsept",
        "retsept raqami",
        "prescription",
        "prescription number",
    ),
    "branch": ("аптека", "филиал", "магазин", "склад", "dorixona", "filial", "branch", "pharmacy"),
}

PACK_WORDS = ("pack", "packs", "уп", "уп.", "упак", "упак.", "упаковка", "qadoq", "pk")
PART_WORDS = (
    "part",
    "parts",
    "блистер",
    "блист",
    "blister",
    "ампула",
    "амп",
    "ampula",
    "ampoule",
    "таблетка",
    "таб",
    "tabletka",
    "qism",
    "часть",
)
TRUE_WORDS = (
    "1",
    "true",
    "yes",
    "y",
    "x",
    "+",
    "да",
    "д",
    "ha",
    "возврат",
    "qaytarish",
    "refund",
    "return",
    "-1",
)


@dataclass
class Layout:
    """How a file is laid out: what an import profile says (the preview passes it unsaved)."""

    file_kind: str = "csv"
    encoding: str = ""
    delimiter: str = ""
    header_row: int = 1
    columns: dict | None = None
    date_format: str = ""
    default_unit: str = "pack"


@dataclass
class Row:
    """One sale line as the file wrote it, read and checked."""

    number: int  # the row in the file, for messages
    receipt: str
    sold_at: datetime
    register: str
    cashier: str
    code: str
    name: str
    quantity: Decimal  # positive, in `unit`
    unit: str  # pack | part
    price: Decimal
    discount: Decimal
    total: Decimal  # positive, after the discount
    payment: str
    refund: bool
    refund_of: str
    series: str
    rx_number: str
    branch: str


class RowError(ValueError):
    """A row that can't be read; the message says why, for people."""


# The file --------------------------------------------------------------------------------


def table(data: bytes, layout: Layout) -> tuple[list[str], list[tuple[int, list]]]:
    """The header row's names and every row after it (with its row number in the file)."""
    grid = _xlsx(data) if layout.file_kind == "xlsx" else _csv(data, layout)
    header_at = max(int(layout.header_row or 1), 1)
    if len(grid) < header_at:
        raise DomainError(
            _("The file has no row %(row)s with the column names.") % {"row": header_at}
        )
    headers = [_text(cell) for cell in grid[header_at - 1]]
    rows = []
    for offset, cells in enumerate(grid[header_at:], start=header_at + 1):
        if any(_text(cell) for cell in cells):
            rows.append((offset, list(cells)))
        if len(rows) > MAX_ROWS:
            raise DomainError(
                _("The file has more than %(count)s rows: split it into smaller files.")
                % {"count": MAX_ROWS}
            )
    return headers, rows


def _csv(data: bytes, layout: Layout) -> list[list]:
    text = _decode(data, layout.encoding)
    delimiter = layout.delimiter or _sniff(text)
    try:
        return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)]
    except csv.Error as exc:
        raise DomainError(_("The file isn't readable as CSV.")) from exc


def _decode(data: bytes, encoding: str) -> str:
    for candidate in (encoding,) if encoding else ENCODINGS:
        try:
            return data.decode(candidate)
        except UnicodeDecodeError, LookupError:
            continue
    raise DomainError(_("The file's text can't be read: pick its encoding in the profile."))


def _sniff(text: str) -> str:
    sample = "\n".join(text.splitlines()[:20])
    try:
        return csv.Sniffer().sniff(sample, delimiters=DELIMITERS).delimiter
    except csv.Error:
        first = text.splitlines()[0] if text else ""
        return max(DELIMITERS, key=first.count) if first else ";"


def _xlsx(data: bytes) -> list[list]:
    from openpyxl import load_workbook

    try:
        book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # anything openpyxl can't open is simply not a workbook
        raise DomainError(_("The file isn't readable as an Excel workbook.")) from exc
    try:
        sheet = book.worksheets[0]
        grid = []
        for values in sheet.iter_rows(values_only=True):
            grid.append(list(values))
            if len(grid) > MAX_ROWS + 50:
                break
        return grid
    finally:
        book.close()


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).replace(" ", " ").strip()


# The column map --------------------------------------------------------------------------


def guess(headers: list[str]) -> dict[str, str]:
    """A column map from the header names the file has, for the mapper to start from."""
    found: dict[str, str] = {}
    used: set[int] = set()
    normalized = [_key(header) for header in headers]
    for field, words in SYNONYMS.items():
        for index, header in enumerate(normalized):
            if index in used or not header:
                continue
            if header in words:
                found[field] = headers[index]
                used.add(index)
                break
    if "sold_at" in found:
        found.pop("date", None)
        found.pop("time", None)
    return found


def _key(header: str) -> str:
    return re.sub(r"\s+", " ", (header or "").strip().lower().replace("'", "‘"))


def positions(headers: list[str], columns: dict) -> dict[str, int]:
    """Each mapped field's column index. A value is a header name (any case) or a column
    number counted from 1."""
    names = {_key(header): index for index, header in enumerate(headers) if header}
    found: dict[str, int] = {}
    for field, where in (columns or {}).items():
        if field not in FIELDS or where in (None, ""):
            continue
        if isinstance(where, int) and not isinstance(where, bool):
            index = where - 1
        elif isinstance(where, str) and where.strip().isdigit() and _key(where) not in names:
            index = int(where.strip()) - 1
        else:
            index = names.get(_key(str(where)))
        if index is None or index < 0:
            raise DomainError(
                _("The file has no column %(column)s (for %(field)s).")
                % {"column": where, "field": field}
            )
        found[field] = index
    return found


FIELDS = (
    "receipt",
    "sold_at",
    "date",
    "time",
    "register",
    "cashier",
    "code",
    "name",
    "quantity",
    "unit",
    "price",
    "discount",
    "total",
    "payment",
    "refund",
    "refund_of",
    "series",
    "rx_number",
    "branch",
)
REQUIRED = ("receipt", "code", "quantity")


def check_columns(columns: dict, *, needs_branch: bool) -> None:
    """The column map names what an import can't do without."""
    named = {field for field, where in (columns or {}).items() if where not in (None, "")}
    if unknown := set(columns or {}) - set(FIELDS):
        raise DomainError(_("Unknown columns: %(names)s.") % {"names": ", ".join(sorted(unknown))})
    missing = [field for field in REQUIRED if field not in named]
    if "sold_at" not in named and "date" not in named:
        missing.append("sold_at")
    if "total" not in named and "price" not in named:
        missing.append("total")
    if needs_branch and "branch" not in named:
        missing.append("branch")
    if missing:
        raise DomainError(_("Say which column holds: %(fields)s.") % {"fields": ", ".join(missing)})


# Rows ------------------------------------------------------------------------------------


def rows(data: bytes, layout: Layout, *, timezone: str, needs_branch: bool):
    """Every readable sale line of the file, and the rows that couldn't be read:
    `(rows, problems)` with problems as `[{"row": 12, "message": "…"}]`."""
    headers, grid = table(data, layout)
    check_columns(layout.columns or {}, needs_branch=needs_branch)
    where = positions(headers, layout.columns or {})
    zone = ZoneInfo(timezone)
    found, problems = [], []
    for number, cells in grid:
        try:
            found.append(parse(number, cells, where, layout, zone))
        except RowError as exc:
            problems.append({"row": number, "message": str(exc)})
    return found, problems


def parse(number: int, cells: list, where: dict[str, int], layout: Layout, zone) -> Row:
    def cell(field: str):
        index = where.get(field)
        if index is None or index >= len(cells):
            return None
        return cells[index]

    def text(field: str, limit: int) -> str:
        return _text(cell(field))[:limit]

    receipt = text("receipt", 32)
    if not receipt:
        raise RowError(_("No receipt number."))
    code = text("code", 64)
    name = text("name", 200)
    if not code:
        raise RowError(_("No item code."))
    quantity = amount(cell("quantity"), field=_("quantity"))
    if quantity is None or quantity == 0:
        raise RowError(_("No quantity."))
    price = amount(cell("price"), field=_("price")) or Decimal(0)
    discount = abs(amount(cell("discount"), field=_("discount")) or Decimal(0))
    total = amount(cell("total"), field=_("total"))
    if total is None:
        total = (abs(price) * abs(quantity) - discount).quantize(CENT)
    refund = flag(cell("refund")) or quantity < 0 or total < 0
    sold_at = moment(
        cell("sold_at") if "sold_at" in where else cell("date"),
        cell("time"),
        layout.date_format,
        zone,
    )
    return Row(
        number=number,
        receipt=receipt,
        sold_at=sold_at,
        register=text("register", 20),
        cashier=text("cashier", 32),
        code=code,
        name=name or code,
        quantity=abs(quantity),
        unit=unit(cell("unit"), layout.default_unit),
        price=abs(price).quantize(CENT),
        discount=discount.quantize(CENT),
        total=abs(total).quantize(CENT),
        payment=text("payment", 50),
        refund=refund,
        refund_of=text("refund_of", 32),
        series=text("series", 40),
        rx_number=text("rx_number", 40),
        branch=text("branch", 100),
    )


def amount(value, *, field: str = "") -> Decimal | None:
    """A number as cash-register programs write it: 1234.5, "1 234,50", "(12)", "-3"."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise RowError(_("The %(field)s isn't a number.") % {"field": field})
    if isinstance(value, int | float | Decimal):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            raise RowError(_("The %(field)s isn't a number.") % {"field": field}) from None
    raw = re.sub(r"[\s  ]", "", str(value))
    negative = raw.startswith("(") and raw.endswith(")")
    raw = raw.strip("()")
    raw = raw.replace(",", "") if "," in raw and "." in raw else raw.replace(",", ".")
    raw = re.sub(r"[^\d.\-+]", "", raw)
    if not raw:
        return None
    try:
        number = Decimal(raw)
    except InvalidOperation:
        raise RowError(_("The %(field)s isn't a number.") % {"field": field}) from None
    if not number.is_finite() or abs(number) > Decimal("9999999999999"):
        raise RowError(_("The %(field)s isn't a number.") % {"field": field})
    return -number if negative else number


def moment(value, clock, date_format: str, zone) -> datetime:
    """When the line was sold, as an aware moment in the company's timezone."""
    when = _when(value, date_format)
    if when is None:
        raise RowError(_("The date isn't readable."))
    extra = _clock(clock)
    if extra is not None and isinstance(when, datetime) and when.time() == time(0, 0):
        when = datetime.combine(when.date(), extra)
    elif extra is not None and not isinstance(when, datetime):
        when = datetime.combine(when, extra)
    if not isinstance(when, datetime):
        when = datetime.combine(when, time(12, 0))
    if when.tzinfo is None:
        when = when.replace(tzinfo=zone)
    return when


def _when(value, date_format: str) -> datetime | date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        # An Excel serial date (days since 1899-12-30).
        if 20000 < value < 80000:
            return datetime(1899, 12, 30) + timedelta(days=float(value))
        return None
    raw = re.sub(r"\s+", " ", str(value).strip())
    for pattern in (date_format,) if date_format else DATE_FORMATS:
        try:
            return datetime.strptime(raw, pattern)
        except ValueError:
            continue
    return None


def _clock(value) -> time | None:
    if value is None or value == "":
        return None
    if isinstance(value, time):
        return value
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, float) and 0 <= value < 1:
        seconds = round(value * 86400)
        return time(seconds // 3600 % 24, seconds // 60 % 60, seconds % 60)
    raw = str(value).strip()
    for pattern in TIME_FORMATS:
        try:
            return datetime.strptime(raw, pattern).time()
        except ValueError:
            continue
    raise RowError(_("The time isn't readable."))


def unit(value, default: str) -> str:
    word = _text(value).lower()
    if word in PACK_WORDS:
        return "pack"
    if word in PART_WORDS:
        return "part"
    return default if default in ("pack", "part") else "pack"


def flag(value) -> bool:
    if value is None or isinstance(value, bool):
        return bool(value)
    return _text(value).lower() in TRUE_WORDS


# The column mapper's preview --------------------------------------------------------------


def preview(data: bytes, layout: Layout) -> dict:
    """The header names, the first rows as text and a proposed column map."""
    headers, grid = table(data, layout)
    return {
        "headers": headers,
        "rows": [[_text(value) for value in cells] for _number, cells in grid[:PREVIEW_ROWS]],
        "total_rows": len(grid),
        "guess": guess(headers),
    }
