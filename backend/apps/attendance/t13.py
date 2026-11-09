"""The timesheet as the standard T-13 form (the `attendance.t13` export): one row per person, a
column per day with its letter code (and the hours of a day at work), the month's totals.

The codes are the form's own, in Cyrillic: Я at work, В a day off or a holiday, ОТ leave, ДО an
excused (unpaid) absence, НН absent for no known reason.
"""

# ruff: noqa: RUF002 (the form's letter codes are Cyrillic on purpose)

from datetime import datetime

from django.utils.translation import gettext_lazy as _l
from rest_framework import serializers

from apps.attendance import clock, queries
from apps.members import scope
from apps.members.models import Membership

# The timesheet's cell codes (queries._cell) as the form's letters.
CODES = {
    "present": "Я",
    "late": "Я",
    "unscheduled": "Я",
    "open": "Я",
    "auto": "Я",
    "absent": "НН",
    "leave": "ОТ",
    "excused": "ДО",
    "holiday": "В",
    "off": "В",
    "planned": "",
}

COLUMNS = [
    ("number", _l("No"), "number"),
    ("person", _l("Person")),
    ("position", _l("Position")),
    *[(f"d{day:02d}", str(day)) for day in range(1, 32)],
    ("days", _l("Days at work"), "number"),
    ("hours", _l("Hours worked"), "number"),
    ("absent", _l("Absences"), "number"),
    ("leave", _l("Days on leave"), "number"),
]


class Params(serializers.Serializer):
    month = serializers.CharField(required=False, max_length=7)
    branch = serializers.IntegerField(required=False, allow_null=True)


def cell(value: dict) -> str:
    """ "Я 8.5" for a day at work, else the day's letter code ("В", "ОТ", "НН"…)."""
    code = CODES.get(value.get("code", ""), "")
    if code == "Я" and value.get("minutes"):
        return f"{code} {round(value['minutes'] / 60, 1):g}"
    return code


def rows(member: Membership, params: dict):
    """The month's rows for the people in the member's scope (a branch narrows it)."""
    company = member.company
    try:
        first = datetime.strptime((params.get("month") or "")[:7], "%Y-%m").date()
    except ValueError:
        first = clock.today(company).replace(day=1)
    sheet = queries.timesheet(
        company, first, branch_ids=scope.branch_ids(member), branch_id=params.get("branch")
    )
    for index, row in enumerate(sheet["people"], start=1):
        person = row["member"]
        out = {
            "number": index,
            "person": person["name"],
            "position": (person.get("position") or {}).get("name", ""),
        }
        days = minutes = absent = leave = 0
        for day in sheet["days"]:
            value = row["cells"].get(day)
            if value is None:
                continue
            text = cell(value)
            out[f"d{int(day[8:]):02d}"] = text
            if text.startswith("Я"):
                days += 1
                minutes += value.get("minutes") or 0
            elif text == "НН":
                absent += 1
            elif text == "ОТ":
                leave += 1
        out |= {"days": days, "hours": round(minutes / 60, 1), "absent": absent, "leave": leave}
        yield out
