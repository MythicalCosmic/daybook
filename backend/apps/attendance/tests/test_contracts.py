"""What attendance gives other packages: payroll's period summary (golden §3.17 numbers), the
analytics shape, the board, and every registry entry (fixed shapes, scope, permissions)."""

from datetime import date, time, timedelta

import pytest

from apps.ai.tools.testing import call_tool

# Imported here so the tool registers when the tests are collected, before apps/ai's tests
# swap the registry out (autodiscovery can't re-register a module that is already imported).
from apps.attendance import (
    ai_tools,  # noqa: F401
    providers,
    queries,
    services,
)
from apps.attendance.models import AttendanceRecord
from apps.attendance.tests.conftest import DAY, local
from apps.attendance.tests.factories import absent, assign, shift_at, weekly_schedule
from apps.console import contracts, registry
from apps.exports.registry import EXPORTERS
from apps.inbox.registry import KINDS
from apps.members import bot_menu
from apps.tasks import offdays
from apps.timeoff.models import Holiday, TimeOff

pytestmark = pytest.mark.django_db

OCTOBER = (date(2026, 10, 1), date(2026, 10, 31))


@pytest.fixture
def october(staff):
    """The §3.17 setup: Mon-Sat workdays and the holiday of 1 October 2026 (Thursday)."""
    company = staff.ali.company
    company.workdays = [0, 1, 2, 3, 4, 5]
    company.save()
    Holiday.objects.create(company=company, date=date(2026, 10, 1), name="Teachers' Day")
    return company


def test_scheduled_days_without_shifts_follow_the_workdays(october, staff):
    summary = queries.period_summary(october, *OCTOBER, branch_ids=None)[staff.ali.pk]
    assert summary.scheduled_days == 26  # 27 Mon-Sat days minus the holiday
    assert summary.has_schedule is False


def test_scheduled_days_with_shifts_and_absences(october, staff, freeze):
    freeze(local(date(2026, 9, 30), 12))
    assign(staff.ali, weekly_schedule(october, days=range(6)), date(2026, 10, 1))
    services.generate_shifts(october, start=date(2026, 10, 1), days=30)
    summary = queries.period_summary(october, *OCTOBER, branch_ids=None)[staff.ali.pk]
    assert summary.scheduled_days == 26 and summary.has_schedule
    # Two unpaid absences and one day of approved time off.
    for day in (date(2026, 10, 5), date(2026, 10, 6)):
        absent(staff.ali.work_shifts.get(date=day))
    time_off = TimeOff.objects.create(
        company=october,
        membership=staff.ali,
        first_day=date(2026, 10, 7),
        last_day=date(2026, 10, 7),
        status=TimeOff.Status.APPROVED,
    )
    services.time_off_approved(time_off)
    summary = queries.period_summary(october, *OCTOBER, branch_ids=None)[staff.ali.pk]
    assert summary.absent_days == 2
    assert summary.leave_days == 1 and summary.leave_time_off_ids == [time_off.pk]
    assert summary.scheduled_days == 26


def test_attended_worked_overtime_late_and_holiday_work(october, staff):
    services.update_settings(october, by=staff.manager, require_location=False)
    day = date(2026, 10, 12)
    shift_at(staff.ali, day)
    services.check_in(staff.ali, now=local(day, 9, 20))
    services.check_out(staff.ali, now=local(day, 19, 20))
    record = AttendanceRecord.objects.get(membership=staff.ali)
    services.decide_overtime(record, by=staff.manager, approve=True)
    holiday = shift_at(staff.ali, date(2026, 10, 1))
    services.check_in(staff.ali, now=local(date(2026, 10, 1), 9, 0))
    services.check_out(staff.ali, now=local(date(2026, 10, 1), 13, 0))
    summary = queries.period_summary(october, *OCTOBER, branch_ids=None)[staff.ali.pk]
    assert summary.attended_days == 2
    assert summary.late_arrivals == 1 and summary.late_minutes == 20
    assert summary.approved_overtime_minutes == 60
    assert summary.worked_minutes == 9 * 60 + 240  # four hours exactly: no break
    assert summary.holiday_worked_days == 1
    assert holiday.date not in {date(2026, 10, 12)}


def test_period_summary_keeps_people_who_left(october, staff, member):
    from apps.members.models import Membership

    shift_at(staff.vali, date(2026, 10, 2))
    staff.vali.status = Membership.Status.LEFT
    staff.vali.save()
    assert staff.vali.pk in queries.period_summary(october, *OCTOBER, branch_ids=None)


def test_period_summary_respects_branch_scope(staff):
    company = staff.ali.company
    found = queries.period_summary(company, DAY, DAY, branch_ids=[staff.ali.home_branch_id])
    assert staff.ali.pk in found and staff.sara.pk not in found


