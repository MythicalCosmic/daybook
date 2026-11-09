"""Password sign-in (docs/DAVOMAT.md §1.2): `POST auth/password/`, the lockout, and
`POST auth/password/change/`, in both editions."""

import pytest

from apps.audit.models import AuditLog
from apps.davomat import passwords, services
from apps.davomat.audit_actions import DavomatAction
from apps.davomat.tests.conftest import API, DASHBOARD, OWNER_PASSWORD, PASSWORD
from apps.signin import services as signin
from apps.signin.models import DeviceSession
from apps.signin.tokens import OwnerAccessToken

pytestmark = pytest.mark.django_db

LOGIN = f"{API}/auth/password/"
CHANGE = f"{API}/auth/password/change/"
WRONG = {"detail": "Wrong username or password.", "code": "wrong_password"}


def login(client, username, password, *, address="213.230.1.2", **headers):
    return client.post(
        LOGIN,
        {"username": username, "password": password},
        content_type="application/json",
        REMOTE_ADDR=address,
        **(DASHBOARD | headers),
    )


def test_the_right_password_signs_in_with_a_session(client, org):
    response = login(client, "owner", OWNER_PASSWORD)

    assert response.status_code == 200, response.content
    token = OwnerAccessToken(response.json()["access"])
    assert str(token["user_id"]) == str(org.owner.user_id)
    cookie = response.cookies["owner_refresh"]
    assert cookie["httponly"] and cookie["path"] == "/api/v1/owner/auth/"
    assert DeviceSession.objects.filter(user=org.owner.user).count() == 1
    org.owner.user.refresh_from_db()
    assert org.owner.user.last_login is not None
    assert AuditLog.objects.filter(action=DavomatAction.PASSWORD_LOGIN).count() == 1


def test_the_session_refreshes_like_any_other(client, org):
    login(client, "owner", OWNER_PASSWORD)

    refreshed = client.post(f"{API}/auth/refresh/", **DASHBOARD)

    assert refreshed.status_code == 200 and refreshed.json()["access"]


def test_usernames_match_in_any_case(client, org):
    assert login(client, "OWNER", OWNER_PASSWORD).status_code == 200


def test_a_wrong_password_and_an_unknown_name_answer_the_same(client, org):
    wrong = login(client, "owner", "not-the-password")
    unknown = login(client, "nobody", OWNER_PASSWORD)

    assert wrong.status_code == unknown.status_code == 400
    assert wrong.json() == unknown.json() == WRONG


def test_five_wrong_passwords_lock_the_name_at_that_address(client, org):
    for _attempt in range(5):
        assert login(client, "owner", "guess").status_code == 400

    locked = login(client, "owner", OWNER_PASSWORD)  # even the right one, for 15 minutes

    assert locked.status_code == 429
    assert locked.json()["code"] == "locked"
    assert 0 < int(locked["Retry-After"]) <= 15 * 60
    assert "15 minutes" in locked.json()["detail"]
    assert login(client, "owner", OWNER_PASSWORD, address="84.54.1.1").status_code == 200
    assert AuditLog.objects.filter(action=DavomatAction.PASSWORD_LOCKED).count() == 1


def test_the_lock_ends(client, org, monkeypatch):
    for _attempt in range(5):
        login(client, "owner", "guess")
    later = passwords.time.time() + 15 * 60 + 1
    monkeypatch.setattr(passwords.time, "time", lambda: later)

    assert login(client, "owner", OWNER_PASSWORD).status_code == 200


def test_unknown_names_lock_too(client, org):
    for _attempt in range(5):
        login(client, "ghost", "guess")

    assert login(client, "ghost", "guess").status_code == 429


def test_a_right_password_clears_the_count(client, org):
    for _attempt in range(4):
        login(client, "owner", "guess")
    assert login(client, "owner", OWNER_PASSWORD).status_code == 200

    for _attempt in range(4):
        assert login(client, "owner", "guess").status_code == 400


