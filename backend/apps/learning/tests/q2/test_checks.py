"""Regular checks (docs/PLAN-LEARNING.md §4.9): the schedule, one round per period, reminders at
half time and two hours before the end, the digest at the end."""

from datetime import date, time, timedelta

import pytest

from apps.companies.tests.factories import BranchFactory
from apps.core.exceptions import DomainError
from apps.inbox.models import Notification
from apps.learning import attempts, checks
from apps.learning.models import Attempt, CheckEntry, CheckRound, RegularCheck
from apps.learning.tests.q2.fixtures import local, person, position, question, quiz, topic
from apps.timeoff.models import TimeOff

pytestmark = pytest.mark.django_db

# Monday 9 November 2026, 10:00 in Tashkent.
MONDAY_10 = local(2026, 11, 9, 10, 0)


@pytest.fixture
def weekly(pharmacy, manager):
    cold = topic(pharmacy)
    test = quiz(pharmacy, [question(pharmacy, "true_false", topic=cold) for _ in range(2)])
    check = checks.create_check(
        pharmacy,
        by=manager,
        title="Dushanba tekshiruvi",
        quiz_id=test.pk,
        every="week",
        weekday=0,
        at="10:00",
        answer_within_hours=48,
    )
    RegularCheck.objects.filter(pk=check.pk).update(next_run_at=MONDAY_10)
    check.refresh_from_db()
    return check


def notices(kind, member=None):
    rows = Notification.objects.filter(kind=kind)
    return rows.filter(recipient=member) if member else rows


def test_the_next_time_a_check_is_due(pharmacy):
    check = RegularCheck(company=pharmacy, every="week", weekday=0, at=time(10, 0))
    assert checks.next_occurrence(check, local(2026, 11, 7, 12, 0)) == MONDAY_10
    assert checks.next_occurrence(check, MONDAY_10) == MONDAY_10 + timedelta(days=7)
    assert checks.next_occurrence(check, local(2026, 11, 9, 9, 59)) == MONDAY_10
    monthly = RegularCheck(company=pharmacy, every="month", month_day=28, at=time(9, 30))
    assert checks.next_occurrence(monthly, local(2026, 11, 28, 9, 30)) == local(2026, 12, 28, 9, 30)
    assert checks.next_occurrence(monthly, local(2026, 12, 29, 0, 0)) == local(2027, 1, 28, 9, 30)


def test_a_check_needs_its_day_and_a_quiz_of_the_company(pharmacy, manager, other_company):
    test = quiz(pharmacy, [question(pharmacy, "true_false")])
    with pytest.raises(DomainError):
        checks.create_check(pharmacy, by=manager, title="T", quiz_id=test.pk, every="week")
    with pytest.raises(DomainError):
        checks.create_check(
            pharmacy, by=manager, title="T", quiz_id=test.pk, every="month", month_day=31
        )
    with pytest.raises(DomainError):
        checks.create_check(
            pharmacy,
            by=manager,
            title="T",
            quiz_id=quiz(other_company, [question(other_company, "true_false")]).pk,
            every="week",
            weekday=0,
        )
    with pytest.raises(DomainError):
        checks.create_check(
            pharmacy,
            by=manager,
            title="T",
            quiz_id=test.pk,
            every="week",
            weekday=2,
            answer_within_hours=0,
        )


def test_a_round_starts_once_per_period_with_an_entry_and_a_notice_each(
    weekly, pharmacy, staff, manager
):
    assert checks.run_checks(MONDAY_10 - timedelta(minutes=5)) == 0
    assert checks.run_checks(MONDAY_10 + timedelta(minutes=2)) == 1
    assert checks.run_checks(MONDAY_10 + timedelta(minutes=12)) == 0
    round_ = CheckRound.objects.get()
    assert (round_.starts_at, round_.due_at) == (MONDAY_10, MONDAY_10 + timedelta(hours=48))
    assert set(round_.entries.values_list("membership", flat=True)) == {staff.pk, manager.pk}
    entry = CheckEntry.objects.get(membership=staff)
    [notice] = notices("learning.check_started", staff)
    assert notice.title == "Regular check: Dushanba tekshiruvi"
    assert notice.body == "2 questions, to answer by 11.11 10:00."
    assert notice.app_screen == f"check:{entry.pk}"
    weekly.refresh_from_db()
    assert weekly.next_run_at == MONDAY_10 + timedelta(days=7)


def test_the_audience_positions_branches_and_time_off(weekly, pharmacy, staff, manager):
    pharmacists = position(pharmacy)
    yunusobod = BranchFactory(company=pharmacy, name="Yunusobod")
    there = person(pharmacy, branch=yunusobod, position=pharmacists)
    here = person(pharmacy, position=pharmacists)
    away = person(pharmacy, branch=yunusobod, position=pharmacists)
    TimeOff.objects.create(
        company=pharmacy,
        membership=away,
        status="approved",
        first_day=date(2026, 11, 9),
        last_day=date(2026, 11, 10),
    )
    checks.update_check(
        weekly,
        by=manager,
        audience_all=False,
        position_ids=[pharmacists.pk],
        branch_ids=[yunusobod.pk],
    )
    weekly.refresh_from_db()
    RegularCheck.objects.filter(pk=weekly.pk).update(next_run_at=MONDAY_10)
    checks.run_checks(MONDAY_10)
    assert list(CheckEntry.objects.values_list("membership", flat=True)) == [there.pk]
    assert here.pk and staff.pk  # the others were not asked


