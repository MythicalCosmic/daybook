"""Review sweep of every projects endpoint (docs/PLAN-OWNER.md §2.3 rule 21, §2.6, §13.3):

- another company's id answers 404 everywhere, the same as a hidden project;
- no dashboard access answers 403 on every owner endpoint;
- ids in payloads (lead, branch, people, lists, milestones, accounts) from another company or
  outside the caller's branch scope answer 404, never act;
- hidden fields stay hidden (budget and spending without money access, other people's time);
- list endpoints don't grow their query count with the number of projects or cards.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.companies.models import Branch
from apps.projects import services
from apps.projects.models import Project, ProjectMember, TimeEntry
from apps.projects.tests.factories import card, lists, project, team

pytestmark = pytest.mark.django_db


@pytest.fixture
def people(company, member):
    return team(company, member)


@pytest.fixture
def reno(company, people):
    reno = project(company, people["owner"], lead=people["manager"], key="RENO", budget="1000000")
    services.add_member(reno, people["aziz"], by=people["owner"])
    return reno


def owner_url(company_id, tail=""):
    return f"/api/v1/owner/companies/{company_id}/projects/{tail}"


def employee_url(company_id, tail=""):
    return f"/api/v1/companies/{company_id}/projects/{tail}"


def project_endpoints(project_id, task_id, list_id, milestone_id, label_id, row_id, entry_id):
    """(method, tail) for every owner endpoint, with real ids of the company's own rows."""
    p = f"{project_id}/"
    return [
        ("get", ""),
        ("post", ""),
        ("get", "summary/"),
        ("get", "people/"),
        ("get", "options/"),
        ("get", "roadmap/"),
        ("get", "settings/"),
        ("patch", "settings/"),
        ("get", "time/"),
        ("post", "time/"),
        ("patch", f"time/{entry_id}/"),
        ("delete", f"time/{entry_id}/"),
        ("get", "timers/"),
        ("post", "timers/"),
        ("post", "timers/stop/"),
        ("get", p),
        ("patch", p),
        ("post", p + "archive/"),
        ("post", p + "restore/"),
        ("post", p + "schedule/"),
        ("get", p + "board/"),
        ("get", p + "cards/"),
        ("post", p + "cards/"),
        ("get", p + f"cards/{task_id}/"),
        ("patch", p + f"cards/{task_id}/"),
        ("post", p + f"cards/{task_id}/move/"),
        ("post", p + f"cards/{task_id}/schedule/"),
        ("get", p + "lists/"),
        ("post", p + "lists/"),
        ("post", p + "lists/reorder/"),
        ("patch", p + f"lists/{list_id}/"),
        ("delete", p + f"lists/{list_id}/"),
        ("get", p + "milestones/"),
        ("post", p + "milestones/"),
        ("patch", p + f"milestones/{milestone_id}/"),
        ("delete", p + f"milestones/{milestone_id}/"),
        ("get", p + "labels/"),
        ("post", p + "labels/"),
        ("patch", p + f"labels/{label_id}/"),
        ("delete", p + f"labels/{label_id}/"),
        ("get", p + "members/"),
        ("post", p + "members/"),
        ("patch", p + f"members/{row_id}/"),
        ("delete", p + f"members/{row_id}/"),
        ("get", p + "updates/"),
        ("post", p + "updates/"),
        ("get", p + "files/"),
        ("post", p + "files/"),
        ("get", p + "links/"),
        ("post", p + "links/"),
        ("get", p + "financials/"),
        ("post", p + "expenses/"),
        ("get", p + "expense-options/"),
        ("get", p + "timeline/"),
    ]


@pytest.fixture
def rows(company, people, reno):
    work = card(reno, people["owner"], assignee=people["aziz"])
    milestone = services.create_milestone(reno, by=people["owner"], name="Launch")
    label = services.create_label(reno, by=people["owner"], name="Paint")
    entry = services.log_time(people["aziz"], day=timezone.localdate(), minutes=30, project=reno)
    row = ProjectMember.objects.get(project=reno, membership=people["aziz"])
    return {
        "project_id": reno.pk,
        "task_id": work.pk,
        "list_id": lists(reno)["To do"].pk,
        "milestone_id": milestone.pk,
        "label_id": label.pk,
        "row_id": row.pk,
        "entry_id": entry.pk,
    }


