"""Every registered calendar source colours its items with a design token (`CALENDAR_COLORS`,
"chart-3", "danger"), never a raw colour, so the dashboard and the mini app can map it to their
own CSS variables and a source looks the same in both, in light and dark (§13.5)."""

import logging
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.agenda.tests.factories import EventFactory
from apps.attendance.models import WorkShift
from apps.attendance.tests.factories import shift_at
from apps.companies.models import Feature
from apps.console import registry
from apps.console.registry import CALENDAR_COLORS, CalendarItem
from apps.finance import services as finance
from apps.finance.tests.factories import CounterpartyFactory
from apps.projects import services as projects
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory
from apps.timeoff.models import Holiday, TimeOff

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(company, member):
    """An owner of a company with every module on, and something in every calendar source over
    the coming week, in each of the states a source colours differently."""
    company.features = list(Feature.values)
    company.save(update_fields=["features"])
    branch = company.branches.order_by("order", "pk").first()
    owner = member.registered(company, "Owner", home_branch=branch)
    worker = member.registered(company, home_branch=branch)
    now = timezone.now()
    today = timezone.localdate()
    for kind in ("meeting", "training", "inventory", "celebration", "deadline", "other"):
        EventFactory(company=company, kind=kind, start=now + timedelta(days=1))
    TaskFactory(assignee=worker, created_by=owner, due_at=now + timedelta(days=1))
    TaskFactory(
        assignee=worker,
        created_by=owner,
        due_at=now + timedelta(days=2),
        status=Task.Status.DONE,
        completed_at=now,
    )
    for status in (TimeOff.Status.APPROVED, TimeOff.Status.PENDING):
        TimeOff.objects.create(
            company=company,
            membership=worker,
            first_day=today + timedelta(days=2),
            last_day=today + timedelta(days=3),
            status=status,
        )
    Holiday.objects.create(company=company, date=today + timedelta(days=4), name="Navruz")
    party = CounterpartyFactory(company=company, name="Barakat")
    for direction, kind in (("payable", "bill"), ("receivable", "trade")):
        finance.open_debt(
            company,
            by=owner,
            direction=direction,
            kind=kind,
            amount=Decimal("1000"),
            currency="UZS",
            issued_on=today,
            due_on=today + timedelta(days=2),
            counterparty=party,
            is_opening=True,
        )
    shift_at(owner, today + timedelta(days=1))
    shift_at(owner, today + timedelta(days=2), status=WorkShift.Status.LEAVE)
    shift_at(worker, today + timedelta(days=1))
    reno = projects.create_project(company, by=owner, name="Renovation", key="RENO")
    projects.create_milestone(reno, by=owner, name="Walls up", due_on=today + timedelta(days=5))
    return owner


def test_every_registered_source_colours_its_items_with_tokens(company, owner):
    first, last = timezone.localdate(), timezone.localdate() + timedelta(days=7)
    empty = []
    for source in registry.CALENDAR_SOURCES:
        assert registry.usable(source, owner), f"{source.key}: give the owner a way to see it"
        items = source.events(company, first, last, owner)
        if not items:
            empty.append(source.key)
        wrong = {item.color for item in items} - CALENDAR_COLORS
        assert not wrong, f"{source.key} sends colours that aren't tokens: {sorted(wrong)}"
    # A new source joins this test with something to show, so its colours are checked too.
    assert not empty, f"put something in these sources in the fixture: {empty}"


def test_a_colour_that_isnt_a_token_is_dropped_and_logged(company, owner, caplog):
    day = date(2026, 10, 21)
    with registry.CALENDAR_SOURCES.isolated():
        registry.CALENDAR_SOURCES.add(
            registry.CalendarSource(
                "agenda.legacy",
                "agenda",
                None,
                None,
                "Legacy",
                lambda c, s, e, m: [
                    CalendarItem("a", "x", "Hex", day, None, True, "#c67139", ""),
                    CalendarItem("b", "x", "CSS", day, None, True, "var(--c-danger)", ""),
                    CalendarItem("c", "x", "Token", day, None, True, "chart-4", ""),
                    CalendarItem("d", "x", "Default", day, None, True, "", ""),
                ],
            )
        )
        with caplog.at_level(logging.WARNING, logger="apps.console.registry"):
            items = registry.collect_calendar(owner, day, day, sources=["agenda.legacy"])

    assert {item.title: item.color for item in items} == {
        "Hex": "",
        "CSS": "",
        "Token": "chart-4",
        "Default": "",
    }
    logged = [r for r in caplog.records if "agenda.legacy" in r.getMessage()]
    assert len(logged) == 1 and "#c67139" in logged[0].getMessage()
