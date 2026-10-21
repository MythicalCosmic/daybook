"""Fixes from the package review: moving without a position, time for others, money in the
base currency, and timeline bars that only move when the deadline may change."""

from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.projects import queries, services
from apps.projects.services import ProjectError
from apps.projects.tests.factories import card, lists, project, team
from apps.signin.tokens import OwnerAccessToken
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db


@pytest.fixture
def people(company, member):
    return team(company, member)


def test_move_to_a_list_without_a_position_puts_the_card_last(company, people):
    reno = project(company, people["owner"])
    first = card(reno, people["owner"], title="One")
    second = card(reno, people["owner"], title="Two")
    doing = lists(reno)["In progress"]
    services.move_card(first, doing, 10, by=people["owner"])

    moved = services.move_card(second, doing, None, by=people["owner"])
    again = services.move_card(moved, doing, None, by=people["owner"])  # same list: stays

    assert moved.list_position > Task.objects.get(pk=first.pk).list_position
    assert again.list_position == moved.list_position


def test_time_for_others_only_for_approved_people_on_the_project(company, people):
    reno = project(company, people["owner"], lead=people["manager"])

    with pytest.raises(ProjectError):  # Madina isn't on the project
        services.log_time(
            people["manager"],
            day=timezone.localdate(),
            minutes=30,
            project=reno,
            membership=people["madina"],
        )
    services.add_member(reno, people["madina"], by=people["owner"])
    people["madina"].status = "blocked"
    people["madina"].save()
    with pytest.raises(ProjectError):  # no longer an approved member
        services.log_time(
            people["manager"],
            day=timezone.localdate(),
            minutes=30,
            project=reno,
            membership=people["madina"],
        )


def test_a_foreign_currency_budget_is_converted_both_ways(company, people):
    from apps.finance.models import CompanyRate

    CompanyRate.objects.create(
        company=company, currency="USD", date=timezone.localdate(), rate=Decimal("12500")
    )
    dollars = project(company, people["owner"], budget="1000", budget_currency="USD")
    assert queries.budget_in_base(dollars) == Decimal("12500000.00")

    company.base_currency = "USD"
    company.save()
    soums = project(
        company, people["owner"], name="Soum budget", budget="25000000", budget_currency="UZS"
    )
    soums.company.refresh_from_db()
    assert queries.budget_in_base(soums) == Decimal("2000.00")  # not 25 000 000 dollars


def test_open_receivables_are_valued_in_the_base_currency(company, people):
    from apps.finance import defaults as finance_defaults
    from apps.finance import services as finance
    from apps.finance.models import CompanyRate, Counterparty

    finance_defaults.ensure(company)
    CompanyRate.objects.create(
        company=company, currency="USD", date=timezone.localdate(), rate=Decimal("12000")
    )
    client = Counterparty.objects.create(company=company, name="Artel")
    reno = project(company, people["owner"], client=client)
    finance.open_debt(
        company,
        by=people["owner"],
        direction="receivable",
        kind="trade",
        amount=Decimal("100"),
        currency="USD",
        issued_on=timezone.localdate(),
        counterparty=client,
        category="sales",
        project=reno,
    )

    assert queries.financials(reno, viewer=people["owner"])["receivable"] == Decimal("1200000.00")


def test_timeline_bars_move_only_for_people_who_may_change_the_deadline(company, people):
    reno = project(company, people["owner"], lead=people["manager"])
    work = card(reno, people["owner"], assignee=people["aziz"])
    # The lead edits the board, but the owner handed this task out and the lead can't hand out
    # tasks here, so its deadline isn't theirs to move.
    role = people["manager"].role
    role.permissions = [p for p in role.permissions if p != "tasks.assign"]
    role.save()
    client = APIClient()
    token = OwnerAccessToken.for_user(people["manager"].user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    rows = client.get(f"/api/v1/owner/companies/{company.pk}/projects/{reno.pk}/timeline/").json()[
        "rows"
    ]

    assert rows[0]["id"] == work.pk and rows[0]["editable"] is False


def test_the_off_track_watch_keeps_going_when_one_company_fails(
    company, other_company, people, member, monkeypatch
):
    from datetime import timedelta

    from apps.projects import jobs

    today = timezone.localdate()
    late = project(
        company,
        people["owner"],
        status="active",
        start_on=today - timedelta(days=20),
        due_on=today - timedelta(days=1),
    )
    boss = member.registered(other_company, "Owner")
    project(other_company, boss, name="Elsewhere", status="active")
    real = jobs._watch_company

    def flaky(projects, now):
        if projects[0].company_id == other_company.pk:
            raise RuntimeError("bad data")
        return real(projects, now)

    monkeypatch.setattr(jobs, "_watch_company", flaky)

    assert jobs.watch_health() >= 1
    late.refresh_from_db()
    assert late.health == "off_track"
