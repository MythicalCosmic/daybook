"""The attendance reports as files and as exports (docs/DAVOMAT.md §1.6).

The five reports of `analytics` (people, departments, branches, days, punctuality) become:

- an Excel workbook (`xlsx()`): the organization, the report and its period on top, a bold
  header that stays in view, numbers as numbers (hours with one decimal, percents 0-100), the
  totals at the bottom, a filter on the header;
- a PDF (`pdf()`, `apps.core.pdf`, landscape A4): the same table with the key figures above it;
- the rows of the `attendance.report_*` exporters (`export_rows()`), so the Exports page can
  build them too (xlsx, csv, to Telegram), in the requester's branch scope.

Every format shows the same columns (`COLUMNS`) built by `table()`.
"""

from __future__ import annotations

import io
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone, translation
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _l
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from apps.attendance import analytics, clock
from apps.companies.models import Branch, Company
from apps.console.ranges import RangeError, parse_range
from apps.core import pdf as core_pdf
from apps.exports.registry import Column
from apps.members import scope
from apps.members.models import Department, Membership

# The exporter of each report (the exports registry, registered in hooks.py).
EXPORTERS = {
    "summary": "attendance.report_people",
    "departments": "attendance.report_departments",
    "branches": "attendance.report_branches",
    "trend": "attendance.report_trend",
    "punctuality": "attendance.report_punctuality",
}
LABELS = {
    "summary": _l("Attendance by person"),
    "departments": _l("Attendance by department"),
    "branches": _l("Attendance by branch"),
    "trend": _l("Attendance by day"),
    "punctuality": _l("Punctuality ranking"),
}

# The figures every grouped table shows, after its first columns.
FIGURE_COLUMNS = [
    Column("days_scheduled", _l("Days planned"), "number"),
    Column("days_present", _l("Days present"), "number"),
    Column("days_absent", _l("Absences"), "number"),
    Column("days_leave", _l("Days on leave"), "number"),
    Column("worked_hours", _l("Hours worked"), "number"),
    Column("late_count", _l("Late arrivals"), "number"),
    Column("late_minutes", _l("Late, min"), "number"),
    Column("early_leave_count", _l("Early leaves"), "number"),
    Column("overtime_hours", _l("Overtime, h"), "number"),
    Column("punctuality_percent", _l("On time, %"), "number"),
    Column("attendance_percent", _l("Attendance, %"), "number"),
]
COLUMNS: dict[str, list[Column]] = {
    "summary": [
        Column("person", _l("Person")),
        Column("position", _l("Position")),
        Column("department", _l("Department")),
        Column("branch", _l("Branch")),
        *FIGURE_COLUMNS,
    ],
    "departments": [
        Column("department", _l("Department")),
        Column("people", _l("People"), "number"),
        *FIGURE_COLUMNS,
    ],
    "branches": [
        Column("branch", _l("Branch")),
        Column("people", _l("People"), "number"),
        *FIGURE_COLUMNS,
    ],
    "trend": [
        Column("date", _l("Date"), "date"),
        Column("scheduled", _l("Planned"), "number"),
        Column("present", _l("Present"), "number"),
        Column("late", _l("Late"), "number"),
        Column("absent", _l("Absent"), "number"),
        Column("leave", _l("On leave"), "number"),
        Column("worked_hours", _l("Hours worked"), "number"),
        Column("punctuality_percent", _l("On time, %"), "number"),
    ],
    "punctuality": [
        Column("rank", _l("Rank"), "number"),
        Column("person", _l("Person")),
        Column("position", _l("Position")),
        Column("department", _l("Department")),
        Column("punctuality_percent", _l("On time, %"), "number"),
        Column("arrivals", _l("Arrivals"), "number"),
        Column("on_time", _l("On time"), "number"),
        Column("late_count", _l("Late arrivals"), "number"),
        Column("late_minutes", _l("Late, min"), "number"),
        Column("average_late_minutes", _l("Average lateness, min"), "number"),
    ],
}
# Columns whose values are hours or percents with one decimal (the rest are whole numbers).
DECIMAL_COLUMNS = {"worked_hours", "overtime_hours", "punctuality_percent", "attendance_percent"}