def _call(client, method, url):
    return getattr(client, method)(url, {}, format="json")


def test_every_owner_endpoint_is_404_for_another_companys_owner(
    company, other_company, people, rows, owner_api, member
):
    stranger = owner_api(member.registered(other_company, "Owner"))
    before = Project.objects.count(), TimeEntry.objects.count()

    for method, tail in project_endpoints(**rows):
        response = _call(stranger, method, owner_url(company.pk, tail))
        assert response.status_code == 404, (method, tail, response.status_code)

    assert (Project.objects.count(), TimeEntry.objects.count()) == before


def test_another_companys_project_ids_are_404_in_my_own_company(
    company, other_company, people, rows, owner_api, member
):
    """An owner of company B, using B's URL with A's ids: every project-scoped row is 404."""
    stranger = owner_api(member.registered(other_company, "Owner"))
    entry = f"time/{rows['entry_id']}/"
    project_scoped = [
        (method, tail)
        for method, tail in project_endpoints(**rows)
        if tail.startswith(f"{rows['project_id']}/") or tail == entry
    ]

    for method, tail in project_scoped:
        response = _call(stranger, method, owner_url(other_company.pk, tail))
        assert response.status_code == 404, (method, tail, response.status_code)


def test_every_owner_endpoint_is_403_without_dashboard_access(company, people, rows, owner_api):
    employee = owner_api(people["aziz"])

    for method, tail in project_endpoints(**rows):
        response = _call(employee, method, owner_url(company.pk, tail))
        assert response.status_code == 403, (method, tail, response.status_code)


def test_employee_endpoints_are_404_for_other_companies_and_hidden_projects(
    company, other_company, people, rows, api_as, member
):
    stranger = api_as(member.registered(other_company))
    outsider = api_as(people["madina"])  # same company, not on the project
    tails = [
        ("get", f"{rows['project_id']}/board/"),
        ("post", f"{rows['project_id']}/cards/{rows['task_id']}/move/"),
        ("get", f"{rows['project_id']}/updates/"),
        ("post", f"{rows['project_id']}/updates/"),
    ]

    for method, tail in tails:
        assert _call(stranger, method, employee_url(company.pk, tail)).status_code in (403, 404)
        assert _call(stranger, method, employee_url(other_company.pk, tail)).status_code == 404
        assert _call(outsider, method, employee_url(company.pk, tail)).status_code == 404
    assert outsider.delete(employee_url(company.pk, f"time/{rows['entry_id']}/")).status_code == 404


# Ids in payloads -------------------------------------------------------------------------


def test_payload_ids_from_another_company_are_refused(
    company, other_company, people, reno, owner_api, member
):
    stranger = member.registered(other_company, "Owner")
    elsewhere = project(other_company, stranger, name="Elsewhere")
    foreign_branch = other_company.branches.first() or Branch.objects.create(
        company=other_company, name="Far"
    )
    client = owner_api(people["owner"])
    work = card(reno, people["owner"], assignee=people["aziz"])

    assert (
        client.post(
            owner_url(company.pk), {"name": "X", "lead": stranger.pk}, format="json"
        ).status_code
        == 404
    )
    assert (
        client.post(
            owner_url(company.pk), {"name": "X", "branch": foreign_branch.pk}, format="json"
        ).status_code
        == 404
    )
    assert (
        client.post(
            owner_url(company.pk, f"{reno.pk}/members/"), {"membership": stranger.pk}, format="json"
        ).status_code
        == 404
    )
    assert (
        client.post(
            owner_url(company.pk, f"{reno.pk}/cards/"),
            {"title": "X", "list": elsewhere.lists.first().pk},
            format="json",
        ).status_code
        == 404
    )
    assert (
        client.post(
            owner_url(company.pk, f"{reno.pk}/cards/{work.pk}/move/"),
            {"list": elsewhere.lists.first().pk, "position": 1},
            format="json",
        ).status_code
        == 404
    )
    assert (
        client.post(
            owner_url(company.pk, "time/"),
            {"day": str(timezone.localdate()), "minutes": 10, "project": elsewhere.pk},
            format="json",
        ).status_code
        == 404
    )
    assert not Project.objects.filter(company=company, name="X").exists()


