import time

import pytest

from apps.accounts.telegram_auth import InvalidInitData, validate_init_data
from apps.accounts.tests.telegram import BOT_TOKEN, signed_init_data


@pytest.fixture(autouse=True)
def bot_token(settings):
    settings.EMPLOYEE_BOT_TOKEN = BOT_TOKEN


def test_valid_init_data_yields_the_telegram_user():
    user = validate_init_data(signed_init_data(user_id=42))

    assert user.id == 42
    assert user.username == "ali"


def test_tampered_init_data_is_rejected():
    tampered = signed_init_data(user_id=42).replace("%22id%22%3A42", "%22id%22%3A43")

    with pytest.raises(InvalidInitData):
        validate_init_data(tampered)


def test_init_data_signed_by_another_bot_is_rejected():
    with pytest.raises(InvalidInitData):
        validate_init_data(signed_init_data(token="999:OTHER-BOT"))


def test_stale_init_data_is_rejected(settings):
    two_days_ago = int(time.time()) - 2 * 24 * 60 * 60

    with pytest.raises(InvalidInitData, match="expired"):
        validate_init_data(signed_init_data(auth_date=two_days_ago))


@pytest.mark.parametrize("init_data", ["", "not a query string", "user=%7B%7D"])
def test_garbage_is_rejected(init_data):
    with pytest.raises(InvalidInitData):
        validate_init_data(init_data)


def test_login_is_refused_without_a_bot_token(settings):
    settings.EMPLOYEE_BOT_TOKEN = ""

    with pytest.raises(InvalidInitData, match="configured"):
        validate_init_data(signed_init_data())


def test_owner_init_data_is_checked_against_the_owner_bot(settings):
    settings.OWNER_BOT_TOKEN = "777:OWNER-BOT"
    owner_data = signed_init_data(user_id=7, token="777:OWNER-BOT")

    assert validate_init_data(owner_data, bot="owner").id == 7
    with pytest.raises(InvalidInitData):
        validate_init_data(owner_data)  # the employee bot didn't sign it
    with pytest.raises(InvalidInitData):
        validate_init_data(signed_init_data(), bot="owner")


def test_owner_sign_in_allows_an_hour_by_default(settings):
    settings.OWNER_BOT_TOKEN = BOT_TOKEN
    two_hours_ago = int(time.time()) - 2 * 60 * 60

    with pytest.raises(InvalidInitData, match="expired"):
        validate_init_data(signed_init_data(auth_date=two_hours_ago), bot="owner")
    assert validate_init_data(signed_init_data(auth_date=two_hours_ago)).id == 42  # employee: a day


def test_max_age_can_be_given(settings):
    ten_minutes_ago = int(time.time()) - 10 * 60

    with pytest.raises(InvalidInitData, match="expired"):
        validate_init_data(signed_init_data(auth_date=ten_minutes_ago), max_age=60)
    assert validate_init_data(signed_init_data(auth_date=ten_minutes_ago), max_age=3600)


def test_init_data_from_the_future_is_rejected():
    tomorrow = int(time.time()) + 24 * 60 * 60

    with pytest.raises(InvalidInitData, match="future"):
        validate_init_data(signed_init_data(auth_date=tomorrow))


def test_unknown_bots_are_a_programming_error():
    with pytest.raises(ValueError):
        validate_init_data(signed_init_data(), bot="other")
