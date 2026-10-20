"""Review fixes: idempotent "copy last week" for open shifts, the bulk eligibility check the
mini app's lists use, eligibility re-checked when a manager approves, settled open-shift
offers, readable errors for bad ids, and list endpoints whose query count doesn't grow with
their rows."""

from datetime import time, timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.attendance import queries, services
from apps.attendance.models import AttendanceCorrection, ShiftSwap, WorkShift
from apps.attendance.tests.conftest import DAY, local
from apps.attendance.tests.factories import absent, shift_at
from apps.core.exceptions import DomainError
from apps.inbox.models import Notification
from apps.members.models import Membership
from apps.timeoff.models import TimeOff

pytestmark = pytest.mark.django_db

FRIDAY = DAY + timedelta(days=2)
MONDAY = DAY + timedelta(days=5)
YESTERDAY = DAY - timedelta(days=1)


@pytest.fixture(autouse=True)
def morning(freeze):
    return freeze(local(DAY, 10, 0))


@pytest.fixture
def run_commits(django_capture_on_commit_callbacks):
    def run(fn, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return fn(*args, **kwargs)

    return run


def owner_url(company, path):
    return f"/api/v1/owner/companies/{company.pk}/attendance/{path}"


def employee_url(company, path):
    return f"/api/v1/companies/{company.pk}/attendance/{path}"


def leave(member, first, last=None) -> TimeOff:
    return TimeOff.objects.create(
        company=member.company,
        membership=member,
        first_day=first,
        last_day=last or first,
        status=TimeOff.Status.APPROVED,
    )


# Copy last week ----------------------------------------------------------------------------


def test_copying_a_week_twice_copies_open_shifts_once(staff, chilonzor):
    company = staff.ali.company
    last_monday = MONDAY - timedelta(days=7)
    shift_at(None, last_monday, time(12), time(21), company=company, branch=chilonzor)
    shift_at(staff.ali, last_monday + timedelta(days=1))
    assert services.bulk_roster(company, by=staff.manager, action="copy_week", week=MONDAY) == 2
    assert services.bulk_roster(company, by=staff.manager, action="copy_week", week=MONDAY) == 0
    week = WorkShift.objects.filter(date__range=(MONDAY, MONDAY + timedelta(days=6)))
    assert week.filter(membership__isnull=True).count() == 1
    assert week.filter(membership=staff.ali).count() == 1


# Who may take a shift, many at once ----------------------------------------------------------


def test_takeable_agrees_with_is_eligible(staff, chilonzor, yunusobod):
    company = staff.ali.company
    cases = [
        shift_at(staff.vali, FRIDAY),  # a cashier colleague's shift at Chilonzor
        shift_at(staff.sara, FRIDAY + timedelta(days=1)),  # Yunusobod
        shift_at(staff.bob, FRIDAY + timedelta(days=2)),  # another position
        shift_at(None, FRIDAY + timedelta(days=3), company=company, branch=chilonzor),
        shift_at(
            None,
            FRIDAY + timedelta(days=4),
            company=company,
            branch=chilonzor,
            position=staff.cashier,
        ),
        shift_at(None, FRIDAY + timedelta(days=5), company=company, branch=yunusobod),
        shift_at(staff.vali, FRIDAY + timedelta(days=6), time(22), time(6)),  # overnight
        shift_at(staff.vali, FRIDAY + timedelta(days=8)),  # Ali is on leave then
        shift_at(staff.vali, FRIDAY + timedelta(days=9)),  # Ali works that day already
    ]
    # Ali's own week: a morning shift the day after the overnight one (it overlaps), leave,
    # and a shift on the day of the last case.
    shift_at(staff.ali, FRIDAY + timedelta(days=7), time(5), time(12))
    leave(staff.ali, FRIDAY + timedelta(days=8))
    shift_at(staff.ali, FRIDAY + timedelta(days=9), time(19), time(23))
    for shift in cases:
        shift.refresh_from_db()
    expected = {shift.pk for shift in cases if queries.is_eligible(shift, staff.ali)}
    assert queries.takeable(staff.ali, cases) == expected
    assert expected == {cases[0].pk, cases[3].pk, cases[4].pk}
    # Nobody who isn't approved takes anything.
    Membership.objects.filter(pk=staff.ali.pk).update(status=Membership.Status.SUSPENDED)
    staff.ali.refresh_from_db()
    assert queries.takeable(staff.ali, cases) == set()


def test_takeable_ignores_the_shift_given_away_in_a_swap(staff):
    mine = shift_at(staff.ali, FRIDAY)
    theirs = shift_at(staff.vali, FRIDAY, time(14), time(22))
    assert queries.takeable(staff.ali, [theirs]) == set()
    assert queries.takeable(staff.ali, [theirs], ignore_shift_ids=[mine.pk]) == {theirs.pk}


def test_my_day_and_swap_lists_check_eligibility_in_a_fixed_number_of_queries(staff, api_as):
    company = staff.ali.company
    services.update_settings(company, by=None, require_location=False)
    shift_at(staff.ali, DAY, time(9), time(18))
    client = api_as(staff.ali)

    def count(path):
        with CaptureQueriesContext(connection) as captured:
            assert client.get(employee_url(company, path)).status_code == 200
        return len(captured)

    def offer(day):
        shift_at(None, day, company=company, branch=staff.ali.home_branch)
        vali = shift_at(staff.vali, day)
        services.request_swap(staff.vali, shift=vali, kind="cover")

    offer(FRIDAY)
    first = {path: count(path) for path in ("today/", "swaps/", "open-shifts/")}
    for days in range(3, 9):
        offer(DAY + timedelta(days=days))
    assert {path: count(path) for path in first} == first
    day = client.get(employee_url(company, "today/")).json()
    assert day["open_shifts"] == 7 and day["requests"] == 7


def test_candidates_list_their_shifts_in_a_fixed_number_of_queries(staff, api_as):
    company = staff.ali.company
    mine = shift_at(staff.ali, FRIDAY)
    client = api_as(staff.ali)

    def count():
        with CaptureQueriesContext(connection) as captured:
            response = client.get(employee_url(company, f"swaps/candidates/?shift_id={mine.pk}"))
        assert response.status_code == 200
        return len(captured), response.json()

    shift_at(staff.vali, FRIDAY + timedelta(days=1))
    before, _rows = count()
    for days in range(2, 8):
        shift_at(staff.vali, FRIDAY + timedelta(days=days))
    after, rows = count()
    assert after == before
    assert [row["member"]["name"] for row in rows] == ["Vali"]
    assert len(rows[0]["shifts"]) == 6  # at most six of theirs


# Approval checks eligibility again -----------------------------------------------------------


def test_approval_refuses_a_colleague_who_went_on_leave(staff, run_commits):
    shift = shift_at(staff.ali, FRIDAY)
    swap = run_commits(services.request_swap, staff.ali, shift=shift, kind="cover")
    run_commits(services.accept_swap, swap, by=staff.vali)
    leave(staff.vali, FRIDAY)
    with pytest.raises(DomainError, match="can't take this shift any more"):
        services.decide_swap(swap, by=staff.manager, approve=True)
    shift.refresh_from_db()
    swap.refresh_from_db()
    assert shift.membership == staff.ali
    assert swap.status == ShiftSwap.Status.ACCEPTED  # the manager can still reject it


def test_approved_claim_closes_the_offers_to_everyone_else(staff, chilonzor, run_commits):
    company = staff.ali.company
    shift = run_commits(
        services.create_shift,
        company,
        by=staff.manager,
        date=FRIDAY,
        starts_at=time(9),
        ends_at=time(18),
        branch=chilonzor,
        position=staff.cashier,
        publish=True,
    )
    offers = Notification.objects.filter(kind="attendance.open_shift", target_id=shift.pk)
    assert offers.count() == 2  # Ali and Vali
    claim = run_commits(services.claim_open_shift, shift, by=staff.ali)
    assert claim.status == ShiftSwap.Status.ACCEPTED
    run_commits(services.decide_swap, claim, by=staff.manager, approve=True)
    assert not offers.filter(acted_at__isnull=True).exists()


def test_a_swap_partner_must_still_be_free_to_take_the_other_shift(staff, run_commits):
    mine = shift_at(staff.ali, FRIDAY)
    theirs = shift_at(staff.vali, FRIDAY + timedelta(days=1))
    swap = run_commits(
        services.request_swap, staff.ali, shift=mine, kind="swap", other_shift=theirs
    )
    leave(staff.ali, FRIDAY + timedelta(days=1))
    with pytest.raises(DomainError, match="changed since the request"):
        services.accept_swap(swap, by=staff.vali)


def test_asking_twice_about_one_shift_makes_one_request(staff):
    shift = shift_at(staff.ali, FRIDAY)
    services.request_swap(staff.ali, shift=shift, kind="cover")
    with pytest.raises(DomainError, match="already asked"):
        services.request_swap(staff.ali, shift=shift, kind="cover", target=staff.vali)
    assert ShiftSwap.objects.filter(shift=shift).count() == 1


# Records -------------------------------------------------------------------------------------


def test_an_attended_day_keeps_its_check_in(staff):
    company = staff.ali.company
    services.update_settings(company, by=None, require_location=False)
    shift_at(staff.ali, YESTERDAY)
    record = services.check_in(staff.ali, now=local(YESTERDAY, 9, 0)).record
    services.check_out(staff.ali, now=local(YESTERDAY, 18, 0))
    with pytest.raises(DomainError, match="check-in time"):
        services.edit_record(record, by=staff.manager, reason="typo", check_in_at=None)


def test_bad_ids_in_filters_answer_400(staff, owner_api):
    company = staff.ali.company
    client = owner_api(staff.manager)
    assert client.get(owner_url(company, "records/?member=abc")).status_code == 400
    assert (
        client.get(owner_url(company, f"shifts/?from={DAY}&to={DAY}&member=x")).status_code == 400
    )
    assert client.get(owner_url(company, "timesheet/?branch=x")).status_code == 400
    assert client.get(owner_url(company, "summary/?member=x")).status_code == 400


# Query counts of the owner lists ---------------------------------------------------------------


def _queries(client, path) -> int:
    with CaptureQueriesContext(connection) as captured:
        response = client.get(path)
    assert response.status_code == 200, response.content
    return len(captured)


def test_owner_lists_do_not_grow_with_their_rows(staff, owner_api, member, chilonzor):
    company = staff.ali.company
    services.update_settings(company, by=None, require_location=False)
    client = owner_api(staff.manager)
    paths = [
        "board/",
        f"records/?from={YESTERDAY}&to={DAY}",
        f"roster/?week={DAY}",
        "timesheet/",
        "swaps/?status=all",
        "corrections/?status=all",
        f"shifts/?from={DAY}&to={FRIDAY}",
    ]

    def add_people(names):
        for name in names:
            person = member.registered(
                company, position=staff.cashier, home_branch=chilonzor, first_name=name
            )
            person.branches.add(chilonzor)
            shift_at(person, DAY)
            yesterday = shift_at(person, YESTERDAY)
            absent(yesterday)
            services.check_in(person, now=local(DAY, 8, 50))
            AttendanceCorrection.objects.create(
                company=company,
                membership=person,
                date=YESTERDAY,
                reason="Forgot",
                check_in_at=local(YESTERDAY, 9),
            )
            theirs = shift_at(person, FRIDAY)
            swap = services.request_swap(person, shift=theirs, kind="cover")
            ShiftSwap.objects.filter(pk=swap.pk).update(status=ShiftSwap.Status.ACCEPTED)

    add_people(["P1", "P2"])
    before = {path: _queries(client, owner_url(company, path)) for path in paths}
    add_people(["P3", "P4", "P5", "P6"])
    after = {path: _queries(client, owner_url(company, path)) for path in paths}
    assert after == before
