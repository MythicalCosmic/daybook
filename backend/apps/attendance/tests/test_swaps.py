"""Swaps, covers and open shifts: only eligible people accept or claim, approval moves the shift
and tells both people, requests expire at the shift's start."""

from datetime import time, timedelta

import pytest
from django.core.exceptions import PermissionDenied

from apps.attendance import services
from apps.attendance.models import ShiftSwap, WorkShift
from apps.attendance.tests.conftest import DAY, local
from apps.attendance.tests.factories import shift_at
from apps.core.exceptions import DomainError
from apps.inbox.models import Notification
from apps.timeoff.models import TimeOff

pytestmark = pytest.mark.django_db

FRIDAY = DAY + timedelta(days=2)


@pytest.fixture(autouse=True)
def morning(freeze):
    return freeze(local(DAY, 10, 0))


@pytest.fixture
def run_commits(django_capture_on_commit_callbacks):
    def run(fn, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return fn(*args, **kwargs)

    return run


def test_cover_by_a_named_colleague_then_approval(staff, run_commits):
    shift = shift_at(staff.ali, FRIDAY)
    swap = run_commits(
        services.request_swap,
        staff.ali,
        shift=shift,
        kind="cover",
        target=staff.vali,
        note="Doctor",
    )
    offered = Notification.objects.get(kind="attendance.cover_request")
    assert offered.recipient == staff.vali
    assert [a["key"] for a in offered.actions] == ["accept", "decline"]

    run_commits(services.accept_swap, swap, by=staff.vali)
    swap.refresh_from_db()
    assert swap.status == ShiftSwap.Status.ACCEPTED
    shift.refresh_from_db()
    assert shift.membership == staff.ali  # waits for a manager

    run_commits(services.decide_swap, swap, by=staff.manager, approve=True)
    shift.refresh_from_db()
    swap.refresh_from_db()
    assert (shift.membership, shift.source) == (staff.vali, WorkShift.Source.SWAP)
    assert swap.status == ShiftSwap.Status.APPROVED
    told = set(
        Notification.objects.filter(kind="attendance.decision", target_id=swap.pk).values_list(
            "recipient_id", flat=True
        )
    )
    assert told == {staff.ali.pk, staff.vali.pk}


def test_only_eligible_people_can_accept(staff, run_commits):
    shift = shift_at(staff.ali, FRIDAY)
    swap = run_commits(services.request_swap, staff.ali, shift=shift, kind="cover")
    # Anyone eligible: Vali (cashier at Chilonzor). Not Bob (stock) nor Sara (Yunusobod).
    recipients = set(
        Notification.objects.filter(kind="attendance.cover_request").values_list(
            "recipient_id", flat=True
        )
    )
    assert recipients == {staff.vali.pk}
    with pytest.raises(DomainError, match="can't take"):
        services.accept_swap(swap, by=staff.bob)
    with pytest.raises(DomainError, match="can't take"):
        services.accept_swap(swap, by=staff.sara)
    with pytest.raises(DomainError, match="own request"):
        services.accept_swap(swap, by=staff.ali)


def test_busy_or_away_colleagues_are_not_eligible(staff):
    shift = shift_at(staff.ali, FRIDAY)
    shift_at(staff.vali, FRIDAY, time(15, 0), time(23, 0))
    assert not services.queries.is_eligible(shift, staff.vali)
    other = shift_at(staff.ali, FRIDAY + timedelta(days=1))
    TimeOff.objects.create(
        company=staff.vali.company,
        membership=staff.vali,
        first_day=other.date,
        last_day=other.date,
        status=TimeOff.Status.APPROVED,
    )
    assert not services.queries.is_eligible(other, staff.vali)


def test_a_named_request_is_for_that_person_only(staff, member, run_commits):
    third = member.registered(
        staff.ali.company, position=staff.cashier, home_branch=staff.ali.home_branch
    )
    third.branches.add(staff.ali.home_branch)
    shift = shift_at(staff.ali, FRIDAY)
    swap = run_commits(
        services.request_swap, staff.ali, shift=shift, kind="cover", target=staff.vali
    )
    with pytest.raises(PermissionDenied):
        services.accept_swap(swap, by=third)
    services.decline_swap(swap, by=staff.vali)
    swap.refresh_from_db()
    assert swap.status == ShiftSwap.Status.REJECTED


def test_swap_exchanges_two_shifts(staff, run_commits):
    mine = shift_at(staff.ali, FRIDAY)
    theirs = shift_at(staff.vali, FRIDAY + timedelta(days=1))
    swap = run_commits(
        services.request_swap, staff.ali, shift=mine, kind="swap", other_shift=theirs
    )
    assert swap.target == staff.vali
    run_commits(services.accept_swap, swap, by=staff.vali)
    run_commits(services.decide_swap, swap, by=staff.manager, approve=True)
    mine.refresh_from_db()
    theirs.refresh_from_db()
    assert mine.membership == staff.vali
    assert theirs.membership == staff.ali


def test_without_required_approval_the_shift_moves_on_accept(staff, run_commits):
    services.update_settings(staff.ali.company, by=staff.manager, swaps_need_approval=False)
    shift = shift_at(staff.ali, FRIDAY)
    swap = run_commits(
        services.request_swap, staff.ali, shift=shift, kind="cover", target=staff.vali
    )
    run_commits(services.accept_swap, swap, by=staff.vali)
    shift.refresh_from_db()
    swap.refresh_from_db()
    assert shift.membership == staff.vali
    assert swap.status == ShiftSwap.Status.APPROVED


def test_claiming_an_open_shift(staff, chilonzor, run_commits):
    open_shift = shift_at(
        None, FRIDAY, company=staff.ali.company, branch=chilonzor, position=staff.cashier
    )
    claim_a = run_commits(services.claim_open_shift, open_shift, by=staff.ali)
    claim_b = run_commits(services.claim_open_shift, open_shift, by=staff.vali)
    assert claim_a.status == claim_b.status == ShiftSwap.Status.ACCEPTED
    with pytest.raises(DomainError, match="can't take"):
        services.claim_open_shift(open_shift, by=staff.bob)
    run_commits(services.decide_swap, claim_b, by=staff.manager, approve=True)
    open_shift.refresh_from_db()
    claim_a.refresh_from_db()
    assert (open_shift.membership, open_shift.status) == (staff.vali, WorkShift.Status.PLANNED)
    assert claim_a.status == ShiftSwap.Status.REJECTED  # someone else got it
    with pytest.raises(DomainError, match="already taken"):
        services.claim_open_shift(open_shift, by=staff.ali)


def test_first_claim_wins_without_approval(staff, chilonzor):
    services.update_settings(
        staff.ali.company, by=staff.manager, open_shift_claim_needs_approval=False
    )
    open_shift = shift_at(
        None, FRIDAY, company=staff.ali.company, branch=chilonzor, position=staff.cashier
    )
    claim = services.claim_open_shift(open_shift, by=staff.ali)
    open_shift.refresh_from_db()
    assert claim.status == ShiftSwap.Status.APPROVED
    assert open_shift.membership == staff.ali


def test_drafts_and_started_shifts_cannot_be_handed_over(staff):
    draft = shift_at(staff.ali, FRIDAY, published=False)
    with pytest.raises(DomainError, match="isn't your shift"):
        services.request_swap(staff.ali, shift=draft, kind="cover")
    started = shift_at(staff.ali, DAY, time(8, 0), time(17, 0))
    with pytest.raises(DomainError, match="any more"):
        services.request_swap(staff.ali, shift=started, kind="cover")
    with pytest.raises(DomainError, match="isn't your shift"):
        services.request_swap(
            staff.vali, shift=shift_at(staff.ali, FRIDAY + timedelta(days=1)), kind="cover"
        )


def test_requests_expire_at_the_shifts_start(staff, freeze, run_commits):
    shift = shift_at(staff.ali, FRIDAY)
    swap = run_commits(
        services.request_swap, staff.ali, shift=shift, kind="cover", target=staff.vali
    )
    assert swap.expires_at == shift.starts_at
    assert services.expire_swaps(local(FRIDAY, 8, 59)) == 0
    freeze(local(FRIDAY, 9, 1))
    with pytest.raises(DomainError, match="started"):
        services.accept_swap(swap, by=staff.vali, now=local(FRIDAY, 9, 1))
    assert run_commits(services.expire_swaps, local(FRIDAY, 9, 1)) == 1
    swap.refresh_from_db()
    assert swap.status == ShiftSwap.Status.EXPIRED
    assert Notification.objects.filter(kind="attendance.decision", recipient=staff.ali).exists()


def test_cancel_by_the_asker_only(staff, run_commits):
    shift = shift_at(staff.ali, FRIDAY)
    swap = run_commits(
        services.request_swap, staff.ali, shift=shift, kind="cover", target=staff.vali
    )
    with pytest.raises(PermissionDenied):
        services.cancel_swap(swap, by=staff.vali)
    run_commits(services.cancel_swap, swap, by=staff.ali)
    swap.refresh_from_db()
    offered = Notification.objects.get(kind="attendance.cover_request")
    assert swap.status == ShiftSwap.Status.CANCELLED
    assert offered.acted_at is not None  # the colleague's buttons are gone


def test_rejecting_needs_a_reason_and_a_manager(staff, run_commits):
    shift = shift_at(staff.ali, FRIDAY)
    swap = run_commits(
        services.request_swap, staff.ali, shift=shift, kind="cover", target=staff.vali
    )
    run_commits(services.accept_swap, swap, by=staff.vali)
    with pytest.raises(DomainError, match="reason"):
        services.decide_swap(swap, by=staff.manager, approve=False)
    with pytest.raises(PermissionDenied):
        services.decide_swap(swap, by=staff.accountant, approve=True)
    run_commits(services.decide_swap, swap, by=staff.manager, approve=False, reason="We need you")
    swap.refresh_from_db()
    assert (swap.status, swap.decision_note) == (ShiftSwap.Status.REJECTED, "We need you")


def test_changing_the_shift_cancels_its_requests(staff, run_commits):
    shift = shift_at(staff.ali, FRIDAY)
    swap = run_commits(
        services.request_swap, staff.ali, shift=shift, kind="cover", target=staff.vali
    )
    run_commits(services.update_shift, shift, by=staff.manager, starts_at=time(10, 0))
    swap.refresh_from_db()
    assert swap.status == ShiftSwap.Status.CANCELLED


def test_inbox_buttons_run_the_same_services(staff, run_commits):
    from apps.inbox import services as inbox

    shift = shift_at(staff.ali, FRIDAY)
    run_commits(services.request_swap, staff.ali, shift=shift, kind="cover", target=staff.vali)
    offered = Notification.objects.get(kind="attendance.cover_request")
    message = run_commits(inbox.run_action, offered.pk, "accept", by=staff.vali)
    assert "manager" in message
    copy = Notification.objects.get(kind="attendance.swap", recipient=staff.manager)
    message = run_commits(inbox.run_action, copy.pk, "approve", by=staff.manager)
    shift.refresh_from_db()
    assert shift.membership == staff.vali
    assert message == "Swap approved."
