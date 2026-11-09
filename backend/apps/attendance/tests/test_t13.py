"""The timesheet as the standard T-13 form (t13.rows): people by days, letter codes."""

import pytest

from apps.attendance import services, t13
from apps.attendance.tests.conftest import DAY, local
from apps.attendance.tests.factories import absent, shift_at
from apps.exports.registry import get_exporter

pytestmark = pytest.mark.django_db


def test_codes_hours_and_totals(staff, freeze):
    services.update_settings(staff.ali.company, by=None, require_location=False)
    shift_at(staff.ali, DAY)  # 09:00 to 18:00, an hour's break
    absent(shift_at(staff.bob, DAY))
    freeze(local(DAY, 8, 55))
    services.check_in(staff.ali)
    freeze(local(DAY, 18, 7))
    services.check_out(staff.ali)
    freeze(local(DAY, 20, 0))
    rows = {row["person"]: row for row in t13.rows(staff.manager, {"month": "2026-10"})}
    ali, bob = rows["Ali"], rows["Bob"]
    assert ali["d21"] == "Я 8.2"
    assert (ali["days"], ali["hours"], ali["absent"]) == (1, 8.2, 0)
    assert bob["d21"] == "НН" and bob["absent"] == 1
    assert rows["Vali"]["d21"] in ("В", "")
    assert ali["number"] >= 1 and ali["position"] == "Cashier"
    # The lead sees Chilonzor's people only.
    lead_rows = {row["person"] for row in t13.rows(staff.lead, {"month": "2026-10"})}
    assert "Sara" not in lead_rows and "Ali" in lead_rows


def test_cell_codes():
    assert t13.cell({"code": "present", "minutes": 480}) == "Я 8"
    assert t13.cell({"code": "late", "minutes": 450}) == "Я 7.5"
    assert t13.cell({"code": "leave", "minutes": 0}) == "ОТ"
    assert t13.cell({"code": "excused", "minutes": 0}) == "ДО"
    assert t13.cell({"code": "holiday", "minutes": 0}) == "В"
    assert t13.cell({"code": "planned", "minutes": 480}) == ""


def test_the_exporter_is_registered():
    exporter = get_exporter("attendance.t13")
    keys = [column.key for column in exporter.columns]
    assert keys[:3] == ["number", "person", "position"] and "d31" in keys and keys[-1] == "leave"