def test_summary_has_the_analytics_shape(staff, freeze):
    freeze(local(DAY, 12))
    company = staff.ali.company
    services.update_settings(company, by=staff.manager, require_location=False)
    shift_at(staff.ali, DAY)
    shift_at(staff.vali, DAY)
    services.check_in(staff.ali, now=local(DAY, 9, 30))
    result = queries.summary(
        company,
        DAY - timedelta(days=6),
        DAY,
        branch_ids=None,
        compare=(DAY - timedelta(days=13), DAY - timedelta(days=7)),
    )
    assert set(result) == {
        "range",
        "compare",
        "currency",
        "totals",
        "previous",
        "series",
        "breakdown",
    }
    assert result["totals"]["present"] == 1 and result["totals"]["late"] == 1
    assert result["totals"]["on_time_percent"] == "0.0"
    assert result["series"][-1] == {
        "date": DAY.isoformat(),
        "rostered": 2,
        "present": 1,
        "late": 1,
        "absent": 0,
    }
    assert {row["label"] for row in result["breakdown"]} == {"Chilonzor", "Yunusobod"}


def test_day_board_states(staff, freeze):
    now = freeze(local(DAY, 9, 45))
    company = staff.ali.company
    services.update_settings(company, by=staff.manager, require_location=False)
    shift_at(staff.ali, DAY)  # in on time
    shift_at(staff.vali, DAY)  # absent (no check-in 45 min after start)
    shift_at(staff.bob, DAY, time(9, 30), time(18))  # not yet (15 min past start)
    shift_at(staff.sara, DAY, time(9, 0), time(18))  # late
    services.check_in(staff.ali, now=local(DAY, 8, 58))
    services.check_in(staff.sara, now=local(DAY, 9, 25))
    board = queries.day_board(company, DAY, branch_ids=None, now=now)
    states = {row["member"]["name"]: (row["state"], row["reason"]) for row in board["people"]}
    assert states["Ali"] == ("in", None)
    assert states["Sara"] == ("late", None)
    assert states["Vali"] == ("absent", None)
    assert states["Bob"] == ("not_yet", "late")
    assert states["Mona"][0] == "off"
    assert board["totals"]["rostered"] == 4
    chilonzor = next(b for b in board["branches"] if b["name"] == "Chilonzor")
    assert chilonzor["rostered"] == 3 and chilonzor["checked_in"] == 1
    assert queries.not_in_count(staff.manager, now) == 2
    scoped = queries.day_board(company, DAY, branch_ids=[staff.ali.home_branch_id], now=now)
    assert "Sara" not in {row["member"]["name"] for row in scoped["people"]}


def test_branch_company_and_person_facts_fit_their_shapes(staff, freeze):
    now = freeze(local(DAY, 10))
    company = staff.ali.company
    services.update_settings(company, by=staff.manager, require_location=False)
    shift_at(staff.ali, DAY)
    services.check_in(staff.ali, now=local(DAY, 8, 50))
    branches = list(company.branches.values_list("pk", flat=True))
    facts = queries.branch_facts(company, DAY, now, branches)
    for value in facts.values():
        assert contracts.problems(contracts.AttendanceFacts, value) == []
    assert facts[staff.ali.home_branch_id]["checked_in"] == 1
    assert facts[staff.ali.home_branch_id]["first_check_in"].startswith("2026-10-21T08:50")
    company_facts = queries.company_facts(company, None, staff.manager)
    assert contracts.problems(contracts.AttendanceCompanyFacts, company_facts) == []
    assert company_facts == {"present": 1, "rostered": 1}
    fields = queries.person_fields(company, [staff.ali.pk, staff.vali.pk], now)
    for value in fields.values():
        assert contracts.problems(contracts.AttendancePersonFields, value) == []
    assert fields[staff.ali.pk]["attendance_today"] == "in"


def test_brief_section_lists_late_and_missing(staff, freeze):
    now = freeze(local(DAY, 9, 20))
    company = staff.ali.company
    services.update_settings(company, by=staff.manager, require_location=False)
    shift_at(staff.ali, DAY)
    shift_at(staff.vali, DAY)
    services.check_in(staff.ali, now=local(DAY, 9, 15))
    section = queries.brief_section(company, DAY, now, None)
    assert section["present"] == 1 and section["rostered"] == 2
    assert [p["name"] for p in section["late"]] == ["Ali"]
    assert [p["name"] for p in section["not_in_yet"]] == ["Vali"]


def test_stream_items_are_scoped(staff, freeze):
    freeze(local(DAY, 10))
    company = staff.ali.company
    services.update_settings(company, by=staff.manager, require_location=False)
    services.check_in(staff.ali, now=local(DAY, 8, 50))
    services.check_in(staff.sara, now=local(DAY, 9, 10))
    titles = [item.title for item in queries.stream(staff.lead, None, 10)]
    assert any("Ali" in title for title in titles)
    assert not any("Sara" in title for title in titles)


