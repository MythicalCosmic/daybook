"""O groups/: connected groups, event toggles, positions and branches filters, disconnect."""

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.companies.tests.factories import BranchFactory
from apps.groups import demo, services
from apps.groups.models import GroupEvent, TelegramGroup
from apps.members.tests.factories import PositionFactory

pytestmark = pytest.mark.django_db


def url(company, path=""):
    return f"/api/v1/owner/companies/{company.pk}/groups/{path}"


@pytest.fixture
def owner(company, member):
    return member(company, "Owner")


@pytest.fixture
def group(company, owner):
    return TelegramGroup.objects.create(
        company=company,
        chat_id=-1001000000001,
        title="Chilonzor jamoasi",
        events=[GroupEvent.DAILY_DONE, GroupEvent.LATE],
        linked_by=owner,
    )


def test_lists_groups_with_their_events_and_how_to_add_one(
    company, owner, owner_api, group, settings
):
    settings.EMPLOYEE_BOT_USERNAME = "daybook_test_bot"

    response = owner_api(owner).get(url(company))

    assert response.status_code == 200
    data = response.json()
    assert data["connect_link"] == "https://t.me/daybook_test_bot?startgroup=connect"
    [row] = data["results"]
    assert row["title"] == "Chilonzor jamoasi" and row["is_active"] is True
    assert row["linked_by"] == {"id": owner.pk, "name": str(owner)}
    events = {event["key"]: event for event in row["events"]}
    assert events["daily_done"]["on"] is True and events["evening"]["on"] is False
    # Module events appear once their module is on.
    assert "sales" not in events and "attendance" not in events


def test_module_events_appear_when_the_module_is_on(company, owner, owner_api, group):
    company.features = ["sales"]
    company.save()

    events = {
        e["key"]: e for e in owner_api(owner).get(url(company)).json()["results"][0]["events"]
    }

    assert events["sales"]["feature"] == "sales" and events["sales"]["available"] is True
    assert "attendance" not in events


def test_changing_events_and_filters_is_audited(company, owner, owner_api, group):
    cashier = PositionFactory(company=company, name="Cashier")
    branch = company.branches.get()

    response = owner_api(owner).patch(
        url(company, f"{group.pk}/"),
        {"events": ["late", "evening"], "position_ids": [cashier.pk], "branch_ids": [branch.pk]},
        format="json",
    )

    assert response.status_code == 200, response.content
    group.refresh_from_db()
    assert group.events == ["late", "evening"]
    assert list(group.positions.all()) == [cashier]
    assert list(group.branches.all()) == [branch]
    data = response.json()
    assert data["positions"] == [{"id": cashier.pk, "name": "Cashier"}]
    log = AuditLog.objects.get(action=AuditLog.Action.GROUP_CHANGED)
    assert log.actor == owner.user
    assert log.details["changes"]["events"] == [["daily_done", "late"], ["late", "evening"]]
    assert log.details["changes"]["branches"] == [[], [branch.pk]]


def test_only_given_fields_change(company, owner, group):
    services.update_settings(group, by=owner, branch_ids=[company.branches.get().pk])

    group.refresh_from_db()
    assert group.events == ["daily_done", "late"]


def test_a_switched_off_modules_event_can_be_kept_but_not_added(company, owner, group):
    group.events = [*group.events, GroupEvent.SALES]
    group.save()

    services.update_settings(group, by=owner, events=["late", "sales"])  # kept: fine
    group.refresh_from_db()
    assert group.events == ["late", "sales"]
    with pytest.raises(services.DomainError):
        services.update_settings(group, by=owner, events=["late", "attendance"])


@pytest.mark.parametrize("field", ["position_ids", "branch_ids"])
def test_filters_must_belong_to_the_company(company, other_company, owner, owner_api, group, field):
    theirs = (
        PositionFactory(company=other_company)
        if field == "position_ids"
        else BranchFactory(company=other_company)
    )

    response = owner_api(owner).patch(
        url(company, f"{group.pk}/"), {field: [theirs.pk]}, format="json"
    )

    assert response.status_code == 400