def test_one_address_spraying_many_names_is_stopped(client, org, monkeypatch):
    monkeypatch.setattr(passwords, "ADDRESS_CEILING", 6)
    for index in range(6):
        login(client, f"name{index}", "guess")

    assert login(client, "owner", OWNER_PASSWORD).status_code == 429
    assert login(client, "owner", OWNER_PASSWORD, address="84.54.1.1").status_code == 200


def test_someone_switched_off_hears_so_once_the_password_is_right(client, org):
    manager = org.user("manager", "bekzod")
    services.set_active(manager, by=org.owner, active=False)

    assert login(client, "bekzod", "guess").json() == WRONG
    refused = login(client, "bekzod", PASSWORD)

    assert refused.status_code == 403 and refused.json()["code"] == "no_access"


def test_employees_never_sign_in(client, org):
    worker = org.employee("Jasur")

    assert login(client, worker.user.username, "").status_code == 400
    assert login(client, worker.user.username, "anything").json() == WRONG


def test_only_the_dashboard_may_sign_in(client, org):
    response = client.post(
        LOGIN, {"username": "owner", "password": OWNER_PASSWORD}, content_type="application/json"
    )

    assert response.status_code == 403


def test_password_sign_in_works_in_daybook_too(client, company, member):
    owner = member(company, "Owner")
    owner.user.set_password(PASSWORD)
    owner.user.save()

    assert login(client, owner.user.username, PASSWORD).status_code == 200


def test_a_daybook_account_from_telegram_has_no_password(client, company, member):
    owner = member(company, "Owner")  # made through Telegram: no usable password

    assert login(client, owner.user.username, "").status_code == 400


# Changing your own password --------------------------------------------------------------------


def test_change_your_password(org, owner_api):
    api = owner_api(org.owner)
    other = signin.issue_session(org.owner.user, _request())

    response = api.post(CHANGE, {"current": OWNER_PASSWORD, "new": "Bukhara-Winter-99"})

    assert response.status_code == 204, response.content
    org.owner.user.refresh_from_db()
    assert org.owner.user.check_password("Bukhara-Winter-99")
    other.session.refresh_from_db()
    assert other.session.revoked_at is not None  # every other browser signed out
    assert AuditLog.objects.filter(action=DavomatAction.PASSWORD_CHANGED).count() == 1


def test_changing_needs_the_current_password(org, owner_api):
    response = owner_api(org.owner).post(CHANGE, {"current": "wrong", "new": "Bukhara-Winter-99"})

    assert response.status_code == 400
    assert "current" in response.json()
    org.owner.user.refresh_from_db()
    assert org.owner.user.check_password(OWNER_PASSWORD)


def test_the_new_password_follows_the_rules(org, owner_api):
    api = owner_api(org.owner)

    short = api.post(CHANGE, {"current": OWNER_PASSWORD, "new": "short"})
    common = api.post(CHANGE, {"current": OWNER_PASSWORD, "new": "password123"})
    same = api.post(CHANGE, {"current": OWNER_PASSWORD, "new": OWNER_PASSWORD})

    assert short.status_code == common.status_code == same.status_code == 400
    assert "new" in short.json() and "new" in common.json() and "new" in same.json()


def test_a_daybook_account_sets_its_first_password(company, member, owner_api):
    owner = member(company, "Owner")

    response = owner_api(owner).post(CHANGE, {"new": "Bukhara-Winter-99"})

    assert response.status_code == 204
    owner.user.refresh_from_db()
    assert owner.user.check_password("Bukhara-Winter-99")


def test_changing_needs_a_sign_in(client, org):
    assert client.post(CHANGE, {"new": "Bukhara-Winter-99"}).status_code == 401


def _request():
    from django.test import RequestFactory

    return RequestFactory().post("/", REMOTE_ADDR="213.230.1.2")
