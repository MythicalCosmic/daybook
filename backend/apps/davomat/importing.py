"""Employees from a spreadsheet (XLSX or CSV), with a dry run first, and back out to one.

The columns are found by their header (English, Uzbek or Russian, as our own export writes
them): first name, last name (or one full-name column), phone, position, department, branch,
face number, hire date. A row whose face number is someone's already updates that employee;
the rest become new employees. Positions and departments are found by name (made when missing,
for someone allowed to); a branch must exist (by name or code). A dry run says what would
happen, row by row, and changes nothing.

    import_employees(company, upload, *, by, dry_run=True) -> dict
    export_rows(company, members) -> (header, rows)       the same columns, ready to re-import
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from apps.companies.models import Branch, Company
from apps.core.exceptions import DomainError
from apps.core.uploads import accept_document
from apps.davomat import queries
from apps.davomat.audit_actions import DavomatAction
from apps.davomat.models import Employee
from apps.faceid import hikvision
from apps.faceid.models import FaceLink
from apps.members import departments as structure
from apps.members import scope
from apps.members import services as members
from apps.members.models import Department, Membership, Position
from apps.members.permissions import Perm

MAX_ROWS = 2000
# Rows described back at most (the counts cover every row).
MAX_REPORTED = 500
FIELDS = (
    "first_name",
    "last_name",
    "full_name",
    "phone",
    "position",
    "department",
    "branch",
    "face_number",
    "hire_date",
)
# Header words each field is known by: lower case, no spaces, ’ for the apostrophe.
SYNONYMS = {
    "first_name": ("firstname", "first", "name", "ism", "ismi", "имя"),
    "last_name": ("lastname", "last", "surname", "familiya", "familiyasi", "фамилия"),
    "full_name": ("fullname", "fio", "f.i.o.", "f.i.sh.", "fish", "ism-familiya", "фио", "ф.и.о."),
    "phone": ("phone", "mobile", "telefon", "telefonraqami", "телефон", "номертелефона"),
    "position": ("position", "jobtitle", "title", "lavozim", "lavozimi", "должность"),
    "department": ("department", "bo‘lim", "bolim", "bo’lim", "отдел", "подразделение"),
    "branch": ("branch", "location", "filial", "joy", "филиал", "локация"),
    "face_number": (
        "facenumber",
        "faceid",
        "faceidnumber",
        "employeeno",
        "employeenumber",
        "terminalnumber",
        "id",
        "raqam",
        "faceidraqami",
        "terminalraqami",
        "табельныйномер",
        "номер",
        "номерfaceid",
    ),
    "hire_date": (
        "hiredate",
        "hired",
        "startdate",
        "ishgakirgan",
        "ishgakirgansana",
        "датаприема",
        "датаприёма",
    ),
}


def _key(text) -> str:
    return "".join(str(text or "").casefold().split()).replace("'", "’").replace("`", "’")


def header_labels() -> dict[str, str]:
    """The export's column headers in the current language (the import knows them too)."""
    return {
        "first_name": _("First name"),
        "last_name": _("Last name"),
        "phone": _("Phone"),
        "position": _("Position"),
        "department": _("Department"),
        "branch": _("Branch"),
        "face_number": _("Face ID number"),
        "hire_date": _("Hire date"),
        "status": _("Status"),
        "left_on": _("Left on"),
        "schedule": _("Schedule"),
        "telegram": _("Telegram"),
    }


# Reading ------------------------------------------------------------------------------------


def read_table(upload) -> tuple[list[str], list[list[str]]]:
    """The header and the rows of an XLSX or CSV upload (checked by its content, never by its
    name), every cell as text."""
    checked = accept_document(upload, allowed=("xlsx", "csv"))
    data = checked.read()
    if checked.name.endswith(".xlsx"):
        from openpyxl import load_workbook

        try:
            book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as exc:  # a damaged workbook
            raise DomainError(_("The spreadsheet can't be read. Save it again and retry.")) from exc
        sheet = book.worksheets[0]
        rows = []
        for row in sheet.iter_rows(values_only=True):
            rows.append(["" if cell is None else _cell(cell) for cell in row])
            if len(rows) > MAX_ROWS + 1:
                break
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
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.reader(io.StringIO(text), dialect))
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
    """{column header: field} for the headers that name a field (each field once)."""
    labels = {_key(label): field for field, label in header_labels().items() if field in FIELDS}
    found: dict[str, str] = {}
    taken: set[str] = set()
    for column in header:
        key = _key(column)
        field = labels.get(key) or next(
            (name for name in FIELDS if key == name.replace("_", "") or key in SYNONYMS[name]),
            None,
        )
        if field is not None and field not in taken:
            found[column] = field
            taken.add(field)
    return found


def _date(text: str) -> date | None:
    text = (text or "").strip()
    if not text:
        return None
    for pattern in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise DomainError(_("Write dates as 2026-11-10 or 10.11.2026."))


# Importing ----------------------------------------------------------------------------------


