"""Owner endpoints take owner tokens only (docs/PLAN-OWNER.md §7, §7.4)."""

from datetime import timedelta

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.signin.tokens import OwnerAccessToken

pytestmark = pytest.mark.django_db


def bearer(token) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.fixture
def owner(company, member):
    return member(company, "Owner")


def owner_urls(company) -> list[str]:
    return ["/api/v1/owner/me/", f"/api/v1/owner/companies/{company.pk}/pulse/"]


def test_an_owner_token_opens_owner_endpoints(company, owner, owner_api):
    for url in owner_urls(company):
        assert owner_api(owner).get(url).status_code == 200, url


def test_a_mini_app_token_gets_401_on_owner_endpoints(company, owner, api_as):
    for url in owner_urls(company):
        response = api_as(owner).get(url)
        assert response.status_code == 401, url
        assert response["WWW-Authenticate"].startswith("Bearer")


def test_a_mini_app_refresh_token_gets_401_too(company, owner):
    token = RefreshToken.for_user(owner.user)
    for url in owner_urls(company):
        assert bearer(token).get(url).status_code == 401
        assert bearer(token.access_token).get(url).status_code == 401


def test_no_token_gets_401(client, company):
    for url in owner_urls(company):
        assert client.get(url).status_code == 401


def test_an_expired_owner_token_gets_401(company, owner):
    token = OwnerAccessToken.for_user(owner.user)
    token.set_exp(lifetime=-timedelta(seconds=1))

    for url in owner_urls(company):
        assert bearer(token).get(url).status_code == 401


def test_a_deactivated_user_gets_401(company, owner, owner_api):
    client = owner_api(owner)
    owner.user.is_active = False
    owner.user.save()

    assert client.get("/api/v1/owner/me/").status_code == 401


def test_session_cookies_are_not_accepted_on_owner_endpoints(client, company, owner):
    client.force_login(owner.user)

    assert client.get(f"/api/v1/owner/companies/{company.pk}/pulse/").status_code == 401


def test_an_owner_token_gets_401_on_the_mini_app_api(company, owner, owner_api):
    response = owner_api(owner).get("/api/v1/me/")

    assert response.status_code == 401


def test_a_mini_app_token_still_works_on_the_mini_app_api(owner):
    assert bearer(AccessToken.for_user(owner.user)).get("/api/v1/me/").status_code == 200


def test_errors_are_in_the_users_language(company, owner):
    owner.user.language = "ru"
    owner.user.save()
    token = OwnerAccessToken.for_user(owner.user)

    response = bearer(token).get(f"/api/v1/owner/companies/{company.pk + 999}/pulse/")

    assert response.status_code == 404
    assert response["Content-Language"] == "ru"
