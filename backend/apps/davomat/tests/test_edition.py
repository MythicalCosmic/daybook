"""The edition switch and the first run (docs/DAVOMAT.md §1.1): `GET edition/`,
`POST edition/setup/` and `manage.py davomat_init`; Telegram sign-in is gone in Davomat."""

from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.accounts.models import User
from apps.attendance import conf as attendance_conf
from apps.audit.models import AuditLog
from apps.companies.models import BranchKind, Company
from apps.davomat import queries
from apps.davomat.audit_actions import DavomatAction
from apps.davomat.models import DavomatSettings
from apps.davomat.tests.conftest import API, DASHBOARD, OWNER_PASSWORD
from apps.faceid.models import FaceIdSettings
from apps.members.models import AccessRole, Membership
from apps.members.permissions import Perm
from apps.signin.models import DeviceSession

pytestmark = pytest.mark.django_db

EDITION = f"{API}/edition/"
SETUP = f"{API}/edition/setup/"


def setup_body(**changes) -> dict:
    body = {
        "organization": "Namuna MChJ",
        "timezone": "Asia/Tashkent",
        "language": "uz",
        "admin": {
            "username": "aziza",
            "password": OWNER_PASSWORD,
            "first_name": "Aziza",
            "last_name": "Karimova",
        },
    }
    body.update(changes)
    return body


def post_setup(client, body=None, **headers):
    return client.post(
        SETUP, body or setup_body(), content_type="application/json", **(DASHBOARD | headers)
    )


# GET edition/ -----------------------------------------------------------------------------------


def test_daybook_says_so_and_needs_no_setup(client):
    data = client.get(EDITION).json()

    assert data["edition"] == "daybook"
    assert data["product"] == "Daybook"
    assert data["organization"] is None
    assert data["needs_setup"] is False
    assert data["languages"] == ["uz", "ru", "en"]
    assert data["telegram"] == {"configured": False, "bot_username": None}


def test_davomat_before_setup_asks_for_it(client, davomat):
    data = client.get(EDITION).json()

    assert data == {
        "edition": "davomat",
        "product": "Davomat",
        "organization": None,
        "needs_setup": True,
        "setup_token_required": False,
        "default_language": "uz",
        "languages": ["uz", "ru", "en"],
        "telegram": {"configured": False, "bot_username": None},
    }


def test_davomat_after_setup_names_the_organization(client, org):
    DavomatSettings.objects.filter(company=org.company).update(
        product_name="Namuna Davomat", bot_token="1:AA", bot_username="namuna_bot"
    )

    data = client.get(EDITION).json()

    assert data["needs_setup"] is False
    assert data["product"] == "Namuna Davomat"
    assert data["organization"] == {"name": "Namuna MChJ", "logo_url": None}
    assert data["default_language"] == "en"
    assert data["telegram"] == {"configured": True, "bot_username": "namuna_bot"}


# POST edition/setup/ ----------------------------------------------------------------------------


def test_setup_makes_the_organization_and_signs_its_owner_in(client, davomat):
    response = post_setup(client)

    assert response.status_code == 201, response.content
    assert response.json()["access"]
    assert response.cookies["owner_refresh"]["httponly"]
    company = Company.objects.get()
    assert company.name == "Namuna MChJ"
    assert company.timezone == "Asia/Tashkent" and company.default_language == "uz"
    assert sorted(company.features) == ["attendance", "face_id"]
    branch = company.branches.get()
    assert branch.kind == BranchKind.OFFICE
    owner = Membership.objects.select_related("user", "role").get(company=company)
    assert owner.role.is_owner and owner.status == Membership.Status.APPROVED
    assert (owner.first_name, owner.last_name) == ("Aziza", "Karimova")
    assert owner.user.check_password(OWNER_PASSWORD)
    assert list(owner.branches.all()) == [branch]
    assert attendance_conf.get_settings(company).require_location is False
    assert FaceIdSettings.objects.filter(company=company).exists()
    assert DavomatSettings.objects.get(company=company).auto_create_employees is True
    assert DeviceSession.objects.filter(user=owner.user).count() == 1
    assert AuditLog.objects.filter(company=company, action=DavomatAction.SETUP_DONE).exists()


def test_setup_gives_the_four_roles_and_the_employee_one(client, davomat):
    post_setup(client)
    company = Company.objects.get()

    kinds = {queries.role_kind(role): role for role in AccessRole.objects.filter(company=company)}

    assert set(kinds) == {"owner", "admin", "manager", "viewer", "employee"}
    assert AccessRole.objects.filter(company=company).count() == 5
    assert set(kinds["admin"].permissions) == set(Perm.values)
    assert set(kinds["manager"].permissions) == {
        "attendance.view",
        "attendance.manage",
        "members.view",
        "members.manage",
        "members.approve",
        "reports.view",
        "dashboard.access",
    }
    assert set(kinds["viewer"].permissions) == {
        "attendance.view",
        "members.view",
        "reports.view",
        "dashboard.access",
    }
    assert kinds["employee"].permissions == [] and kinds["employee"].is_default
    assert Perm.BRANCHES_ALL not in kinds["manager"].permissions  # managers see their branches


