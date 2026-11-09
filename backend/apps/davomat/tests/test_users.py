"""Users of the web app (docs/DAVOMAT.md §1.3): `companies/{c}/users/`."""

import pytest

from apps.audit.models import AuditLog
from apps.davomat import services
from apps.davomat.audit_actions import DavomatAction
from apps.davomat.models import Employee
from apps.davomat.tests.conftest import PASSWORD
from apps.members.models import Membership
from apps.signin import services as signin
from apps.signin.models import DeviceSession

pytestmark = pytest.mark.django_db

NEW_PASSWORD = "Fergana-Valley-2031"


def new_user(**changes) -> dict:
    body = {
        "username": "bekzod",
        "password": PASSWORD,
        "first_name": "Bekzod",
        "last_name": "Mirzayev",
        "role": "manager",
    }
    body.update(changes)
    return body


def test_the_owner_lists_the_users(org, owner_api):
    manager = org.user("manager", "bekzod", branches=[org.second])

    response = owner_api(org.owner).get(org.url("users/"))

    assert response.status_code == 200, response.content
    rows = {row["username"]: row for row in response.json()["results"]}
    assert set(rows) == {"owner", "bekzod"}
    assert rows["owner"]["role"]["kind"] == "owner" and rows["owner"]["is_self"]
    assert rows["bekzod"] == {
        "id": manager.pk,
        "username": "bekzod",
        "first_name": "Test",
        "last_name": "Manager",
        "role": {"id": manager.role_id, "name": "Manager", "kind": "manager"},
        "branch_ids": [org.second.pk],
        "is_active": True,
        "last_login": None,
        "telegram_linked": False,
        "is_employee": False,
        "is_self": False,
    }


def test_employees_are_not_users(org, owner_api):
    org.employee("Jasur")

    rows = owner_api(org.owner).get(org.url("users/")).json()["results"]

    assert [row["username"] for row in rows] == ["owner"]


def test_add_a_manager_who_signs_in(org, owner_api, client):
    response = owner_api(org.owner).post(
        org.url("users/"), new_user(branch_ids=[org.second.pk]), format="json"
    )

    assert response.status_code == 201, response.content
    data = response.json()
    assert data["role"]["kind"] == "manager" and data["branch_ids"] == [org.second.pk]
    person = Membership.objects.get(pk=data["id"])
    assert person.status == Membership.Status.APPROVED and person.home_branch == org.second
    assert person.user.check_password(PASSWORD)
    assert AuditLog.objects.filter(action=DavomatAction.USER_CREATED).exists()
    assert signin.can_sign_in(person.user)


def test_a_role_by_id_works_too(org, owner_api):
    viewer = org.role("viewer")

    response = owner_api(org.owner).post(
        org.url("users/"),
        new_user(role=None, role_id=viewer.pk, branch_ids=[org.main.pk]) | {"role": "viewer"},
        format="json",
    )

    assert response.status_code == 201 and response.json()["role"]["id"] == viewer.pk


def test_managers_and_viewers_need_branches(org, owner_api):
    response = owner_api(org.owner).post(org.url("users/"), new_user(), format="json")

    assert response.status_code == 400 and "branch_ids" in response.json()


def test_administrators_see_every_branch_without_any(org, owner_api):
    response = owner_api(org.owner).post(org.url("users/"), new_user(role="admin"), format="json")

    assert response.status_code == 201
    assert response.json()["branch_ids"] == [org.main.pk]  # the first branch as their home


def test_the_username_and_password_follow_the_rules(org, owner_api):
    api = owner_api(org.owner)
    org.user("viewer", "Madina")

    taken = api.post(org.url("users/"), new_user(username="madina", role="admin"), format="json")
    weak = api.post(org.url("users/"), new_user(password="12345678", role="admin"), format="json")
    spaced = api.post(org.url("users/"), new_user(username="b k", role="admin"), format="json")

    assert taken.status_code == 400 and "username" in taken.json()
    assert weak.status_code == 400 and "password" in weak.json()
    assert spaced.status_code == 400 and "username" in spaced.json()


def test_an_employee_gets_a_sign_in(org, owner_api):
    worker = org.employee("Jasur", "Tursunov")

    response = owner_api(org.owner).post(
        org.url("users/"),
        {"username": "jasur", "password": PASSWORD, "role": "viewer", "employee_id": worker.pk},
        format="json",
    )

    assert response.status_code == 201, response.content
    data = response.json()
    assert data["id"] == worker.pk and data["is_employee"] and data["first_name"] == "Jasur"
    worker.refresh_from_db()
    assert worker.user.username == "jasur" and worker.user.check_password(PASSWORD)
    assert Employee.objects.filter(membership=worker).exists()


def test_change_a_user(org, owner_api):
    manager = org.user("manager", "bekzod")

    response = owner_api(org.owner).patch(
        org.url(f"users/{manager.pk}/"),
        {
            "username": "bekzod.m",
            "first_name": "Bek",
            "role": "viewer",
            "branch_ids": [org.main.pk, org.second.pk],
        },
        format="json",
    )

    assert response.status_code == 200, response.content
    data = response.json()
    assert data["username"] == "bekzod.m" and data["first_name"] == "Bek"
    assert data["role"]["kind"] == "viewer"
    assert data["branch_ids"] == sorted([org.main.pk, org.second.pk])
    manager.refresh_from_db()
    assert manager.user.first_name == "Bek"


def test_a_user_who_scans_too(org, owner_api):
    manager = org.user("manager", "bekzod")
    api = owner_api(org.owner)

    on = api.patch(org.url(f"users/{manager.pk}/"), {"is_employee": True}, format="json")
    off = api.patch(org.url(f"users/{manager.pk}/"), {"is_employee": False}, format="json")

    assert on.json()["is_employee"] is True and off.json()["is_employee"] is False


