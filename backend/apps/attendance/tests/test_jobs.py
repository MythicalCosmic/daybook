"""The periodic jobs with frozen times: auto-close, absences after 03:00, nudges once, the
no-show alert, "still working?", morning posts and generation over every company."""

from datetime import time, timedelta

import pytest

from apps.attendance import jobs, services
from apps.attendance.models import AttendanceRecord, JobMark, WorkShift
from apps.attendance.tests.conftest import DAY, local
from apps.attendance.tests.factories import assign, shift_at, weekly_schedule
from apps.inbox.models import Notification
from apps.members.models import Membership
from apps.notifications.emoji import has_emoji
from apps.timeoff.models import TimeOff

pytestmark = pytest.mark.django_db

YESTERDAY = DAY - timedelta(days=1)


@pytest.fixture
def no_location(staff):
    services.update_settings(staff.ali.company, by=staff.manager, require_location=False)


@pytest.fixture
def telegram(monkeypatch):
    """Direct employee-bot messages: (chat id, text, markup)."""
    sent = []
    monkeypatch.setattr(
        "apps.attendance.notify.send_telegram_message.delay",
        lambda bot, chat_id, text, markup=None, *a, **kw: sent.append((chat_id, text, markup)),
    )
    return sent


def test_auto_close_at_the_shift_end_after_the_grace_hours(
    staff, no_location, freeze, django_capture_on_commit_callbacks
):
    shift = shift_at(staff.ali, DAY)
    services.check_in(staff.ali, now=local(DAY, 8, 58))
    company = staff.ali.company
    assert services.auto_close(company, local(DAY, 20, 59)) == 0  # 18:00 + 3 h not reached
    with django_capture_on_commit_callbacks(execute=True):
        assert services.auto_close(company, local(DAY, 21, 1)) == 1
    record = AttendanceRecord.objects.get(shift=shift)
    assert record.status == AttendanceRecord.Status.AUTO_CLOSED
    assert record.check_out_at == shift.ends_at
    assert record.out_source == AttendanceRecord.Source.SYSTEM
    assert AttendanceRecord.Flag.AUTO_CLOSED in record.flags
    assert record.worked_minutes == 9 * 60 + 2 - 60
    asked = Notification.objects.get(kind="attendance.auto_closed", recipient=staff.ali)
    assert asked.app_screen == f"attendance.correct:{record.pk}"


def test_unscheduled_check_ins_close_with_no_worked_time(staff, no_location):
    services.check_in(staff.ali, now=local(DAY, 9, 0))
    assert services.auto_close(staff.ali.company, local(DAY + timedelta(days=1), 0, 59)) == 0
    assert services.auto_close(staff.ali.company, local(DAY + timedelta(days=1), 1, 1)) == 1
    record = AttendanceRecord.objects.get(membership=staff.ali)
    assert record.worked_minutes == 0
    assert record.status == AttendanceRecord.Status.AUTO_CLOSED


def test_absences_are_marked_after_three_in_the_morning(staff):
    company = staff.ali.company
    missed = shift_at(staff.ali, YESTERDAY)
    shift_at(staff.vali, YESTERDAY)
    services.update_settings(company, by=staff.manager, require_location=False)
    services.check_in(staff.vali, now=local(YESTERDAY, 9, 0))
    assert services.mark_absences(company, local(DAY, 2, 50)) == 0
    assert services.mark_absences(company, local(DAY, 3, 10)) == 1
    assert services.mark_absences(company, local(DAY, 3, 40)) == 0  # idempotent
    record = AttendanceRecord.objects.get(shift=missed)
    assert record.status == AttendanceRecord.Status.ABSENT


def test_no_absence_for_suspended_on_leave_or_unpublished(staff):
    company = staff.ali.company
    shift_at(staff.ali, YESTERDAY)
    shift_at(staff.vali, YESTERDAY)
    shift_at(staff.bob, YESTERDAY, published=False)
    staff.ali.status = Membership.Status.SUSPENDED
    staff.ali.save()
    TimeOff.objects.create(
        company=company,
        membership=staff.vali,
        first_day=YESTERDAY,
        last_day=YESTERDAY,
        status=TimeOff.Status.APPROVED,
    )
    assert services.mark_absences(company, local(DAY, 4, 0)) == 0
    assert WorkShift.objects.get(membership=staff.vali).status == WorkShift.Status.LEAVE


def test_overnight_shift_absence_waits_until_it_ends(staff):
    night = shift_at(staff.ali, YESTERDAY, time(22, 0), time(7, 0))
    company = staff.ali.company
    assert services.mark_absences(company, local(DAY, 4, 0)) == 0
    assert services.mark_absences(company, local(DAY, 7, 30)) == 1
    assert AttendanceRecord.objects.get(shift=night).status == AttendanceRecord.Status.ABSENT


