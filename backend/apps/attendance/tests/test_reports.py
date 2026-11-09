"""The report endpoints `attendance/reports/{summary,departments,branches,trend,punctuality}/`
(docs/DAVOMAT.md §1.6): figures, scope, permissions, the files and the exporters. The week is
`report_week`'s."""

import io

import pytest
from openpyxl import load_workbook

from apps.attendance import reports
from apps.attendance.tests.report_week import FRI, MON, NOW, make_week
from apps.audit.models import AuditLog
from apps.exports.registry import get_exporter

pytestmark = pytest.mark.django_db

PERIOD = {"from": MON.isoformat(), "to": FRI.isoformat()}
KINDS = ("summary", "departments", "branches", "trend", "punctuality")


def url(company, kind):
    return f"/api/v1/owner/companies/{company.pk}/attendance/reports/{kind}/"


@pytest.fixture
def week(staff, chilonzor, yunusobod, freeze):
    made = make_week(staff, chilonzor, yunusobod)
    freeze(NOW)
    return made


@pytest.fixture
def owner(week, member):
    return member(week.ali.company, "Owner", first_name="Dilnoza")


def first_names(rows):
    return [row["employee"]["name"].split()[0] for row in rows]


@pytest.mark.parametrize("kind", KINDS)
def test_every_report_answers_in_its_shape(owner_api, week, kind):
    response = owner_api(week.manager).get(url(week.ali.company, kind), PERIOD)

    assert response.status_code == 200, response.content
    data = response.json()
    assert data["range"] == {"from": "2026-10-19", "to": "2026-10-23"}
    assert data["counted_until"] == "2026-10-23"
    assert data["totals"]["days_scheduled"] == 13
    assert data["totals"]["people"] == 4


def test_the_summary_golden_numbers(owner_api, week):
    data = owner_api(week.manager).get(url(week.ali.company, "summary"), PERIOD).json()

    assert first_names(data["rows"]) == ["Ali", "Bob", "Sara", "Vali"]
    ali = data["rows"][0]
    assert (ali["days_present"], ali["days_absent"], ali["days_leave"]) == (3, 1, 1)
    assert (ali["late_count"], ali["late_minutes"], ali["punctuality_percent"]) == (1, 20, 66.7)
    assert data["totals"]["worked_minutes"] == 4772
    assert data["totals"]["attendance_percent"] == 83.3


def test_the_ranking_and_the_trend(owner_api, week):
    client = owner_api(week.manager)
    ranking = client.get(url(week.ali.company, "punctuality"), PERIOD).json()
    trend = client.get(url(week.ali.company, "trend"), PERIOD).json()

    assert [(row["rank"], row["employee"]["name"].split()[0]) for row in ranking["rows"]] == [
        (1, "Bob"),
        (2, "Ali"),
        (3, "Sara"),
        (4, "Vali"),
    ]
    assert ranking["average"] == 70.0
    assert [day["present"] for day in trend["days"]] == [4, 4, 1, 1, 1]


def test_the_summary_compares_with_the_period_before(owner_api, week):
    client = owner_api(week.manager)
    company = week.ali.company

    # Thursday and Friday against Tuesday and Wednesday.
    data = client.get(
        url(company, "summary"), {"from": "2026-10-22", "to": "2026-10-23", "compare": "prev"}
    ).json()

    assert data["compare"] == {"from": "2026-10-20", "to": "2026-10-21"}
    previous = data["previous"]
    assert (previous["days_scheduled"], previous["days_present"]) == (6, 5)
    assert (previous["days_absent"], previous["late_count"], previous["people"]) == (2, 2, 4)
    # Without a comparison the keys say so; other reports never carry them.
    plain = client.get(url(company, "summary"), PERIOD).json()
    assert plain["compare"] is None and plain["previous"] is None
    trend = client.get(url(company, "trend"), {**PERIOD, "compare": "prev"}).json()
    assert "previous" not in trend


def test_this_month_by_default(owner_api, week):
    data = owner_api(week.manager).get(url(week.ali.company, "summary")).json()

    assert data["range"] == {"from": "2026-10-01", "to": "2026-10-23"}
    assert data["totals"]["days_scheduled"] == 13


def test_a_bad_period_or_format_is_refused(owner_api, week):
    client = owner_api(week.manager)
    company = week.ali.company

    assert client.get(url(company, "summary"), {"from": "2026-13-01"}).status_code == 400
    assert client.get(url(company, "summary"), {**PERIOD, "format": "docx"}).status_code == 400
    assert client.get(url(company, "summary"), {**PERIOD, "department": "x"}).status_code == 400


def test_branch_scope_and_the_branch_filter(owner_api, week, chilonzor, yunusobod):
    company = week.ali.company
    lead = owner_api(week.lead)  # attendance.view for Chilonzor only

    mine = lead.get(url(company, "summary"), PERIOD).json()
    assert first_names(mine["rows"]) == ["Ali", "Bob", "Vali"]
    assert [
        row["branch"]["name"] for row in lead.get(url(company, "branches"), PERIOD).json()["rows"]
    ] == ["Chilonzor"]
    # Another branch is never added to the scope by asking for it.
    asked = lead.get(url(company, "summary"), {**PERIOD, "branch": yunusobod.pk}).json()
    assert asked["rows"] == [] and asked["totals"]["people"] == 0

    picked = owner_api(week.manager).get(
        url(company, "summary"), {**PERIOD, "branch": yunusobod.pk}
    )
    assert first_names(picked.json()["rows"]) == ["Sara"]