def test_offboard_step_and_calendar(staff, freeze):
    freeze(local(DAY, 10))
    shift_at(staff.ali, DAY + timedelta(days=2))
    step = providers.offboard_preview(staff.ali)
    assert any("1 coming shifts" in line for line in step.lines)
    assert step.blockers == []
    items = providers.calendar_events(staff.ali.company, DAY, DAY + timedelta(days=6), staff.ali)
    assert [item.kind for item in items] == ["attendance.shift"]
    viewer = providers.calendar_events(
        staff.ali.company, DAY, DAY + timedelta(days=6), staff.manager
    )
    assert any(item.kind == "attendance.coverage" for item in viewer)


def test_exporter_rows_follow_scope(staff, freeze):
    freeze(local(DAY, 20))
    company = staff.ali.company
    services.update_settings(company, by=staff.manager, require_location=False)
    services.check_in(staff.ali, now=local(DAY, 8, 50))
    services.check_in(staff.sara, now=local(DAY, 9, 10))
    rows = list(providers.timesheet_rows(staff.lead, {"start": DAY, "end": DAY}))
    assert [row["person"] for row in rows] == ["Ali"]
    every = list(providers.timesheet_rows(staff.manager, {"month": "2026-10"}))
    assert {row["person"] for row in every} == {"Ali", "Sara"}
    assert EXPORTERS.get("attendance.timesheet") is not None


def test_ai_tool_checks_permission_and_scope(staff, freeze):
    freeze(local(DAY, 20))
    company = staff.ali.company
    services.update_settings(company, by=staff.manager, require_location=False)
    shift_at(staff.ali, DAY)
    shift_at(staff.sara, DAY)
    services.check_in(staff.ali, now=local(DAY, 8, 50))
    result = call_tool("attendance_summary", staff.lead, start="2026-10-21", end="2026-10-21")
    assert {row["name"] for row in result["rows"]} == {"Ali"}
    assert call_tool("attendance_summary", staff.ali, start="2026-10-21", end="2026-10-21") == {
        "error": "not_allowed"
    }


def test_selfie_check(staff):
    company = staff.ali.company
    services.update_settings(company, by=staff.manager, require_location=False)
    record = services.check_in(staff.sara, now=local(DAY, 9, 0)).record
    assert providers.selfie_check(staff.sara.user, company.pk, record.pk)
    assert providers.selfie_check(staff.manager.user, company.pk, record.pk)
    assert not providers.selfie_check(staff.lead.user, company.pk, record.pk)  # other branch
    assert not providers.selfie_check(staff.ali.user, company.pk, record.pk)


def test_tasks_follow_shifts(staff):
    company = staff.ali.company
    shift_at(staff.ali, DAY)
    assert queries.off_day_people(company, DAY + timedelta(days=1)) == set()  # setting off
    services.update_settings(company, by=staff.manager, tasks_follow_shifts=True)
    assert staff.ali.pk in offdays.people_off(company, DAY + timedelta(days=1))
    assert staff.ali.pk not in queries.off_day_people(company, DAY)
    assert staff.vali.pk not in queries.off_day_people(company, DAY)  # no roster at all


def test_registrations_are_app_prefixed_and_complete():
    for name in ("attendance.not_in", "attendance.swaps", "attendance.corrections"):
        assert registry.PULSE.get(name).count is not None
    for name in ("attendance.corrections", "attendance.overtime", "attendance.swaps"):
        assert name in registry.QUEUE
    assert "attendance.checked_in" in registry.STREAM
    assert "attendance" in registry.BRANCH_FACTS
    assert "attendance" in registry.BRIEF_SECTIONS
    assert "attendance" in registry.PERSON_FIELDS
    assert "attendance" in registry.OFFBOARD_STEPS
    assert "attendance.schedules" in registry.SETUP_STEPS
    assert "attendance" in registry.COMPANY_FACTS
    assert "attendance.shifts" in registry.CALENDAR_SOURCES
    for kind in (
        "attendance.correction",
        "attendance.swap",
        "attendance.cover_request",
        "attendance.open_shift",
    ):
        assert kind in KINDS
    assert any(button.msgid == "📍 Check in / out" for button in bot_menu.registered())
    assert queries.off_day_people in offdays.providers()


def test_queue_items_carry_working_actions(staff, freeze):
    freeze(local(DAY, 10))
    services.request_correction(
        staff.ali,
        date=DAY - timedelta(days=1),
        check_in_at=local(DAY - timedelta(days=1), 9),
        check_out_at=local(DAY - timedelta(days=1), 18),
        reason="forgot",
    )
    [item] = providers.correction_items(staff.manager, 10)
    assert [a.key for a in item.actions] == ["approve", "reject"]
    assert item.actions[0].endpoint == f"attendance/corrections/{item.id}/decide/"
    assert item.actions[1].needs_reason
    assert providers.correction_items(staff.lead, 10)  # Ali works at the lead's branch
