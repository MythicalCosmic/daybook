"""Owner tokens: their own audience and token types, so neither app's token opens the other."""

from datetime import timedelta

import jwt
import pytest
from django.conf import settings as django_settings
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.accounts.tests.factories import UserFactory
from apps.signin.tokens import AUDIENCE, OwnerAccessToken, OwnerRefreshToken

pytestmark = pytest.mark.django_db


def claims(token) -> dict:
    return jwt.decode(str(token), options={"verify_signature": False})


def test_owner_access_token_names_the_dashboard_audience():
    token = OwnerAccessToken.for_user(UserFactory())

    payload = claims(token)
    assert payload["aud"] == AUDIENCE == "dashboard"
    assert payload["token_type"] == "owner_access"


def test_owner_access_token_lives_as_long_as_the_setting_says(settings):
    settings.OWNER_ACCESS_TOKEN_LIFETIME = timedelta(minutes=5)

    payload = claims(OwnerAccessToken.for_user(UserFactory()))

    assert payload["exp"] - payload["iat"] == 300


def test_access_token_from_an_owner_refresh_token_keeps_the_session():
    refresh = OwnerRefreshToken.for_user(UserFactory())
    refresh["sid"] = 17

    access = claims(refresh.access_token)

    assert access["sid"] == 17
    assert access["aud"] == "dashboard"
    assert access["token_type"] == "owner_access"


def test_owner_refresh_token_lives_seven_days():
    payload = claims(OwnerRefreshToken.for_user(UserFactory()))

    assert payload["exp"] - payload["iat"] == 7 * 24 * 3600
    assert payload["token_type"] == "owner_refresh"


def test_a_mini_app_token_is_not_an_owner_token():
    employee = AccessToken.for_user(UserFactory())

    with pytest.raises(TokenError):
        OwnerAccessToken(str(employee))


def test_an_owner_token_is_not_a_mini_app_token():
    owner = OwnerAccessToken.for_user(UserFactory())

    with pytest.raises(TokenError):
        AccessToken(str(owner))


def test_a_token_for_another_audience_is_refused():
    payload = claims(OwnerAccessToken.for_user(UserFactory())) | {"aud": "someone-else"}
    forged = jwt.encode(payload, django_settings.SECRET_KEY, algorithm="HS256")

    with pytest.raises(TokenError):
        OwnerAccessToken(forged)


def test_a_token_signed_with_another_key_is_refused():
    payload = claims(OwnerAccessToken.for_user(UserFactory()))
    forged = jwt.encode(payload, "not-the-secret-key-not-the-secret-key", algorithm="HS256")

    with pytest.raises(TokenError):
        OwnerAccessToken(forged)


def test_an_owner_refresh_token_is_not_an_access_token():
    refresh = OwnerRefreshToken.for_user(UserFactory())

    with pytest.raises(TokenError):
        OwnerAccessToken(str(refresh))
    with pytest.raises(TokenError):
        RefreshToken(str(refresh))