def test_the_department_filter(owner_api, week):
    data = (
        owner_api(week.manager)
        .get(url(week.ali.company, "summary"), {**PERIOD, "department": week.sales.pk})
        .json()
    )

    assert first_names(data["rows"]) == ["Ali", "Vali"]


def test_another_company_and_missing_permissions(owner_api, week, other_company, member):
    stranger = member(other_company, "Owner")
    assert owner_api(stranger).get(url(week.ali.company, "summary"), PERIOD).status_code == 404

    cashier = owner_api(week.ali)  # an employee: no attendance.view, no dashboard
    assert cashier.get(url(week.ali.company, "summary"), PERIOD).status_code == 403


def test_the_reports_need_the_module(owner_api, week):
    company = week.ali.company
    company.features = []
    company.save(update_fields=["features"])

    assert owner_api(week.manager).get(url(company, "trend"), PERIOD).status_code == 403


def test_nothing_hidden_leaks_into_a_row(owner_api, week):
    data = owner_api(week.manager).get(url(week.ali.company, "summary"), PERIOD).json()

    assert set(data["rows"][0]["employee"]) == {
        "id",
        "name",
        "photo_url",
        "position",
        "department",
        "branch",
    }
    for row in data["rows"]:
        assert not {"salary", "phone", "telegram_id", "pinfl"} & set(row)


def test_the_excel_file(owner_api, owner, week):
    response = owner_api(owner).get(url(week.ali.company, "summary"), {**PERIOD, "format": "xlsx"})

    assert response.status_code == 200
    assert response["Content-Type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert response["Content-Disposition"].startswith('attachment; filename="attendance-by-person-')
    assert response["Content-Disposition"].endswith('-2026-10-19-2026-10-23.xlsx"')
    sheet = load_workbook(io.BytesIO(response.content)).active
    values = [[cell.value for cell in row] for row in sheet.iter_rows()]
    assert values[0][0] == week.ali.company.name
    assert values[1][0] == "Attendance by person"
    assert values[2][0] == "19.10.2026–23.10.2026"
    header = values[5]
    assert header[:5] == ["Person", "Position", "Department", "Branch", "Days planned"]
    assert [row[0].split()[0] for row in values[6:10]] == ["Ali", "Bob", "Sara", "Vali"]
    total = values[10]
    assert total[0] == "Total"
    assert total[header.index("Days planned")] == 13
    assert float(total[header.index("Hours worked")]) == round(4772 / 60, 1)
    assert total[header.index("On time, %")] == 70.0
    assert sheet.freeze_panes == "A7"
    log = AuditLog.objects.get(action="attendance.report_exported")
    assert log.details["report"] == "summary" and log.details["format"] == "xlsx"


def test_text_never_becomes_a_formula(owner_api, owner, week):
    week.ali.first_name = "=HYPERLINK(1)"
    week.ali.save(update_fields=["first_name"])

    response = owner_api(owner).get(url(week.ali.company, "summary"), {**PERIOD, "format": "xlsx"})

    sheet = load_workbook(io.BytesIO(response.content)).active
    cells = [
        cell
        for row in sheet.iter_rows()
        for cell in row
        if cell.value and str(cell.value).startswith("=")
    ]
    assert cells and all(cell.data_type == "s" for cell in cells)


def test_the_pdf_file(owner_api, owner, week):
    response = owner_api(owner).get(url(week.ali.company, "branches"), {**PERIOD, "format": "pdf"})

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert response["Content-Disposition"].endswith('.pdf"')


def test_files_need_data_export(owner_api, week):
    # The Manager role sees attendance but may not export data.
    response = owner_api(week.manager).get(
        url(week.ali.company, "summary"), {**PERIOD, "format": "xlsx"}
    )

    assert response.status_code == 403
    assert not AuditLog.objects.filter(action="attendance.report_exported").exists()


def test_the_accountant_exports_with_data_export(owner_api, week):
    response = owner_api(week.accountant).get(
        url(week.ali.company, "trend"), {**PERIOD, "format": "xlsx"}
    )

    assert response.status_code == 200


@pytest.mark.parametrize("kind", KINDS)
def test_the_exporters_build_the_same_rows(week, owner, kind):
    exporter = get_exporter(reports.EXPORTERS[kind])

    rows = list(exporter.rows(owner, {"from": PERIOD["from"], "to": PERIOD["to"]}))

    columns = {column.key for column in exporter.columns}
    assert rows and all(set(row) <= columns for row in rows)
    if kind == "summary":
        assert rows[-1]["person"] == "Total" and rows[-1]["days_scheduled"] == 13
    if kind == "trend":
        assert len(rows) == 5  # one per day, no totals row in a date column


def test_the_exporters_keep_the_requesters_scope(week, chilonzor, yunusobod):
    rows = list(
        get_exporter("attendance.report_people").rows(
            week.lead, {**PERIOD, "branch": [str(yunusobod.pk), str(chilonzor.pk)]}
        )
    )

    assert [row["person"].split()[0] for row in rows] == ["Ali", "Bob", "Vali", "Total"]