def test_ids_outside_the_branch_scope_are_404(company, people, owner_api, member):
    first = company.branches.order_by("order", "pk").first()
    far = Branch.objects.create(company=company, name="Yunusobod")
    scoped = member.registered(company, "Manager", home_branch=first)
    scoped.role.permissions = [p for p in scoped.role.permissions if p != "branches.all"]
    scoped.role.save()
    scoped.branches.set([first])
    stranger_here = member.registered(company, home_branch=far)
    stranger_here.branches.set([far])
    client = owner_api(scoped)

    in_far_branch = client.post(owner_url(company.pk), {"name": "Far", "branch": far.pk})
    far_lead = client.post(owner_url(company.pk), {"name": "Far", "lead": stranger_here.pk})
    mine = client.post(owner_url(company.pk), {"name": "Near", "branch": first.pk})

    assert in_far_branch.status_code == 404
    assert far_lead.status_code == 404
    assert mine.status_code == 201
    moved = client.patch(owner_url(company.pk, f"{mine.json()['id']}/"), {"branch": far.pk})
    assert moved.status_code == 404
    assert Project.objects.get(pk=mine.json()["id"]).branch_id == first.pk


# Hidden fields ---------------------------------------------------------------------------


def test_budget_and_spending_are_hidden_without_money_access(company, people, reno, api_as):
    # Aziz is an employee on the project: he sees progress and health, not money.
    items = api_as(people["aziz"]).get(employee_url(company.pk)).json()
    board = api_as(people["aziz"]).get(employee_url(company.pk, f"{reno.pk}/board/")).json()

    assert items[0]["budget"] is None and "spent" not in items[0] and "burn" not in items[0]
    assert board["project"]["budget"] is None
    # The lead manages the project and sees its money.
    lead_items = api_as(people["manager"]).get(employee_url(company.pk)).json()
    assert lead_items[0]["budget"] == "1000000.00"


def test_card_detail_shows_other_peoples_time_only_to_those_who_may_see_it(
    company, people, reno, owner_api, member
):
    work = card(reno, people["owner"], assignee=people["aziz"])
    services.log_time(people["aziz"], day=timezone.localdate(), minutes=45, task=work)
    viewer = member.registered(company, "Accountant")
    services.add_member(reno, viewer, by=people["owner"], role="viewer")

    seen_by_viewer = owner_api(viewer).get(owner_url(company.pk, f"{reno.pk}/cards/{work.pk}/"))
    seen_by_lead = owner_api(people["manager"]).get(
        owner_url(company.pk, f"{reno.pk}/cards/{work.pk}/")
    )

    assert seen_by_viewer.json()["time"] == []
    assert seen_by_viewer.json()["minutes"] == 45  # the total is part of the card
    assert [row["minutes"] for row in seen_by_lead.json()["time"]] == [45]


def test_index_health_filter_pages_over_every_project(company, people, owner_api):
    late = project(
        company,
        people["owner"],
        name="Late one",
        status="active",
        start_on=timezone.localdate() - timedelta(days=30),
        due_on=timezone.localdate() - timedelta(days=1),
    )
    for n in range(3):
        project(company, people["owner"], name=f"Fine {n}", status="active")

    page = owner_api(people["owner"]).get(
        owner_url(company.pk), {"health": "off_track", "page_size": 1}
    )

    assert page.json()["count"] == 1
    assert [row["id"] for row in page.json()["results"]] == [late.pk]


# Query counts ----------------------------------------------------------------------------


def _queries(client, url, params=None) -> int:
    with CaptureQueriesContext(connection) as captured:
        response = client.get(url, params or {})
    assert response.status_code == 200, response.content
    return len(captured)