def test_switch_a_user_off_and_back_on(org, owner_api):
    manager = org.user("manager", "bekzod")
    session = signin.issue_session(manager.user, _request())
    api = owner_api(org.owner)

    off = api.post(org.url(f"users/{manager.pk}/deactivate/"))

    assert off.status_code == 200 and off.json()["is_active"] is False
    session.session.refresh_from_db()
    assert session.session.revoked_at is not None
    assert not signin.can_sign_in(Membership.objects.get(pk=manager.pk).user)
    on = api.post(org.url(f"users/{manager.pk}/activate/"))
    assert on.json()["is_active"] is True
    assert api.delete(org.url(f"users/{manager.pk}/")).status_code == 204
    manager.refresh_from_db()
    assert manager.user.is_active is False
    assert AuditLog.objects.filter(action=DavomatAction.USER_DEACTIVATED).count() == 2


def test_nobody_switches_themselves_off(org, owner_api):
    response = owner_api(org.owner).post(org.url(f"users/{org.owner.pk}/deactivate/"))

    assert response.status_code == 400


def test_an_administrator_cant_touch_the_owner(org, owner_api):
    admin = org.user("admin", "aziz")
    api = owner_api(admin)

    assert api.post(org.url(f"users/{org.owner.pk}/deactivate/")).status_code == 403
    assert api.patch(org.url(f"users/{org.owner.pk}/"), {"role": "viewer"}).status_code == 403
    assert (
        api.post(org.url(f"users/{org.owner.pk}/password/"), {"password": NEW_PASSWORD}).status_code
        == 403
    )
    created = api.post(org.url("users/"), new_user(role="owner"), format="json")
    assert created.status_code == 403


def test_the_last_owner_stays(org, owner_api):
    second = org.user("owner", "boss2")
    api = owner_api(second)

    assert api.post(org.url(f"users/{org.owner.pk}/deactivate/")).status_code == 200
    again = owner_api(org.owner)  # switched off: their token no longer works
    assert again.get(org.url("users/")).status_code == 401
    response = owner_api(second).patch(
        org.url(f"users/{second.pk}/"), {"role": "admin"}, format="json"
    )
    assert response.status_code == 400  # the only owner left can't stop being one


def test_set_someones_password(org, owner_api, client):
    manager = org.user("manager", "bekzod")
    session = signin.issue_session(manager.user, _request())

    response = owner_api(org.owner).post(
        org.url(f"users/{manager.pk}/password/"), {"password": NEW_PASSWORD}
    )

    assert response.status_code == 204
    manager.user.refresh_from_db()
    assert manager.user.check_password(NEW_PASSWORD)
    session.session.refresh_from_db()
    assert session.session.revoked_at is not None
    assert AuditLog.objects.filter(action=DavomatAction.PASSWORD_SET).exists()
    assert "Fergana" not in str(AuditLog.objects.values_list("details", flat=True))


def test_the_roles_offered(org, owner_api):
    rows = owner_api(org.owner).get(org.url("users/roles/")).json()

    assert [row["kind"] for row in rows] == ["owner", "admin", "manager", "viewer"]


# Rights and scope ---------------------------------------------------------------------------


def test_managers_and_viewers_may_not_manage_users(org, owner_api):
    for person in (org.user("manager", "bekzod"), org.user("viewer", "madina")):
        api = owner_api(person)
        assert api.get(org.url("users/")).status_code == 403
        created = api.post(org.url("users/"), new_user(username="x1"), format="json")
        assert created.status_code == 403


def test_another_companys_users_are_missing(org, owner_api, other_company, member):
    stranger = member(other_company, "Owner")
    api = owner_api(org.owner)

    assert api.get(org.url(f"users/{stranger.pk}/")).status_code == 404
    assert api.patch(org.url(f"users/{stranger.pk}/"), {"first_name": "X"}).status_code == 404
    assert api.post(org.url(f"users/{stranger.pk}/deactivate/")).status_code == 404
    theirs = f"/api/v1/owner/companies/{other_company.pk}/users/"
    assert api.get(theirs).status_code == 404


def test_daybook_has_no_users_page(org, owner_api, settings):
    settings.EDITION = "daybook"

    assert owner_api(org.owner).get(org.url("users/")).status_code == 404


def test_link_your_own_telegram_without_managing_users(org, owner_api):
    from apps.davomat.models import DavomatSettings

    DavomatSettings.objects.filter(company=org.company).update(
        bot_token="1:AA", bot_username="namuna_bot"
    )
    viewer = org.user("viewer", "madina")
    api = owner_api(viewer)

    mine = api.post(org.url(f"users/{viewer.pk}/telegram-link/"))
    theirs = api.post(org.url(f"users/{org.owner.pk}/telegram-link/"))

    assert mine.status_code == 201, mine.content
    assert mine.json()["url"].startswith("https://t.me/namuna_bot?start=link_")
    assert theirs.status_code == 403


def test_deactivating_keeps_an_employee_scanning(org, owner_api):
    worker = org.employee("Jasur")
    services.create_user(
        org.company, by=org.owner, username="jasur", password=PASSWORD,
        role=org.role("viewer"), branches=[org.main], employee=worker,
    )  # fmt: skip

    owner_api(org.owner).post(org.url(f"users/{worker.pk}/deactivate/"))

    worker.refresh_from_db()
    assert worker.status == Membership.Status.APPROVED  # still an employee who scans
    assert DeviceSession.objects.filter(user=worker.user, revoked_at__isnull=True).count() == 0


def _request():
    from django.test import RequestFactory

    return RequestFactory().post("/", REMOTE_ADDR="213.230.1.2")
