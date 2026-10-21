"""The team directory and Person 360 on the owner API (`people/`)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.companies.tests.factories import BranchFactory
from apps.console import registry
from apps.console.perms import AnyOf
from apps.members.models import AccessRole, Membership
from apps.members.permissions import Perm
from apps.members.tests.factories import AccessRoleFactory, PositionFactory
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db

URL = "/api/v1/owner/companies/{cid}/people/"


def url(company, suffix=""):
    return URL.format(cid=company.pk) + suffix


@pytest.fixture
def branches(company):
    first = company.branches.order_by("pk").first()
    first.name = "Chilonzor"
    first.save()
    second = BranchFactory(company=company, name="Yunusobod", order=1)
    return first, second


@pytest.fixture
def owner(company, member, branches):
    return member.registered(company, "Owner", first_name="Dilnoza", last_name="Karimova")


def placed(member_maker, company, branch, role="Employee", **kwargs):
    person = member_maker.registered(company, role, home_branch=branch, **kwargs)
    person.branches.set([branch])
    return person


def test_the_directory_lists_current_people_with_their_numbers(
    owner_api, owner, company, member, branches
):
    chilonzor, _yunusobod = branches
    cashier = PositionFactory(company=company, name="Cashier")
    ali = placed(
        member, company, chilonzor, first_name="Ali", last_name="Valiyev", position=cashier
    )
    now = timezone.now()
    Task.objects.create(
        company=company,
        kind=Task.Kind.DAILY,
        title="Count the float",
        assignee=ali,
        due_at=now - timedelta(days=1),
        status=Task.Status.DONE,
        completed_at=now - timedelta(days=1, minutes=5),
    )
    Task.objects.create(
        company=company,
        kind=Task.Kind.DAILY,
        title="Count the float",
        assignee=ali,
        due_at=now - timedelta(days=2),
        status=Task.Status.DONE,
        completed_at=now - timedelta(days=2) + timedelta(minutes=30),
    )
    member(company, status=Membership.Status.LEFT, first_name="Gone")

    response = owner_api(owner).get(url(company))

    assert response.status_code == 200
    names = [row["name"] for row in response.data["results"]]
    assert "Ali Valiyev" in names and "Gone" not in names
    row = next(row for row in response.data["results"] if row["name"] == "Ali Valiyev")
    assert row["position"] == {"id": cashier.pk, "name": "Cashier"}
    assert row["home_branch"]["name"] == "Chilonzor"
    assert row["work"]["on_time_30d"] == "50"
    assert row["work"]["done_30d"] == 2
    assert row["status"] == "approved"


def test_filters_by_status_position_branch_and_search(owner_api, owner, company, member, branches):
    chilonzor, yunusobod = branches
    cook = PositionFactory(company=company, name="Courier")
    placed(member, company, chilonzor, first_name="Ali", position=cook)
    placed(member, company, yunusobod, first_name="Vali")
    member(company, status=Membership.Status.LEFT, first_name="Former")
    api = owner_api(owner)

    def names(**params):
        response = api.get(url(company), params)
        assert response.status_code == 200
        return {row["first_name"] for row in response.data["results"]}

    assert names(position=cook.pk) == {"Ali"}
    assert names(branch=yunusobod.pk) == {"Vali"}
    assert names(q="val") == {"Vali"}
    assert names(status="left") == {"Former"}


def test_a_branch_manager_sees_only_their_branches(owner_api, company, member, branches):
    chilonzor, yunusobod = branches
    role = AccessRoleFactory(
        company=company, permissions=[Perm.DASHBOARD_ACCESS, Perm.MEMBERS_VIEW]
    )
    boss = member.registered(company, role.name, first_name="Boss", home_branch=chilonzor)
    boss.branches.set([chilonzor])
    placed(member, company, chilonzor, first_name="Near")
    far = placed(member, company, yunusobod, first_name="Far")
    api = owner_api(boss)

    response = api.get(url(company))
    assert {row["first_name"] for row in response.data["results"]} == {"Boss", "Near"}
    # Someone outside the scope doesn't exist, like another company's person.
    assert api.get(url(company, f"{far.pk}/")).status_code == 404
    # Asking for another branch's people gives nobody.
    response = api.get(url(company), {"branch": yunusobod.pk})
    assert response.data["results"] == []


def test_permissions_and_tenancy(owner_api, company, other_company, member, branches):
    plain = member.registered(company, "Accountant")  # members.view, not members.manage
    AccessRole.objects.filter(pk=plain.role_id).update(
        permissions=[Perm.DASHBOARD_ACCESS, Perm.REPORTS_VIEW]
    )
    plain.role.refresh_from_db()
    stranger = member.registered(other_company, "Owner")
    person = member.registered(company)

    assert owner_api(plain).get(url(company)).status_code == 403
    assert owner_api(stranger).get(url(company)).status_code == 404
    assert owner_api(stranger).get(url(other_company, f"{person.pk}/")).status_code == 404


def test_salary_shows_only_with_payroll_view(
    owner_api, company, member, branches, isolated_registries
):
    def salary(company, member_ids, now):
        return {
            member_id: {
                "salary": {"amount": "5200000.00", "currency": "UZS", "pay_type": "monthly"}
            }
            for member_id in member_ids
        }

    registry.PERSON_FIELDS.add(
        registry.PersonFieldsProvider("payroll", "payroll", Perm.PAYROLL_VIEW, None, salary)
    )
    owner = member.registered(company, "Owner")
    manager = member.registered(company, "Manager")  # no payroll.view
    worker = placed(member, company, branches[0])

    seen_by_owner = owner_api(owner).get(url(company, f"{worker.pk}/")).data
    seen_by_manager = owner_api(manager).get(url(company, f"{worker.pk}/")).data

    assert seen_by_owner["fields"]["salary"]["amount"] == "5200000.00"
    assert "salary" not in seen_by_manager["fields"]


def test_person_360_has_numbers_actions_and_upcoming_time_off(
    owner_api, owner, company, member, branches
):
    from apps.timeoff.models import TimeOff

    worker = placed(member, company, branches[0], first_name="Ali")
    today = timezone.localdate()
    TimeOff.objects.create(
        company=company,
        membership=worker,
        first_day=today + timedelta(days=3),
        last_day=today + timedelta(days=4),
        status=TimeOff.Status.APPROVED,
    )

    data = owner_api(owner).get(url(company, f"{worker.pk}/")).data

    assert (
        data["overview"]["upcoming_time_off"][0]["first_day"]
        == (today + timedelta(days=3)).isoformat()
    )
    assert len(data["overview"]["trend"]) == 12
    assert data["can"]["edit"] and data["can"]["offboard"] and data["can"]["change_role"]
    assert not data["can"]["unblock"]


def test_editing_position_branches_and_home_branch(owner_api, owner, company, member, branches):
    chilonzor, yunusobod = branches
    cook = PositionFactory(company=company, name="Courier")
    worker = placed(member, company, chilonzor)

    response = owner_api(owner).patch(
        url(company, f"{worker.pk}/"),
        {
            "position_id": cook.pk,
            "branch_ids": [chilonzor.pk, yunusobod.pk],
            "home_branch_id": yunusobod.pk,
        },
        format="json",
    )

    assert response.status_code == 200, response.data
    worker.refresh_from_db()
    assert worker.position == cook
    assert set(worker.branches.values_list("pk", flat=True)) == {chilonzor.pk, yunusobod.pk}
    assert worker.home_branch == yunusobod
    row = AuditLog.objects.filter(target_type="membership", target_id=worker.pk).latest("pk")
    assert row.action == "members.changed"
    assert row.details["changes"]["position"] == [None, "Courier"]


def test_a_home_branch_outside_the_branches_is_refused(owner_api, owner, company, member, branches):
    chilonzor, yunusobod = branches
    worker = placed(member, company, chilonzor)

    response = owner_api(owner).patch(
        url(company, f"{worker.pk}/"),
        {"branch_ids": [chilonzor.pk], "home_branch_id": yunusobod.pk},
        format="json",
    )

    assert response.status_code == 400


def test_changing_a_role_needs_roles_manage(owner_api, company, member, branches):
    role = AccessRoleFactory(
        company=company,
        permissions=[
            Perm.DASHBOARD_ACCESS,
            Perm.MEMBERS_VIEW,
            Perm.MEMBERS_MANAGE,
            Perm.BRANCHES_ALL,
        ],
    )
    editor = member.registered(company, role.name)
    worker = placed(member, company, branches[0])
    cashier = AccessRole.objects.get(company=company, name="Cashier")

    response = owner_api(editor).patch(
        url(company, f"{worker.pk}/"), {"role_id": cashier.pk}, format="json"
    )

    assert response.status_code == 403


def test_block_and_unblock(owner_api, owner, company, member, branches):
    worker = placed(member, company, branches[0])
    api = owner_api(owner)

    blocked = api.post(url(company, f"{worker.pk}/block/"))
    assert blocked.status_code == 200
    assert blocked.data["status"] == "blocked"
    assert blocked.data["can"]["unblock"]

    unblocked = api.post(url(company, f"{worker.pk}/unblock/"))
    assert unblocked.status_code == 200
    assert unblocked.data["status"] == "left"


def test_the_last_owner_cant_be_blocked(owner_api, owner, company, member, branches):
    second = member.registered(company, "Owner")

    response = owner_api(second).post(url(company, f"{owner.pk}/block/"))
    assert response.status_code == 200  # two owners: fine

    alone = owner_api(second).post(url(company, f"{second.pk}/block/"))
    assert alone.status_code == 400  # yourself, and the only owner left


def test_suspend_and_reinstate(owner_api, owner, company, member, branches):
    worker = placed(member, company, branches[0])
    until = timezone.localdate() + timedelta(days=3)
    api = owner_api(owner)

    response = api.post(
        url(company, f"{worker.pk}/suspend/"),
        {"until": until.isoformat(), "reason": "Cash shortage under review"},
        format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data["status"] == "suspended"
    assert response.data["suspended_until"] == until.isoformat()

    response = api.post(url(company, f"{worker.pk}/reinstate/"))
    assert response.data["status"] == "approved"


def test_history_shows_audit_rows_about_the_person_and_their_time_off(
    owner_api, owner, company, member, branches
):
    from apps.timeoff import services as timeoff_services

    worker = placed(member, company, branches[0])
    timeoff_services.record_time_off(
        worker, by=owner, first_day=timezone.localdate(), last_day=timezone.localdate()
    )
    owner_api(owner).patch(url(company, f"{worker.pk}/"), {"first_name": "Alisher"}, format="json")

    response = owner_api(owner).get(url(company, f"{worker.pk}/history/"))

    assert response.status_code == 200
    actions = [row["action"] for row in response.data["results"]]
    assert "members.changed" in actions and "timeoff.recorded" in actions
    assert response.data["results"][0]["actor"]["name"] == "Dilnoza Karimova"
    # Someone who may see the team but not time off doesn't get its rows (reasons included).
    viewer_role = AccessRoleFactory(
        company=company,
        permissions=[Perm.DASHBOARD_ACCESS, Perm.MEMBERS_VIEW, Perm.BRANCHES_ALL],
    )
    viewer = member.registered(company, viewer_role.name)
    seen = owner_api(viewer).get(url(company, f"{worker.pk}/history/"))
    assert [row["action"] for row in seen.data["results"]] == ["members.changed"]


def test_pickers_can_load_the_whole_team(owner_api, owner, company, member, branches):
    for _ in range(3):
        placed(member, company, branches[0])

    response = owner_api(owner).get(url(company), {"page_size": 500, "status": "active"})

    assert response.status_code == 200
    assert response.data["count"] == 4
    assert {"id", "name", "full_name", "position", "home_branch", "photo_url"} <= set(
        response.data["results"][0]
    )


def test_registered_search_finds_people_in_scope(company, member, branches, owner):
    placed(member, company, branches[0], first_name="Madina", last_name="Saidova")

    hits = registry.run_search(owner, "madi", types=["members.person"])

    assert [hit.title for hit in hits] == ["Madina Saidova"]
    assert hits[0].url.startswith("people/")


def test_registrations_have_app_prefixed_keys():
    assert "members.join" in registry.QUEUE
    assert "members.pending" in registry.PULSE
    assert "members.people" in registry.BRIEF_SECTIONS
    assert "members" in registry.OFFBOARD_STEPS
    assert "members.positions" in registry.SETUP_STEPS
    assert {"members.positions", "members.roles"} <= set(registry.COPY_PARTS.keys())
    assert isinstance(registry.PERSON_FIELDS.get("timeoff").perm, AnyOf)


def test_stats_count_the_team_inside_the_callers_branches(
    owner_api, owner, company, member, branches
):
    from apps.timeoff.models import TimeOff

    chilonzor, yunusobod = branches
    away = placed(member, company, chilonzor, first_name="Away")
    placed(member, company, chilonzor, first_name="Here")
    paused = placed(member, company, yunusobod, first_name="Paused")
    Membership.objects.filter(pk=paused.pk).update(status=Membership.Status.SUSPENDED)
    today = timezone.localdate()
    TimeOff.objects.create(
        company=company,
        membership=away,
        first_day=today,
        last_day=today + timedelta(days=1),
        status=TimeOff.Status.APPROVED,
    )

    data = owner_api(owner).get(url(company, "stats/")).data
    assert data["suspended"] == 1
    assert data["on_leave_today"] == 1
    assert data["current"] == data["active"] + 1

    role = AccessRoleFactory(
        company=company, permissions=[Perm.DASHBOARD_ACCESS, Perm.MEMBERS_VIEW]
    )
    boss = member.registered(company, role.name, first_name="Boss", home_branch=chilonzor)
    boss.branches.set([chilonzor])
    scoped = owner_api(boss).get(url(company, "stats/")).data
    # Yunusobod's suspended person is outside the scope; join requests need members.approve.
    assert scoped["suspended"] == 0
    assert scoped["on_leave_today"] == 1
    assert scoped["pending_requests"] == 0