def test_reminders_at_half_time_and_two_hours_before_the_end(weekly, staff, manager):
    checks.run_checks(MONDAY_10)
    entry = CheckEntry.objects.get(membership=manager)
    test = weekly.quiz
    attempt, _new = attempts.start(test, manager, entry=entry, now=MONDAY_10 + timedelta(hours=1))
    attempts.finish(attempt, now=MONDAY_10 + timedelta(hours=1, minutes=5))
    assert checks.run_checks(MONDAY_10 + timedelta(hours=23)) == 0
    assert checks.run_checks(MONDAY_10 + timedelta(hours=24)) == 1  # half time: staff only
    assert checks.run_checks(MONDAY_10 + timedelta(hours=25)) == 0
    assert checks.run_checks(MONDAY_10 + timedelta(hours=46)) == 1  # two hours left
    [half, last] = notices("learning.check_reminder", staff).order_by("pk")
    assert half.body == "Half the time is gone: answer by 11.11 10:00."
    assert last.body == "Two hours left: answer by 11.11 10:00."
    assert not notices("learning.check_reminder", manager).exists()


def test_the_round_closes_with_a_digest_for_each_manager_about_their_people(
    weekly, pharmacy, staff, manager
):
    yunusobod = BranchFactory(company=pharmacy, name="Yunusobod")
    night = person(pharmacy, branch=yunusobod, first_name="Nigora", last_name="Azimova")
    from apps.learning.tests.q2.fixtures import branch_viewer
    from apps.members.permissions import Perm

    head = branch_viewer(pharmacy, [yunusobod], perms=(Perm.LEARNING_MANAGE,))
    checks.run_checks(MONDAY_10)
    entry = CheckEntry.objects.get(membership=night)
    attempt, _new = attempts.start(weekly.quiz, night, entry=entry, now=MONDAY_10)
    for item in attempt.items:
        attempts.save_answer(attempt, item["question"], {"value": True}, now=MONDAY_10)  # wrong
    open_one, _new = attempts.start(
        weekly.quiz, staff, entry=CheckEntry.objects.get(membership=staff), now=MONDAY_10
    )
    assert checks.run_checks(MONDAY_10 + timedelta(hours=48)) == 2  # two managers heard
    round_ = CheckRound.objects.get()
    assert (round_.people, round_.finished, round_.passed) == (4, 2, 0)
    assert round_.closed_at == MONDAY_10 + timedelta(hours=48)
    open_one.refresh_from_db()
    assert open_one.state == Attempt.State.FINISHED  # graded with what was saved
    [mine] = notices("learning.check_results", head)
    assert mine.title == "Check results: Dushanba tekshiruvi"
    assert mine.body.startswith("Answered: 1 of 2. Passed: 0.")  # Nigora and the head
    assert "Hardest question: «true_false question?» (0 % right)." in mine.body
    [everyone] = notices("learning.check_results", manager)
    assert "Answered: 2 of 4." in everyone.body
    assert "Didn't answer: " in everyone.body and "Bekzod Mirzayev" in everyone.body
    assert checks.run_checks(MONDAY_10 + timedelta(hours=50)) == 0  # closed once


def test_after_a_pause_only_the_latest_open_period_is_sent(weekly, staff):
    RegularCheck.objects.filter(pk=weekly.pk).update(next_run_at=MONDAY_10 - timedelta(days=14))
    assert checks.run_checks(MONDAY_10 + timedelta(hours=1)) == 1
    assert list(CheckRound.objects.values_list("starts_at", flat=True)) == [MONDAY_10]
    # Nothing still open: no round is sent (the open one closes), the schedule moves on.
    RegularCheck.objects.filter(pk=weekly.pk).update(next_run_at=MONDAY_10 - timedelta(days=5))
    checks.run_checks(MONDAY_10 + timedelta(days=3))
    assert CheckRound.objects.count() == 1
    weekly.refresh_from_db()
    assert weekly.next_run_at == MONDAY_10 + timedelta(days=7)


def test_paused_archived_or_with_learning_off_nothing_goes(weekly, pharmacy, manager):
    checks.set_check_state(weekly, "paused", by=manager)
    RegularCheck.objects.filter(pk=weekly.pk).update(next_run_at=MONDAY_10)
    assert checks.run_checks(MONDAY_10) == 0
    checks.set_check_state(weekly, "active", by=manager)
    RegularCheck.objects.filter(pk=weekly.pk).update(next_run_at=MONDAY_10)
    pharmacy.features = [feature for feature in pharmacy.features if feature != "learning"]
    pharmacy.save(update_fields=["features"])
    assert checks.run_checks(MONDAY_10) == 0
    assert not CheckRound.objects.exists()


def test_a_quiz_that_isnt_published_skips_the_round(weekly, manager):
    from apps.learning import quizzes

    quizzes.archive_quiz(weekly.quiz, by=manager)
    assert checks.run_checks(MONDAY_10) == 0
    assert not CheckRound.objects.exists()
    weekly.refresh_from_db()
    assert weekly.next_run_at == MONDAY_10 + timedelta(days=7)