class _Lookups:
    """The company's positions, departments and branches by name, filled as rows make them."""

    def __init__(self, company: Company):
        self.positions = {
            _key(position.name): position
            for position in Position.objects.for_company(company).filter(is_active=True)
        }
        self.departments = {
            _key(department.name): department
            for department in Department.objects.for_company(company)
        }
        self.branches: dict[str, Branch] = {}
        for branch in Branch.objects.for_company(company).filter(is_active=True):
            self.branches.setdefault(_key(branch.name), branch)
            if branch.code:
                self.branches.setdefault(_key(branch.code), branch)
        self.numbers = {
            link.number_key: link
            for link in FaceLink.objects.for_company(company).select_related("membership")
        }


def import_employees(company: Company, upload, *, by: Membership, dry_run: bool = True) -> dict:
    """Create and update employees from a spreadsheet. Returns what happened (or, on a dry
    run, what would): counts, the columns found, and one entry per row."""
    from apps.davomat import services

    services._require(by, Perm.MEMBERS_MANAGE)
    header, rows = read_table(upload)
    mapping = guess_mapping(header)
    fields = set(mapping.values())
    if not fields & {"first_name", "full_name"}:
        raise DomainError(_("No column with the first name (or the full name) was found."))
    index = {header.index(column): field for column, field in mapping.items()}
    found = _Lookups(company)
    may_add_positions = by.has_perm(Perm.POSITIONS_MANAGE)
    may_add_dept = structure.may_edit_structure(by)
    result = {
        "dry_run": dry_run,
        "columns": header,
        "mapping": mapping,
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "rows": [],
    }
    seen_numbers: set[str] = set()
    allowed = scope.branch_ids(by)
    for number, row in enumerate(rows, start=2):
        values = {
            field: row[position] if position < len(row) else "" for position, field in index.items()
        }
        entry = {"row": number, "action": "skip", "name": "", "employee_id": None, "errors": []}
        try:
            fields_, match = _row(values, found, seen_numbers)
            entry["name"] = " ".join(filter(None, (fields_["first_name"], fields_["last_name"])))
            _check_scope(by, allowed, fields_, match)
            for kind, may_add in (("position", may_add_positions), ("department", may_add_dept)):
                wanted = fields_.pop(f"_{kind}_new", "")
                if wanted and not may_add:
                    raise DomainError(UNKNOWN[kind]() % {"name": wanted})
                if wanted and not dry_run:
                    fields_[kind] = _make(company, kind, wanted, by, found)
            entry["action"] = "update" if match is not None else "create"
            entry["employee_id"] = match.pk if match is not None else None
            if not dry_run:
                with transaction.atomic():
                    if match is None:
                        made = services.create_employee(
                            company, by=by, source=Employee.Source.IMPORT, **fields_
                        )
                        entry["employee_id"] = made.pk
                    else:
                        _update(match, by, fields_)
        except (DomainError, PermissionDenied) as exc:
            entry["action"], entry["errors"] = "skip", [str(exc)]
        except IntegrityError:  # saved by someone else a moment ago (a number, a username)
            entry["action"] = "skip"
            entry["errors"] = [_("This row clashes with a change made a moment ago. Try again.")]
        result[{"create": "created", "update": "updated", "skip": "skipped"}[entry["action"]]] += 1
        result["rows"].append(entry)
    result["rows"] = result["rows"][:MAX_REPORTED]
    if not dry_run and (result["created"] or result["updated"]):
        services._audit(
            by,
            DavomatAction.EMPLOYEES_IMPORTED,
            company,
            created=result["created"],
            updated=result["updated"],
            skipped=result["skipped"],
        )
        services._bump(company.pk, services.PULSE_EMPLOYEES, services.PEOPLE)
    return result


UNKNOWN = {
    "position": lambda: _("Unknown position: %(name)s"),
    "department": lambda: _("Unknown department: %(name)s"),
}


def _check_scope(by: Membership, allowed: list[int] | None, fields: dict, match) -> None:
    """A manager imports only into their branches, and updates only their branches' people."""
    if allowed is None:
        return
    if match is not None and not queries.in_scope(by, match):
        raise DomainError(_("%(name)s works at a branch you don't manage.") % {"name": match})
    branches = fields.get("branches")
    if match is None and not branches:
        raise DomainError(_("Pick the branch they work at."))
    if branches and any(branch.pk not in allowed for branch in branches):
        raise DomainError(_("You can only give the branches you manage."))