def test_nudges_go_once(staff, freeze, telegram, django_capture_on_commit_callbacks):
    company = staff.ali.company
    services.update_settings(company, by=staff.manager, pre_shift_reminder_minutes=15)
    shift_at(staff.ali, DAY)
    jobs.nudge_company(company, local(DAY, 8, 50))
    assert len(telegram) == 1 and "starts at 09:00" in telegram[0][1]
    jobs.nudge_company(company, local(DAY, 8, 55))
    assert len(telegram) == 1
    # 10 minutes after the start without a check-in: "your shift started".
    jobs.nudge_company(company, local(DAY, 9, 10))
    assert len(telegram) == 2 and "started at 09:00" in telegram[1][1]
    keyboard = telegram[1][2]["inline_keyboard"]
    assert keyboard[1][0]["callback_data"].startswith("att:off:")
    # 30 minutes after: the managers hear about it, once.
    with django_capture_on_commit_callbacks(execute=True):
        jobs.nudge_company(company, local(DAY, 9, 31))
        jobs.nudge_company(company, local(DAY, 9, 36))
    alerts = Notification.objects.filter(kind="attendance.no_show")
    assert set(alerts.values_list("recipient_id", flat=True)) == {staff.manager.pk, staff.lead.pk}
    assert "hasn't checked in" in alerts.first().title


def test_checked_in_people_get_no_nudges(staff, no_location, telegram):
    company = staff.ali.company
    shift_at(staff.ali, DAY)
    services.check_in(staff.ali, now=local(DAY, 8, 59))
    jobs.nudge_company(company, local(DAY, 9, 40))
    assert telegram == []
    assert not Notification.objects.filter(kind="attendance.no_show").exists()


def test_off_today_replaces_the_no_show_alert(staff, telegram, django_capture_on_commit_callbacks):
    company = staff.ali.company
    shift = shift_at(staff.ali, DAY)
    with django_capture_on_commit_callbacks(execute=True):
        assert services.say_off_today(staff.ali, shift)
        assert not services.say_off_today(staff.ali, shift)
        jobs.nudge_company(company, local(DAY, 9, 40))
    alerts = Notification.objects.filter(kind="attendance.no_show", recipient=staff.manager)
    assert alerts.count() == 1
    assert "off today" in alerts.get().title


def test_still_working_is_asked_an_hour_after_the_end(staff, no_location, telegram):
    company = staff.ali.company
    shift_at(staff.ali, DAY)
    services.check_in(staff.ali, now=local(DAY, 8, 59))
    jobs.nudge_company(company, local(DAY, 18, 50))
    assert telegram == []
    jobs.nudge_company(company, local(DAY, 19, 5))
    jobs.nudge_company(company, local(DAY, 19, 10))
    assert len(telegram) == 1 and "Still working?" in telegram[0][1]
    buttons = [b["callback_data"] for b in telegram[0][2]["inline_keyboard"][0]]
    assert buttons[0].startswith("att:done:") and buttons[1].startswith("att:still:")


def test_morning_post_once_per_branch(staff, no_location, monkeypatch):
    posted = []
    monkeypatch.setattr(
        "apps.groups.services.broadcast",
        lambda company_id, event, text, **kw: (
            posted.append((event, text, kw.get("branch_id"))) or 1
        ),
    )
    company = staff.ali.company
    shift_at(staff.ali, DAY)
    shift_at(staff.vali, DAY)
    services.check_in(staff.ali, now=local(DAY, 8, 55))
    jobs.nudge_company(company, local(DAY, 9, 20))
    assert posted == []
    jobs.nudge_company(company, local(DAY, 9, 31))
    jobs.nudge_company(company, local(DAY, 9, 40))
    assert len(posted) == 1
    event, text, branch_id = posted[0]
    assert event == "attendance" and branch_id == staff.ali.home_branch_id
    assert "1 of 2" in text and "Vali" in text
    # Who came on time and who is missing, in words (no tick and clock marks).
    lines = text.splitlines()
    assert lines[0].startswith("<b>Who's in · ")
    assert any(line.startswith("On time: ") for line in lines)
    assert any(line.startswith("Not here yet: ") and "Vali" in line for line in lines)
    assert not has_emoji(text)


def test_jobs_walk_companies_with_the_module_on(staff, other_company, freeze):
    freeze(local(DAY, 6, 0))
    assign(staff.ali, weekly_schedule(staff.ali.company, days=range(7)), DAY)
    assert jobs.generate_shifts(local(DAY, 6, 0)) == 15
    assert jobs.generate_shifts(local(DAY, 6, 0)) == 0


def test_old_job_marks_are_cleared(staff):
    company = staff.ali.company
    mark = JobMark.objects.create(company=company, key="late:1")
    JobMark.objects.filter(pk=mark.pk).update(created_at=local(DAY - timedelta(days=40), 9))
    jobs.close_days(local(DAY, 4, 0))
    assert not JobMark.objects.filter(pk=mark.pk).exists()
