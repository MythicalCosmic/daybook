"""Signup codes and who may create a company (`COMPANY_SIGNUP`)."""

from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.core.exceptions import DomainError
from apps.signin import signup
from apps.signin.models import SignupCode

pytestmark = pytest.mark.django_db


def test_codes_are_easy_to_read_and_stored_as_hashes():
    code, raw = signup.create_code(uses=2, note="Malika, Chorsu pharmacy")

    assert len(raw) == 9 and raw[4] == "-"
    assert set(raw.replace("-", "")) <= set(signup.ALPHABET)
    assert code.code_hash == signup.code_hash(raw) and raw not in code.code_hash
    assert code.uses_left == 2


@pytest.mark.parametrize("typed", ["{raw}", "{lower}", "{plain}", " {spaced} "])
def test_codes_are_found_however_they_are_typed(typed):
    _code, raw = signup.create_code()
    variants = {
        "raw": raw,
        "lower": raw.lower(),
        "plain": raw.replace("-", ""),
        "spaced": raw.replace("-", " "),
    }

    assert signup.find(typed.format(**variants)) is not None


def test_a_code_is_used_up():
    _code, raw = signup.create_code(uses=1)

    signup.consume(raw)

    assert signup.find(raw) is None
    with pytest.raises(DomainError):
        signup.consume(raw)


def test_an_expired_code_is_refused():
    _code, raw = signup.create_code(expires_at=timezone.now() - timedelta(minutes=1))

    assert signup.find(raw) is None
    with pytest.raises(DomainError):
        signup.consume(raw)


def test_wrong_codes_are_refused():
    assert signup.find("") is None
    assert signup.find("ABCD-EFGH") is None
    with pytest.raises(DomainError):
        signup.create_code(uses=0)


def test_code_mode_needs_a_code_until_someone_owns_a_company(settings, company, member):
    settings.COMPANY_SIGNUP = "code"
    newcomer = UserFactory()
    owner = member(company, "Owner").user

    assert signup.policy(newcomer) == signup.Policy("code", True, True, "")
    assert signup.policy(owner).needs_code is False
    with pytest.raises(DomainError, match="signup code"):
        signup.admit(newcomer, None)
    _code, raw = signup.create_code()
    assert signup.admit(newcomer, raw) is not None
    assert signup.admit(owner, None) is None


def test_open_and_off_modes(settings):
    newcomer = UserFactory()
    settings.COMPANY_SIGNUP = "open"
    assert signup.admit(newcomer, None) is None

    settings.COMPANY_SIGNUP = "off"
    assert signup.policy(newcomer).allowed is False
    with pytest.raises(DomainError):
        signup.admit(newcomer, "anything")


def test_platform_admins_never_need_a_code(settings):
    settings.COMPANY_SIGNUP = "off"
    settings.PLATFORM_ADMIN_TG_IDS = [7000000001]

    assert signup.admit(UserFactory(telegram_id=7000000001), None) is None


def test_the_command_prints_the_code_and_the_bot_link(settings):
    settings.OWNER_BOT_USERNAME = "owner_test_bot"
    out = StringIO()

    call_command("signup_code", "--uses", "3", "--days", "7", "--note", "Chorsu", stdout=out)

    raw, link = out.getvalue().split()
    code = SignupCode.objects.get()
    assert code.code_hash == signup.code_hash(raw)
    assert (code.uses_left, code.note) == (3, "Chorsu")
    assert code.expires_at > timezone.now() + timedelta(days=6)
    assert link == f"https://t.me/owner_test_bot?start=new_{signup.normalize(raw)}"


def test_without_the_owner_bot_the_command_prints_no_link(settings):
    """Only the owner bot runs /new; an employee bot link would just greet the person."""
    settings.OWNER_BOT_USERNAME = ""
    settings.EMPLOYEE_BOT_USERNAME = "staff_test_bot"
    out = StringIO()

    call_command("signup_code", stdout=out)

    assert len(out.getvalue().split()) == 1


def test_the_admin_shows_a_new_code_once(admin_client):
    response = admin_client.post(
        "/admin/signin/signupcode/add/", {"note": "Yunusobod pharmacy", "uses_left": 1}, follow=True
    )

    assert response.status_code == 200
    code = SignupCode.objects.get()
    shown = [str(message) for message in response.context["messages"]]
    assert any("shown only once" in message for message in shown)
    raw = shown[0].split("<b>")[1].split("</b>")[0]
    assert code.code_hash == signup.code_hash(raw)


def test_signin_admin_pages_render(admin_client):
    for url in (
        "/admin/signin/signupcode/",
        "/admin/signin/loginlink/",
        "/admin/signin/devicesession/",
    ):
        assert admin_client.get(url).status_code == 200, url