def hours(minutes: int) -> Decimal:
    return (Decimal(minutes) / Decimal(60)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _figures(row: dict) -> dict:
    return {
        "days_scheduled": row["days_scheduled"],
        "days_present": row["days_present"],
        "days_absent": row["days_absent"],
        "days_leave": row["days_leave"],
        "worked_hours": hours(row["worked_minutes"]),
        "late_count": row["late_count"],
        "late_minutes": row["late_minutes"],
        "early_leave_count": row["early_leave_count"],
        "overtime_hours": hours(row["overtime_minutes"]),
        "punctuality_percent": row["punctuality_percent"],
        "attendance_percent": row["attendance_percent"],
    }


def _ref(value: dict | None) -> str:
    return (value or {}).get("name", "")


def table(kind: str, data: dict) -> tuple[list[dict], dict | None]:
    """The report's rows keyed by `COLUMNS[kind]`, and its totals row (or None)."""
    totals = data.get("totals") or {}
    if kind == "summary":
        rows = [
            {
                "person": row["employee"]["name"],
                "position": _ref(row["employee"]["position"]),
                "department": _ref(row["employee"]["department"]),
                "branch": _ref(row["employee"]["branch"]),
                **_figures(row),
            }
            for row in data["rows"]
        ]
        return rows, {"person": _("Total"), **_figures(totals)}
    if kind in ("departments", "branches"):
        field = "department" if kind == "departments" else "branch"
        none = _("No department") if kind == "departments" else _("No branch")
        rows = [
            {field: _ref(row[field]) or none, "people": row["people"], **_figures(row)}
            for row in data["rows"]
        ]
        return rows, {field: _("Total"), "people": totals.get("people", 0), **_figures(totals)}
    if kind == "trend":
        rows = [
            {
                "date": date.fromisoformat(day["date"]),
                "scheduled": day["scheduled"],
                "present": day["present"],
                "late": day["late"],
                "absent": day["absent"],
                "leave": day["leave"],
                "worked_hours": hours(day["worked_minutes"]),
                "punctuality_percent": day["punctuality_percent"],
            }
            for day in data["days"]
        ]
        return rows, {
            "date": _("Total"),
            "scheduled": totals.get("days_scheduled", 0),
            "present": totals.get("days_present", 0),
            "late": totals.get("late_count", 0),
            "absent": totals.get("days_absent", 0),
            "leave": totals.get("days_leave", 0),
            "worked_hours": hours(totals.get("worked_minutes", 0)),
            "punctuality_percent": totals.get("punctuality_percent"),
        }
    rows = [
        {
            "rank": row["rank"],
            "person": row["employee"]["name"],
            "position": _ref(row["employee"]["position"]),
            "department": _ref(row["employee"]["department"]),
            "punctuality_percent": row["punctuality_percent"],
            "arrivals": row["arrivals"],
            "on_time": row["on_time"],
            "late_count": row["late_count"],
            "late_minutes": row["late_minutes"],
            "average_late_minutes": row["average_late_minutes"],
        }
        for row in data["rows"]
    ]
    return rows, {"person": _("Average"), "punctuality_percent": data.get("average")}


# What was asked ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Ask:
    """A report request: the period and the filters, already inside the caller's scope."""

    start: date
    end: date
    branch_ids: list[int] | None
    department_ids: list[int] | None
    branches: list[int]
    departments: list[int]


def narrowed(member_scope: list[int] | None, picked: list[int]) -> list[int] | None:
    """The branch filter inside the caller's scope (never wider than it)."""
    if not picked:
        return member_scope
    return [pk for pk in picked if member_scope is None or pk in member_scope]


def build(company: Company, kind: str, ask: Ask, *, now=None) -> dict:
    report = analytics.build(
        company,
        ask.start,
        ask.end,
        branch_ids=ask.branch_ids,
        department_ids=ask.department_ids,
        now=now,
    )
    return analytics.BUILDERS[kind](report)


def _ids(value) -> list[int]:
    values = value if isinstance(value, list | tuple) else [value] if value else []
    return [int(part) for item in values for part in str(item).split(",") if part.isdigit()]


def ask_from_params(member: Membership, params: dict, now=None) -> Ask:
    """A request from an export's saved parameters (tolerant: anything unusable falls back to
    this month and no filter)."""
    company = member.company
    flat = {
        key: (value[0] if isinstance(value, list) and value else value)
        for key, value in (params or {}).items()
        if key in ("from", "to", "preset")
    }
    try:
        period = parse_range(flat, company, now or timezone.now())
    except RangeError:
        period = parse_range({}, company, now or timezone.now())
    branches = _ids((params or {}).get("branch"))
    departments = _ids((params or {}).get("department"))
    return Ask(
        period.start,
        period.end,
        narrowed(scope.branch_ids(member), branches),
        analytics.departments_below(company, departments),
        branches,
        departments,
    )


def export_rows(kind: str) -> Callable[[Membership, dict], Iterable[dict]]:
    """The rows function of report `kind`'s exporter (the exports registry)."""

    def rows(member: Membership, params: dict) -> Iterable[dict]:
        data = build(member.company, kind, ask_from_params(member, params))
        found, totals = table(kind, data)
        yield from found
        # The days' totals would put a word in the date column, which those files refuse.
        if totals and found and kind != "trend":
            yield totals

    return rows


# Files ------------------------------------------------------------------------------------


def filename(kind: str, company: Company, ask: Ask, extension: str) -> str:
    """ "davomat-namuna-mchj-2026-11-01-2026-11-30.xlsx"."""
    label = slugify(str(LABELS[kind])) or "attendance"
    who = slugify(company.name)[:40] or "company"
    return f"{label}-{who}-{ask.start.isoformat()}-{ask.end.isoformat()}.{extension}"


def _day(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def _subtitle(data: dict, ask: Ask) -> str:
    period = f"{_day(ask.start)}–{_day(ask.end)}"
    until = data.get("counted_until")
    if until and until < ask.end.isoformat():
        return _("%(period)s, counted until %(day)s") % {
            "period": period,
            "day": _day(date.fromisoformat(until)),
        }
    return period


def filters_line(company: Company, ask: Ask) -> str:
    """ "Branches: Chilonzor · Departments: Sales", or "" without filters."""
    parts = []
    if ask.branches:
        names = Branch.objects.filter(company=company, pk__in=ask.branches).order_by(
            "order", "name"
        )
        parts.append(_("Branches: %(names)s") % {"names": ", ".join(b.name for b in names)})
    if ask.departments:
        names = Department.objects.filter(company=company, pk__in=ask.departments).order_by("name")
        parts.append(_("Departments: %(names)s") % {"names": ", ".join(d.name for d in names)})
    return " · ".join(parts)


HEADER_FILL = PatternFill("solid", fgColor="EEF1F5")
TITLE_FONT = Font(bold=True, size=14)
BOLD = Font(bold=True)
MUTED = Font(color="667085")
THIN = Side(style="thin", color="C9CED6")
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _cell_value(column: Column, value):
    if value is None:
        return None
    if column.kind == "number" and not isinstance(value, str):
        return value
    if column.kind == "date" and isinstance(value, date):
        return value
    return str(value)


def xlsx(kind: str, data: dict, *, company: Company, ask: Ask) -> bytes:
    columns = COLUMNS[kind]
    rows, totals = table(kind, data)
    book = Workbook()
    sheet = book.active
    sheet.title = str(LABELS[kind])[:31]
    sheet["A1"] = company.name
    sheet["A1"].font = TITLE_FONT
    sheet["A2"] = str(LABELS[kind])
    sheet["A2"].font = BOLD
    sheet["A3"] = _subtitle(data, ask)
    sheet["A3"].font = MUTED
    line = filters_line(company, ask)
    if line:
        sheet["A4"] = line
        sheet["A4"].font = MUTED
    header_row = 6
    for index, column in enumerate(columns, start=1):
        cell = sheet.cell(row=header_row, column=index, value=str(column.label))
        cell.font = BOLD
        cell.fill = HEADER_FILL
        cell.border = Border(bottom=THIN)
        cell.alignment = Alignment(
            horizontal="right" if column.kind == "number" else "left",
            vertical="center",
            wrap_text=True,
        )
    widths = [max(10, min(36, len(str(column.label)) + 2)) for column in columns]
    body = [*rows, totals] if totals and rows else rows
    for offset, row in enumerate(body, start=header_row + 1):
        is_total = row is totals
        for index, column in enumerate(columns, start=1):
            value = _cell_value(column, row.get(column.key))
            cell = sheet.cell(row=offset, column=index, value=value)
            if isinstance(value, str):
                cell.data_type = "s"  # never a formula, whatever the text starts with
                widths[index - 1] = max(widths[index - 1], min(36, len(value) + 2))
            if column.kind == "date" and isinstance(value, date):
                cell.number_format = "DD.MM.YYYY"
            elif column.key in DECIMAL_COLUMNS:
                cell.number_format = "0.0"
            elif column.kind == "number":
                cell.number_format = "0"
            if is_total:
                cell.font = BOLD
                cell.border = Border(top=THIN)
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.row_dimensions[header_row].height = 30
    sheet.freeze_panes = sheet.cell(row=header_row + 1, column=1)
    if rows:
        last = get_column_letter(len(columns))
        sheet.auto_filter.ref = f"A{header_row}:{last}{header_row + len(rows)}"
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _decimal(value) -> str:
    """One decimal, with a decimal comma in Uzbek and Russian: "83,3"."""
    text = f"{Decimal(str(value)):.1f}"
    return text if (translation.get_language() or "uz") == "en" else text.replace(".", ",")


def _shown(column: Column, value, blank: str = "—") -> str:
    if value is None or value == "":
        return blank if column.kind == "number" else ""
    if isinstance(value, date):
        return _day(value)
    if column.key in DECIMAL_COLUMNS:
        return _decimal(value)
    return str(value)


def _cells(columns: list[Column], row: dict, blank: str = "—") -> list[dict]:
    return [
        {"text": _shown(column, row.get(column.key), blank), "num": column.kind == "number"}
        for column in columns
    ]


def kpis(kind: str, data: dict) -> list[tuple[str, str]]:
    """The figures printed above the table."""
    totals = data.get("totals") or {}

    def pct(value) -> str:
        return "—" if value is None else f"{_decimal(value)}%"

    shown = [
        (_("Attendance"), pct(totals.get("attendance_percent"))),
        (_("On time"), pct(totals.get("punctuality_percent"))),
        (_("Late arrivals"), str(totals.get("late_count", 0))),
        (_("Absences"), str(totals.get("days_absent", 0))),
        (_("Hours worked"), _decimal(hours(totals.get("worked_minutes", 0)))),
    ]
    if totals.get("people"):
        shown.insert(0, (_("People"), str(totals["people"])))
    return shown


def pdf(kind: str, data: dict, *, company: Company, ask: Ask, language: str) -> bytes:
    with translation.override(language):
        columns = COLUMNS[kind]
        rows, totals = table(kind, data)
        context = {
            "company": company,
            "title": str(LABELS[kind]),
            "subtitle": _subtitle(data, ask),
            "filters": filters_line(company, ask),
            "printed_on": clock.local(company, timezone.now()).strftime("%d.%m.%Y %H:%M"),
            "logo_src": core_pdf.image_src(company.logo) if company.logo else "",
            "kpis": kpis(kind, data),
            "columns": [
                {"label": str(column.label), "numeric": column.kind == "number"}
                for column in columns
            ],
            "rows": [_cells(columns, row) for row in rows],
            "totals": _cells(columns, totals, blank="") if totals and rows else None,
            "empty": not rows,
        }
    return core_pdf.render_pdf("attendance/report.html", context, language=language)
