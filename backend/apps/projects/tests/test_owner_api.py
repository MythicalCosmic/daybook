"""Owner endpoints of projects: permissions (200/403), other company (404), branch isolation,
hidden fields, money as strings (docs/PLAN-OWNER.md §2.3 rule 21, §13.3)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.companies.models import Branch
from apps.projects import services
from apps.projects.models import Project, TimeEntry
from apps.projects.tests.factories import card, lists, project, team
from apps.tasks.models import Proof, Task

pytestmark = pytest.mark.django_db


@pytest.fixture
def people(company, member):
    return team(company, member)


def url(company, tail=""):
    return f"/api/v1/owner/companies/{company.pk}/projects/{tail}"


@pytest.fixture
def reno(company, people):
    reno = project(company, people["owner"], lead=people["manager"], key="RENO", budget="1000000")
    services.add_member(reno, people["aziz"], by=people["owner"])
    return reno


def fund(company, owner):
    from apps.finance import defaults as finance_defaults
    from apps.finance import services as finance

    finance_defaults.ensure(company)
    account = finance.create_account(company, by=owner, kind="bank", name="Bank")
    finance.record_transaction(
        company,
        by=owner,
        kind="owner",
        amount=Decimal("50000000"),
        account=account,
        occurred_on=timezone.localdate() - timedelta(days=3),
    )
    return account


# Index ----------------------------------------------------------------------------------


def test_the_index_lists_projects_with_progress_health_and_burn(company, people, reno, owner_api):
    card(reno, people["owner"])

    response = owner_api(people["owner"]).get(url(company))

    assert response.status_code == 200
    item = response.json()["results"][0]
    assert item["key"] == "RENO"
    assert item["progress"] == {"done": 0, "total": 1, "overdue": 0, "percent": 0}
    assert item["health"] == "on_track"
    assert item["budget"] == "1000000.00"  # money is a string
    assert item["spent"] == "0.00"
    assert item["burn"] == 0
    assert item["lead"]["name"] == str(people["manager"])
    assert item["my_role"] == "member"  # gave themselves a card, so they joined


def test_filters(company, people, reno, owner_api):
    project(company, people["owner"], name="Website", status="active")
    client = owner_api(people["owner"])

    assert [p["key"] for p in client.get(url(company), {"status": "active"}).json()["results"]] == [
        "WEBS"
    ]
    assert [p["key"] for p in client.get(url(company), {"q": "reno"}).json()["results"]] == ["RENO"]
    assert [
        p["key"] for p in client.get(url(company), {"lead": people["manager"].pk}).json()["results"]
    ] == ["RENO"]
    assert client.get(url(company), {"health": "off_track"}).json()["results"] == []


def test_money_is_hidden_from_people_who_dont_see_it(company, people, reno, owner_api, member):
    # An accountant-like viewer of a company-wide project: dashboard access but no project
    # management and no finance.view.
    viewer = member.registered(company, "Accountant")
    viewer.role.permissions = [p for p in viewer.role.permissions if p != "finance.view"]
    viewer.role.save()
    services.update_project(reno, by=people["owner"], visibility="company")

    item = owner_api(viewer).get(url(company)).json()["results"][0]

    assert "spent" not in item and "burn" not in item
    assert owner_api(viewer).get(url(company, f"{reno.pk}/financials/")).status_code == 403


def test_creating_needs_projects_manage(company, people, owner_api, member):
    accountant = member.registered(company, "Accountant")

    denied = owner_api(accountant).post(url(company), {"name": "Mine"}, format="json")
    created = owner_api(people["owner"]).post(
        url(company),
        {"name": "Yunusobod refit", "budget": "5000000.00", "lead": people["manager"].pk},
        format="json",
    )

    assert denied.status_code == 403
    assert created.status_code == 201
    body = created.json()
    assert body["key"] == "YR" and body["budget"] == "5000000.00"
    assert [row["name"] for row in body["lists"]][-1] == "Done"
    assert body["capabilities"]["manage"] is True


def test_a_bad_key_is_a_field_error_with_a_code(company, people, reno, owner_api):
    response = owner_api(people["owner"]).post(
        url(company), {"name": "X", "key": "RENO"}, format="json"
    )
    assert response.status_code == 400
    assert response.json()["code"] == "key"


def test_another_companys_project_is_404(company, other_company, people, reno, owner_api, member):
    stranger = member.registered(other_company, "Owner")

    assert (
        owner_api(stranger).get(f"/api/v1/owner/companies/{company.pk}/projects/").status_code
        == 404
    )
    assert (
        owner_api(stranger)
        .get(f"/api/v1/owner/companies/{other_company.pk}/projects/{reno.pk}/")
        .status_code
        == 404
    )


def test_a_members_only_project_is_404_for_others(company, people, reno, owner_api, member):
    accountant = member.registered(company, "Accountant")
    assert owner_api(accountant).get(url(company, f"{reno.pk}/")).status_code == 404
    assert owner_api(accountant).get(url(company)).json()["results"] == []


def test_employees_have_no_dashboard(company, people, reno, owner_api):
    assert owner_api(people["aziz"]).get(url(company)).status_code == 403


def test_branch_isolation(company, people, owner_api, member):
    first = company.branches.order_by("order", "pk").first()
    other = Branch.objects.create(company=company, name="Yunusobod")
    scoped = member.registered(company, "Manager")
    scoped.role.permissions = [p for p in scoped.role.permissions if p != "branches.all"]
    scoped.role.save()
    scoped.branches.set([first])
    project(company, people["owner"], name="Here", branch=first)
    there = project(company, people["owner"], name="There", branch=other)

    keys = [p["name"] for p in owner_api(scoped).get(url(company)).json()["results"]]

    assert keys == ["Here"]
    assert owner_api(scoped).get(url(company, f"{there.pk}/")).status_code == 404


def test_summary(company, people, reno, owner_api):
    card(reno, people["owner"])
    services.update_project(reno, by=people["owner"], status="active")

    body = owner_api(people["owner"]).get(url(company, "summary/")).json()

    assert body["active"] == 1 and body["budget"] == "1000000.00" and body["spent"] == "0.00"


# One project and its board --------------------------------------------------------------


def test_detail_and_edit(company, people, reno, owner_api):
    client = owner_api(people["manager"])  # the lead

    detail = client.get(url(company, f"{reno.pk}/")).json()
    changed = client.patch(
        url(company, f"{reno.pk}/"), {"name": "Big refit", "status": "active"}, format="json"
    )

    assert detail["capabilities"]["manage"] is True
    assert changed.status_code == 200
    assert changed.json()["name"] == "Big refit"
    assert (
        owner_api(people["owner"]).post(url(company, f"{reno.pk}/archive/")).json()["archived_at"]
    )
    assert (
        owner_api(people["owner"]).post(url(company, f"{reno.pk}/restore/")).json()["archived_at"]
        is None
    )


def test_the_board_has_lists_and_cards_in_one_go(
    company, people, reno, owner_api, django_assert_max_num_queries
):
    for n in range(6):
        card(reno, people["owner"], title=f"Card {n}", assignee=people["aziz"])
    client = owner_api(people["owner"])

    with django_assert_max_num_queries(40):
        body = client.get(url(company, f"{reno.pk}/board/")).json()

    assert [row["name"] for row in body["lists"]] == [
        "Backlog",
        "To do",
        "In progress",
        "Review",
        "Done",
    ]
    assert len(body["cards"]) == 6
    first = body["cards"][0]
    assert first["key"] == "RENO-1" and first["assignee"]["name"] == str(people["aziz"])
    assert {p["id"] for p in body["people"]} >= {people["manager"].pk, people["aziz"].pk}


def test_quick_add_and_move(company, people, reno, owner_api):
    client = owner_api(people["owner"])
    to_do = lists(reno)["To do"]

    created = client.post(
        url(company, f"{reno.pk}/cards/"),
        {"title": "Order tiles", "list": to_do.pk, "assignee": people["aziz"].pk},
        format="json",
    )
    task_id = created.json()["id"]
    moved = client.post(
        url(company, f"{reno.pk}/cards/{task_id}/move/"),
        {"list": lists(reno)["In progress"].pk, "position": 512.5},
        format="json",
    )

    assert created.status_code == 201 and created.json()["list_id"] == to_do.pk
    assert moved.status_code == 200
    assert moved.json()["card"]["list_id"] == lists(reno)["In progress"].pk
    assert moved.json()["card"]["position"] == 512.5


def test_moving_a_card_that_needs_proof_answers_needs_proof(company, people, reno, owner_api):
    photo = card(reno, people["owner"], assignee=people["owner"], proof=Proof.PHOTO)

    response = owner_api(people["owner"]).post(
        url(company, f"{reno.pk}/cards/{photo.pk}/move/"),
        {"list": lists(reno)["Done"].pk, "position": 1},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["code"] == "needs_proof"


def test_card_detail_and_edit(company, people, reno, owner_api):
    work = card(reno, people["owner"], assignee=people["aziz"], checklist=["Primer", "Two coats"])
    label = services.create_label(reno, by=people["owner"], name="Paint")
    client = owner_api(people["owner"])

    detail = client.get(url(company, f"{reno.pk}/cards/{work.pk}/")).json()
    changed = client.patch(
        url(company, f"{reno.pk}/cards/{work.pk}/"), {"label_ids": [label.pk]}, format="json"
    )

    assert [item["text"] for item in detail["checklist"]] == ["Primer", "Two coats"]
    assert detail["checklist_total"] == 2
    assert changed.json()["label_ids"] == [label.pk]


def test_cards_of_another_project_are_404(company, people, reno, owner_api):
    other = project(company, people["owner"], name="Other")
    elsewhere = card(other, people["owner"])
    response = owner_api(people["owner"]).get(url(company, f"{reno.pk}/cards/{elsewhere.pk}/"))
    assert response.status_code == 404


def test_lists_milestones_labels_members(company, people, reno, owner_api):
    client = owner_api(people["owner"])

    new_list = client.post(
        url(company, f"{reno.pk}/lists/"), {"name": "QA", "wip_limit": 2}, format="json"
    )
    milestone = client.post(
        url(company, f"{reno.pk}/milestones/"),
        {"name": "Launch", "due_on": str(timezone.localdate() + timedelta(days=9))},
        format="json",
    )
    label = client.post(
        url(company, f"{reno.pk}/labels/"), {"name": "Urgent", "color": "chart-1"}, format="json"
    )
    members = client.post(
        url(company, f"{reno.pk}/members/"), {"membership": people["madina"].pk}, format="json"
    )

    assert new_list.status_code == 201 and new_list.json()["wip_limit"] == 2
    assert milestone.status_code == 201 and milestone.json()["overdue"] is False
    assert label.status_code == 201
    assert members.status_code == 201
    assert {row["person"]["id"] for row in members.json()} >= {
        people["madina"].pk,
        people["manager"].pk,
    }
    lead_row = next(row for row in members.json() if row["role"] == "lead")
    assert lead_row["person"]["id"] == people["manager"].pk
    assert (
        client.delete(url(company, f"{reno.pk}/lists/{new_list.json()['id']}/")).status_code == 204
    )


def test_members_cant_manage_the_board(company, people, reno, owner_api, member):
    viewer = member.registered(company, "Accountant")
    services.add_member(reno, viewer, by=people["owner"])

    response = owner_api(viewer).post(
        url(company, f"{reno.pk}/lists/"), {"name": "Mine"}, format="json"
    )

    assert response.status_code == 403


def test_updates_files_links(company, people, reno, owner_api):
    from apps.tasks.tests.factories import jpeg

    client = owner_api(people["manager"])

    update = client.post(
        url(company, f"{reno.pk}/updates/"), {"health": "at_risk", "text": "Late"}, format="json"
    )
    upload = client.post(
        url(company, f"{reno.pk}/files/"), {"file": jpeg("plan.jpg")}, format="multipart"
    )
    link = client.post(
        url(company, f"{reno.pk}/links/"),
        {"title": "Plan", "url": "https://figma.com/x"},
        format="json",
    )
    files = client.get(url(company, f"{reno.pk}/files/")).json()

    assert update.status_code == 201 and update.json()["health"] == "at_risk"
    assert upload.status_code == 201
    assert files[0]["url"].startswith("/api/v1/files/")
    assert link.status_code == 201
    download = client.get(files[0]["url"])
    assert download.status_code == 200 and download["Content-Type"] == "image/jpeg"


def test_financials_and_expenses(company, people, reno, owner_api):
    from apps.finance.models import Category

    account = fund(company, people["owner"])
    repairs = Category.objects.get(company=company, system_code="repairs")
    client = owner_api(people["owner"])

    options = client.get(url(company, f"{reno.pk}/expense-options/")).json()
    created = client.post(
        url(company, f"{reno.pk}/expenses/"),
        {
            "amount": "250000.00",
            "account": account.pk,
            "category": repairs.pk,
            "occurred_on": str(timezone.localdate()),
            "description": "Tiles",
        },
        format="json",
    )
    money = client.get(url(company, f"{reno.pk}/financials/")).json()

    assert account.pk in [a["id"] for a in options["accounts"]]
    assert created.status_code == 201 and created.json()["base_amount"] == "-250000.00"
    assert money["spent"] == "250000.00" and money["budget"] == "1000000.00"
    assert money["burn"] == 25 and money["remaining"] == "750000.00"
    assert money["transactions"][0]["description"] == "Tiles"
    assert money["labour_cost"] is None  # owners see payroll; no rates yet


def test_labour_cost_is_hidden_without_payroll_view(company, people, reno, owner_api):
    money = owner_api(people["manager"]).get(url(company, f"{reno.pk}/financials/")).json()
    assert "labour_cost" not in money
    assert money["margin_includes_labour"] is False


def test_expenses_need_finance_record(company, people, reno, owner_api):
    response = owner_api(people["manager"]).post(
        url(company, f"{reno.pk}/expenses/"),
        {"amount": "1.00", "account": 1, "category": 1, "occurred_on": str(timezone.localdate())},
        format="json",
    )
    assert response.status_code == 403


def test_timeline_and_reschedule(company, people, reno, owner_api):
    work = card(reno, people["owner"], assignee=people["aziz"])
    client = owner_api(people["owner"])
    day = timezone.localdate() + timedelta(days=10)

    rows = client.get(url(company, f"{reno.pk}/timeline/")).json()["rows"]
    moved = client.post(
        url(company, f"{reno.pk}/cards/{work.pk}/schedule/"),
        {"start_on": str(day - timedelta(days=2)), "end_on": str(day)},
        format="json",
    )

    assert rows[0]["id"] == work.pk and rows[0]["editable"] is True
    assert moved.status_code == 200 and moved.json()["start_on"] == str(day - timedelta(days=2))


def test_roadmap_shows_every_visible_project(company, people, reno, owner_api):
    project(company, people["owner"], name="Website", status="active")
    client = owner_api(people["owner"])

    rows = client.get(url(company, "roadmap/")).json()["rows"]
    moved = client.post(
        url(company, f"{reno.pk}/schedule/"),
        {
            "start_on": str(timezone.localdate()),
            "end_on": str(timezone.localdate() + timedelta(days=20)),
        },
        format="json",
    )

    assert {row["key"] for row in rows} == {"RENO", "WEBS"}
    assert moved.status_code == 200
    reno.refresh_from_db()
    assert reno.due_on == timezone.localdate() + timedelta(days=20)


# Time -----------------------------------------------------------------------------------


def test_time_week_grid_logging_and_timers(company, people, reno, owner_api):
    client = owner_api(people["manager"])  # leads reno
    services.log_time(people["aziz"], day=timezone.localdate(), minutes=60, project=reno)

    logged = client.post(
        url(company, "time/"),
        {"day": str(timezone.localdate()), "minutes": 30, "project": reno.pk},
        format="json",
    )
    week = client.get(url(company, "time/"), {"project": reno.pk}).json()
    started = client.post(url(company, "timers/"), {"project": reno.pk}, format="json")
    running = client.get(url(company, "timers/")).json()
    stopped = client.post(url(company, "timers/stop/"))

    assert logged.status_code == 201
    assert week["total"] == 90 and len(week["rows"]) == 2
    assert week["rows"][0]["person"]["id"] == people["aziz"].pk  # most time first
    assert started.status_code == 201 and running[0]["project_key"] == "RENO"
    assert stopped.status_code == 200 and stopped.json()["source"] == "timer"


def test_time_is_private_to_people_who_may_see_it(company, people, reno, owner_api, member):
    accountant = member.registered(company, "Accountant")
    services.log_time(people["aziz"], day=timezone.localdate(), minutes=60, project=reno)

    week = owner_api(accountant).get(url(company, "time/")).json()

    assert week["total"] == 0


def test_editing_someone_elses_time_is_refused(company, people, reno, owner_api, member):
    entry = services.log_time(people["aziz"], day=timezone.localdate(), minutes=60, project=reno)
    other = member.registered(company, "Accountant")

    response = owner_api(other).patch(
        url(company, f"time/{entry.pk}/"), {"minutes": 5}, format="json"
    )

    assert response.status_code == 404
    assert TimeEntry.objects.get(pk=entry.pk).minutes == 60


def test_settings(company, people, owner_api):
    client = owner_api(people["owner"])

    changed = client.patch(
        url(company, "settings/"), {"weekly_nudge": False, "at_risk_days": 10}, format="json"
    )

    assert changed.status_code == 200
    assert changed.json()["weekly_nudge"] is False and changed.json()["at_risk_days"] == 10
    assert changed.json()["default_lists"][-1] == "Done"


def test_people_and_options(company, people, owner_api):
    client = owner_api(people["owner"])
    names = {row["name"] for row in client.get(url(company, "people/")).json()}
    options = client.get(url(company, "options/")).json()
    assert str(people["aziz"]) in names
    assert options["can_create"] is True and options["branches"]


def test_unused_cancelled_cards_stay_off_the_board(company, people, reno, owner_api):
    work = card(reno, people["owner"])
    Task.objects.filter(pk=work.pk).update(status=Task.Status.CANCELLED)
    assert owner_api(people["owner"]).get(url(company, f"{reno.pk}/board/")).json()["cards"] == []
    assert Project.objects.filter(pk=reno.pk).exists()
