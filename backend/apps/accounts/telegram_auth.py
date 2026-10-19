"""Verifies the launch data Telegram hands the mini app (Telegram.WebApp.initData)."""

from datetime import timedelta

from aiogram.utils.web_app import WebAppUser, safe_parse_webapp_init_data
from django.conf import settings
from django.utils import timezone


class InvalidInitData(Exception):
    pass


def validate_init_data(init_data: str) -> WebAppUser:
    token = settings.EMPLOYEE_BOT_TOKEN
    if not token:
        raise InvalidInitData("Mini app login isn't configured.")
    try:
        # Checks the HMAC that Telegram computed with the employee bot's token.
        data = safe_parse_webapp_init_data(token, init_data)
    except ValueError as exc:
        raise InvalidInitData("Invalid init data.") from exc
    if data.user is None:
        raise InvalidInitData("Init data has no user.")
    if timezone.now() - data.auth_date > timedelta(seconds=settings.MINIAPP_INIT_DATA_MAX_AGE):
        raise InvalidInitData("Init data has expired. Reopen the app.")
    return data.user
