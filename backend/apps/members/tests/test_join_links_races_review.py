"""Races around team links, with real transactions in two threads (bulk/review)."""

import threading
import time

import pytest
from django.db import OperationalError, connection

from apps.accounts.tests.factories import UserFactory
from apps.members import join_links, services
from apps.members.models import JoinLink, Membership

pytestmark = pytest.mark.django_db(transaction=True)


def opened(link):
    user = UserFactory(phone="+998901112233")
    membership, _admitted = join_links.open_link(user, link.start_param)
    return membership


def run(target, errors):
    def body():
        try:
            target()
        except Exception as exc:  # noqa: BLE001 - collected for the assertion
            errors.append(exc)
        finally:
            connection.close()

    thread = threading.Thread(target=body)
    thread.start()
    return thread


def test_the_last_place_goes_to_one_of_two_people_finishing_together(company, member, monkeypatch):
    """Control (passes): the link's row lock serialises the last place."""
    owner = member.registered(company, "Owner")
    link = join_links.create_link(company, by=owner, name="Meeting", max_uses=1)
    first, second = opened(link), opened(link)
    real_approve = services.approve
    first_in = threading.Event()

    def slow_approve(*args, **kwargs):  # the first holds the link's lock for a moment
        first_in.set()
        time.sleep(0.5)
        return real_approve(*args, **kwargs)

    monkeypatch.setattr(services, "approve", slow_approve)
    errors = []

    def finish(membership):
        return lambda: services.complete_onboarding(
            membership, first_name="A", last_name="B", position_id=None
        )

    one = run(finish(first), errors)
    first_in.wait(5)
    two = run(finish(second), errors)
    one.join(10)
    two.join(10)

    assert errors == []
    statuses = sorted(
        Membership.objects.filter(pk__in=[first.pk, second.pk]).values_list("status", flat=True)
    )
    assert statuses == [Membership.Status.APPROVED, Membership.Status.PENDING]
    assert JoinLink.objects.get(pk=link.pk).uses == 1


def test_deleting_a_link_while_someone_finishes_through_it_doesnt_deadlock(
    company, member, monkeypatch
):
    """complete_onboarding locks the membership, then the link (admit); delete_link locks the
    link, then updates the memberships pointing at it (on_delete=SET_NULL). Interleaved, the
    two wait for each other and PostgreSQL kills one with "deadlock detected" (a 500)."""
    owner = member.registered(company, "Owner")
    link = join_links.create_link(company, by=owner, name="Meeting")
    joining = opened(link)
    joining.user.phone = "+998901112233"
    joining.user.save()

    membership_locked, link_locked = threading.Event(), threading.Event()
    real_admit, real_lock = services.admit, join_links._lock

    def admit_after_the_delete_started(membership, **kwargs):
        membership_locked.set()
        link_locked.wait(5)
        time.sleep(0.5)  # the delete reaches its UPDATE of the memberships and waits for ours
        return real_admit(membership, **kwargs)

    def lock_and_tell(link):
        locked = real_lock(link)
        link_locked.set()
        return locked

    monkeypatch.setattr(services, "admit", admit_after_the_delete_started)
    monkeypatch.setattr(join_links, "_lock", lock_and_tell)
    errors = []

    finishing = run(
        lambda: services.complete_onboarding(
            joining, first_name="Aziz", last_name="Karimov", position_id=None
        ),
        errors,
    )
    membership_locked.wait(5)
    deleting = run(lambda: join_links.delete_link(link, by=owner), errors)
    finishing.join(15)
    deleting.join(15)

    deadlocks = [exc for exc in errors if isinstance(exc, OperationalError)]
    assert not deadlocks, deadlocks
