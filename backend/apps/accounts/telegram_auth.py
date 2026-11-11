"""Verifies the launch data Telegram hands a Mini App (Telegram.WebApp.initData).

Telegram signs it with the token of the bot that opened the app, so the employee mini app is
checked against the employee bot and the owner dashboard (opened from the owner bot) against
the owner bot. In the Davomat edition the web app opens from the organization's own bot, whose
token is saved in Settings (`apps.davomat`): `bot="davomat"`, refused in any other edition.
`max_age` is how old the data may be, in seconds: the mini app allows a day
(`MINIAPP_INIT_DATA_MAX_AGE`), owner sign-in an hour (`OWNER_INIT_DATA_MAX_AGE`).
"""

from datetime import timedelta
from typing import Literal

from aiogram.utils.web_app import WebAppUser, safe_parse_webapp_init_data
from django.conf import settings
from django.utils import timezone

Bot = Literal["employee", "owner", "davomat"]


class InvalidInitData(Exception):
    pass


def validate_init_data(
    init_data: str, *, bot: Bot = "employee", max_age: int | None = None
) -> WebAppUser:
    """The Telegram user of valid, fresh init data signed by `bot`; raises InvalidInitData."""
    if bot == "employee":
        token = settings.EMPLOYEE_BOT_TOKEN
        default_max_age = settings.MINIAPP_INIT_DATA_MAX_AGE
    elif bot == "owner":
        token = settings.OWNER_BOT_TOKEN
        default_max_age = settings.OWNER_INIT_DATA_MAX_AGE
    elif bot == "davomat":
        token = davomat_bot_token()
        default_max_age = settings.OWNER_INIT_DATA_MAX_AGE
    else:
        raise ValueError(f"Unknown bot {bot!r}.")
    if not token:
        raise InvalidInitData("Mini app login isn't configured.")
    try:
        # Checks the HMAC that Telegram computed with that bot's token.
        data = safe_parse_webapp_init_data(token, init_data)
    except ValueError as exc:
        raise InvalidInitData("Invalid init data.") from exc
    if data.user is None:
        raise InvalidInitData("Init data has no user.")
    age = timezone.now() - data.auth_date
    if age > timedelta(seconds=default_max_age if max_age is None else max_age):
        raise InvalidInitData("Init data has expired. Reopen the app.")
    if age < -timedelta(minutes=5):
        raise InvalidInitData("Init data is dated in the future.")
    return data.user


def davomat_bot_token() -> str:
    """The Davomat organization's own bot token (decrypted), only in that edition: anywhere else
    no launch data is ever taken as signed by it."""
    if settings.EDITION != "davomat":
        return ""
    from apps.davomat.queries import bot_token

    return bot_token()