def _grow_projects(company, people, n):
    for index in range(n):
        made = project(
            company,
            people["owner"],
            name=f"Project {index} {timezone.now().timestamp()}",
            status="active",
            lead=people["manager"],
            budget="500000",
            member_ids=[people["aziz"].pk],
        )
        services.create_milestone(
            made, by=people["owner"], name="M", due_on=timezone.localdate() + timedelta(days=5)
        )
        services.post_update(made, by=people["manager"], health="on_track", text="ok")
        card(made, people["owner"], assignee=people["aziz"])


@pytest.mark.parametrize(
    "tail", ["", "summary/", "roadmap/", "time/"], ids=["index", "summary", "roadmap", "time"]
)
def test_list_endpoints_dont_grow_with_projects(company, people, owner_api, tail):
    client = owner_api(people["owner"])
    _grow_projects(company, people, 2)
    few = _queries(client, owner_url(company.pk, tail))
    _grow_projects(company, people, 4)
    many = _queries(client, owner_url(company.pk, tail))
    assert many == few, (tail, few, many)


def test_the_index_doesnt_grow_for_a_manager_either(company, people, owner_api):
    client = owner_api(people["manager"])
    _grow_projects(company, people, 2)
    few = _queries(client, owner_url(company.pk))
    _grow_projects(company, people, 4)
    assert _queries(client, owner_url(company.pk)) == few


def test_my_projects_dont_grow_with_projects(company, people, api_as):
    client = api_as(people["aziz"])
    _grow_projects(company, people, 2)
    few = _queries(client, employee_url(company.pk))
    _grow_projects(company, people, 4)
    assert _queries(client, employee_url(company.pk)) == few


@pytest.mark.parametrize("tail", ["board/", "cards/", "timeline/", "members/"])
def test_board_endpoints_dont_grow_with_cards(company, people, reno, owner_api, tail):
    client = owner_api(people["owner"])
    label = services.create_label(reno, by=people["owner"], name="Paint")
    for n in range(2):
        card(reno, people["owner"], title=f"A {n}", assignee=people["aziz"], label_ids=[label.pk])
    few = _queries(client, owner_url(company.pk, f"{reno.pk}/{tail}"))
    for n in range(6):
        work = card(
            reno,
            people["owner"],
            title=f"B {n}",
            assignee=people["madina"] if n % 2 else people["aziz"],
            label_ids=[label.pk],
            checklist=["one", "two"],
        )
        services.log_time(people["owner"], day=timezone.localdate(), minutes=5, task=work)
    many = _queries(client, owner_url(company.pk, f"{reno.pk}/{tail}"))
    assert many == few, (tail, few, many)


def test_employee_board_doesnt_grow_with_cards(company, people, reno, api_as):
    client = api_as(people["aziz"])
    card(reno, people["owner"], assignee=people["aziz"])
    few = _queries(client, employee_url(company.pk, f"{reno.pk}/board/"))
    for n in range(5):
        card(reno, people["owner"], title=f"B {n}", assignee=people["aziz"])
    assert _queries(client, employee_url(company.pk, f"{reno.pk}/board/")) == few


def test_money_on_the_index_is_a_string_and_matches_the_ledger(company, people, reno, owner_api):
    from apps.finance import defaults as finance_defaults
    from apps.finance import services as finance
    from apps.finance.models import Category

    finance_defaults.ensure(company)
    account = finance.create_account(company, by=people["owner"], kind="bank", name="Bank")
    finance.record_transaction(
        company,
        by=people["owner"],
        kind="owner",
        amount=Decimal("5000000"),
        account=account,
        occurred_on=timezone.localdate() - timedelta(days=2),
    )
    services.add_expense(
        reno,
        by=people["owner"],
        amount=Decimal("300000"),
        account=account,
        category=Category.objects.get(company=company, system_code="repairs"),
        occurred_on=timezone.localdate(),
    )

    item = owner_api(people["owner"]).get(owner_url(company.pk)).json()["results"][0]

    assert item["spent"] == "300000.00" and item["budget"] == "1000000.00" and item["burn"] == 30