def _row(values: dict, found: _Lookups, seen: set[str]):
    """The create/update fields of one row, and the employee it updates (None: a new one)."""
    from apps.davomat import services

    first = values.get("first_name", "").strip()
    last = values.get("last_name", "").strip()
    if not first and values.get("full_name"):
        first, last = services.split_name(values["full_name"])
    if not first:
        raise DomainError(_("A first name is required."))
    fields = {"first_name": first, "last_name": last}
    if "phone" in values:
        fields["phone"] = services.clean_phone(values["phone"])
    for kind, lookup in (("position", found.positions), ("department", found.departments)):
        name = " ".join(values.get(kind, "").split())
        if not name:
            continue
        match = lookup.get(_key(name))
        if match is not None:
            fields[kind] = match
        else:
            fields[f"_{kind}_new"] = name[:100]
    branch_name = values.get("branch", "").strip()
    if branch_name:
        branch = found.branches.get(_key(branch_name))
        if branch is None:
            raise DomainError(_("Unknown branch: %(name)s") % {"name": branch_name})
        fields["branches"] = [branch]
    if values.get("hire_date"):
        fields["hire_date"] = _date(values["hire_date"])
    numbers = [part.strip() for part in values.get("face_number", "").replace(";", ",").split(",")]
    numbers = [part for part in numbers if part]
    match = None
    for each in numbers:
        key = hikvision.number_key(each)
        if not key:
            raise DomainError(_("Give the Employee No from the terminal."))
        if key in seen:
            raise DomainError(_("The face number repeats an earlier row."))
        seen.add(key)
        link = found.numbers.get(key)
        if link is None:
            continue
        if link.membership_id is None:
            raise DomainError(_("Number %(number)s is set aside.") % {"number": each})
        if match is not None and link.membership_id != match.pk:
            raise DomainError(_("These numbers belong to different people."))
        match = link.membership
    if match is not None and not queries.is_employee(match):
        raise DomainError(_("Number %(number)s belongs to a user.") % {"number": numbers[0]})
    if match is not None and match.status not in queries.CURRENT:
        raise DomainError(_("%(name)s has left: take them back first.") % {"name": match})
    fields["face_numbers"] = numbers
    return fields, match


def _make(company, kind: str, name: str, by: Membership, found: _Lookups):
    if kind == "position":
        made = members.save_position(company, by=by, name=name)
        found.positions[_key(name)] = made
        return made
    made = structure.create_department(company, by=by, name=name)
    found.departments[_key(name)] = made
    return made


def _update(match: Membership, by: Membership, fields: dict) -> None:
    from apps.davomat import services

    numbers = fields.pop("face_numbers")
    current = [link.employee_no for link in FaceLink.objects.filter(membership=match)]
    keys = {hikvision.number_key(number) for number in current}
    extra = [number for number in numbers if hikvision.number_key(number) not in keys]
    services.update_employee(
        match,
        by=by,
        first_name=fields.get("first_name"),
        last_name=fields.get("last_name"),
        phone=fields.get("phone"),
        position=fields.get("position", services.UNSET),
        department=fields.get("department", services.UNSET),
        branches=fields.get("branches"),
        hire_date=fields.get("hire_date", services.UNSET),
        face_numbers=[*current, *extra] if extra else None,
    )


# Exporting ----------------------------------------------------------------------------------

EXPORT_FIELDS = (
    "first_name",
    "last_name",
    "phone",
    "position",
    "department",
    "branch",
    "face_number",
    "hire_date",
    "status",
    "left_on",
    "schedule",
    "telegram",
)
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def export_rows(company: Company, people: list[Membership], dates: dict) -> list[list]:
    """One row per employee, the header first, in the import's columns (then the rest)."""
    labels = header_labels()
    rows: list[list] = [[labels[field] for field in EXPORT_FIELDS]]
    for person in people:
        hired, left = dates.get(person.pk, (None, None))
        branches = sorted(person.branches.all(), key=lambda branch: (branch.order, branch.pk))
        home = person.home_branch or (branches[0] if branches else None)
        schedule = getattr(person, "work_schedule", None)
        rows.append(
            [
                person.first_name,
                person.last_name,
                person.user.phone,
                person.position.name if person.position_id else "",
                person.department.name if person.department_id else "",
                home.name if home else "",
                ", ".join(sorted(link.employee_no for link in person.face_links.all())),
                hired,
                _("Left") if person.status == Membership.Status.LEFT else _("Active"),
                left if person.status == Membership.Status.LEFT else None,
                schedule.schedule.name if schedule and schedule.schedule_id else "",
                _("Yes") if person.user.telegram_id else _("No"),
            ]
        )
    return rows


def as_csv(rows: list[list]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    for row in rows:
        writer.writerow([_safe_text(value) for value in row])
    # The BOM makes Excel read o‘zbek and Cyrillic text right.
    return buffer.getvalue().encode("utf-8-sig")


def as_xlsx(rows: list[list], *, title: str) -> bytes:
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    book = Workbook(write_only=True)
    sheet = book.create_sheet(title=title[:31] or "Sheet")
    sheet.freeze_panes = "A2"
    widths = [14, 16, 16, 18, 18, 18, 16, 12, 10, 12, 18, 10]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    bold = Font(bold=True)
    for number, row in enumerate(rows):
        cells = []
        for value in row:
            if isinstance(value, date):
                cell = WriteOnlyCell(sheet, value=value)
                cell.number_format = "yyyy-mm-dd"
            else:
                cell = WriteOnlyCell(sheet, value="" if value is None else str(value))
                cell.data_type = "s"  # never a formula, whatever the text starts with
            if number == 0:
                cell.font = bold
            cells.append(cell)
        sheet.append(cells)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _safe_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    text = str(value)
    return f"'{text}" if text.startswith(FORMULA_START) else text