def test_unknown_events_are_refused(company, owner, owner_api, group):
    assert (
        owner_api(owner)
        .patch(url(company, f"{group.pk}/"), {"events": ["party"]}, format="json")
        .status_code
        == 400
    )


def test_disconnect(company, owner, owner_api, group):
    response = owner_api(owner).post(url(company, f"{group.pk}/disconnect/"))

    assert response.status_code == 200 and response.json()["is_active"] is False
    assert AuditLog.objects.filter(action=AuditLog.Action.GROUP_DISCONNECTED).exists()
    # A disconnected group can't be changed until the bot is added again.
    assert (
        owner_api(owner)
        .patch(url(company, f"{group.pk}/"), {"events": ["late"]}, format="json")
        .status_code
        == 400
    )


def test_groups_need_groups_manage(company, member, owner_api, group):
    accountant = member(company, "Accountant")
    manager = member(company, "Manager")

    assert owner_api(accountant).get(url(company)).status_code == 403
    assert (
        owner_api(accountant)
        .patch(url(company, f"{group.pk}/"), {"events": []}, format="json")
        .status_code
        == 403
    )
    assert owner_api(accountant).post(url(company, f"{group.pk}/disconnect/")).status_code == 403
    assert owner_api(manager).get(url(company)).status_code == 200


def test_another_companys_group_is_not_found(company, other_company, owner, owner_api, member):
    theirs = TelegramGroup.objects.create(company=other_company, chat_id=-1009, title="Theirs")

    assert (
        owner_api(owner)
        .patch(url(company, f"{theirs.pk}/"), {"events": []}, format="json")
        .status_code
        == 404
    )
    assert owner_api(owner).post(url(company, f"{theirs.pk}/disconnect/")).status_code == 404
    assert owner_api(owner).get(url(other_company)).status_code == 404


def test_the_service_checks_the_actor(company, other_company, member, group):
    worker = member(company, "Employee")
    outsider = member(other_company, "Owner")

    with pytest.raises(services.PermissionDenied):
        services.update_settings(group, by=worker, events=[])
    with pytest.raises(services.PermissionDenied):
        services.update_settings(group, by=outsider, events=[])


def test_demo_groups(company, demo_people):
    company.features = ["sales", "attendance", "hr", "recognition"]
    company.save()
    PositionFactory(company=company, name="Cashier")
    people = demo_people(company)

    demo.seed(company, people, timezone.now())
    demo.seed(company, people, timezone.now())  # idempotent

    groups = TelegramGroup.objects.filter(company=company)
    assert groups.count() == 4
    kassa = groups.get(title="Kassa · Chilonzor")
    assert kassa.events == ["shifts", "cash", "sales"] or set(kassa.events) == {
        "shifts",
        "cash",
        "sales",
    }
    assert [p.name for p in kassa.positions.all()] == ["Cashier"]


def test_managers_hear_when_the_bot_is_removed(company, owner, member, group):
    from apps.inbox.models import Notification

    manager = member(company, "Manager")
    worker = member(company, "Employee")

    services.bot_removed(group.chat_id, by=worker.user)

    notes = Notification.objects.filter(kind="groups.removed")
    assert {n.recipient_id for n in notes} == {owner.pk, manager.pk}
    note = notes.get(recipient=owner)
    assert "Chilonzor jamoasi" in note.title
    assert str(worker) in note.body
    assert note.url == f"/c/{company.pk}/groups"
    assert note.severity == "warning"


def test_the_list_offers_the_companys_positions_and_branches(company, owner, owner_api, group):
    cashier = PositionFactory(company=company, name="Cashier")
    PositionFactory(company=company, name="Old job", is_active=False)
    branch = company.branches.get()

    options = owner_api(owner).get(url(company)).json()["options"]

    assert options["positions"] == [{"id": cashier.pk, "name": "Cashier"}]
    assert options["branches"] == [{"id": branch.pk, "name": branch.name}]