def test_setup_happens_once(client, davomat):
    assert post_setup(client).status_code == 201

    again = post_setup(client, setup_body(organization="Boshqa"))

    assert again.status_code == 409
    assert again.json()["code"] == "setup_done"
    assert Company.objects.count() == 1


def test_setup_checks_the_owners_username_and_password(client, davomat):
    weak = setup_body(admin={"username": "aziza", "password": "12345678"})
    bad_name = setup_body(admin={"username": "a b", "password": OWNER_PASSWORD})

    first = post_setup(client, weak)
    second = post_setup(client, bad_name)

    assert first.status_code == 400 and "password" in first.json()["admin"]
    assert second.status_code == 400 and "username" in second.json()["admin"]
    assert not Company.objects.exists() and not User.objects.filter(username="aziza").exists()


def test_setup_refuses_an_unknown_timezone(client, davomat):
    response = post_setup(client, setup_body(timezone="Mars/Olympus"))

    assert response.status_code == 400
    assert not Company.objects.exists()


def test_setup_only_from_the_dashboard(client, davomat):
    response = client.post(SETUP, setup_body(), content_type="application/json")

    assert response.status_code == 403
    assert not Company.objects.exists()


def test_a_setup_code_keeps_strangers_out(client, davomat):
    davomat.DAVOMAT_SETUP_TOKEN = "installer-printed-this-code"

    assert client.get(EDITION).json()["setup_token_required"] is True
    missing = post_setup(client)
    wrong = post_setup(client, setup_body(setup_token="guess"))
    right = post_setup(client, setup_body(setup_token="installer-printed-this-code"))

    assert missing.status_code == wrong.status_code == 403
    assert wrong.json()["code"] == "setup_token"
    assert right.status_code == 201


def test_daybook_has_no_setup(client):
    assert post_setup(client).status_code == 404


# manage.py davomat_init ---------------------------------------------------------------------


def test_davomat_init_sets_up_like_the_page(db):
    out = StringIO()

    call_command(
        "davomat_init",
        "--organization",
        "Namuna MChJ",
        "--admin-username",
        "admin",
        "--admin-password",
        OWNER_PASSWORD,
        "--language",
        "ru",
        stdout=out,
    )

    company = Company.objects.get()
    assert company.default_language == "ru"
    owner = Membership.objects.get(company=company)
    assert owner.user.username == "admin" and owner.role.is_owner
    assert owner.first_name == "admin"  # no first name given: the username stands in
    assert "admin can sign in" in out.getvalue()


def test_davomat_init_takes_the_password_from_the_environment(db, monkeypatch):
    monkeypatch.setenv("DAVOMAT_ADMIN_PASSWORD", OWNER_PASSWORD)

    call_command(
        "davomat_init", "--organization", "Namuna", "--admin-username", "admin", stdout=StringIO()
    )

    assert User.objects.get(username="admin").check_password(OWNER_PASSWORD)


def test_davomat_init_refuses_when_an_organization_exists(org):
    with pytest.raises(CommandError, match="already set up"):
        call_command(
            "davomat_init",
            "--organization",
            "Ikkinchi",
            "--admin-username",
            "boss",
            "--admin-password",
            OWNER_PASSWORD,
        )

    assert Company.objects.count() == 1


def test_davomat_init_says_what_is_wrong_with_the_password(db):
    with pytest.raises(CommandError, match=r"admin\.password"):
        call_command(
            "davomat_init",
            "--organization",
            "Namuna",
            "--admin-username",
            "admin",
            "--admin-password",
            "short",
        )


# Telegram sign-in is gone --------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["auth/telegram/", "auth/login-links/", "auth/login-links/x/", "auth/login-links/x/claim/"],
)
def test_telegram_sign_in_answers_404_in_davomat(client, davomat, path):
    assert client.post(f"{API}/{path}", {}, **DASHBOARD).status_code == 404
    assert client.get(f"{API}/{path}").status_code in (404, 405)


def test_telegram_sign_in_stays_in_daybook(client, settings):
    settings.EMPLOYEE_BOT_TOKEN, settings.EMPLOYEE_BOT_USERNAME = "42:TEST", "daybook_test_bot"

    assert client.post(f"{API}/auth/login-links/", **DASHBOARD).status_code == 201
    assert client.post(f"{API}/auth/telegram/", {"init_data": "x"}).status_code == 401
