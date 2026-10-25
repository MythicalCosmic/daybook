"""The site's own addresses: the bare domain and the API map."""

import pytest
from django.contrib.auth import get_user_model

pytestmark = pytest.mark.django_db


def test_the_bare_address_opens_the_dashboard(client):
    response = client.get("/")

    assert response.status_code == 302
    assert response["Location"] == "/dashboard/"


@pytest.mark.parametrize("path", ["/api/schema/", "/api/docs/"])
def test_the_api_map_is_closed_to_strangers_in_production(client, path):
    assert client.get(path).status_code in (401, 403)


def test_staff_signed_in_to_the_admin_may_read_the_api_map(client):
    staff = get_user_model().objects.create_user(username="admin-reader", is_staff=True)
    client.force_login(staff)

    assert client.get("/api/schema/").status_code == 200


def test_the_api_map_is_open_in_development(client, settings):
    settings.DEBUG = True

    assert client.get("/api/schema/").status_code == 200
