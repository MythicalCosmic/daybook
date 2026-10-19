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
