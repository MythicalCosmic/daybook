"""The owner dashboard and the mini app, served next to the API (apps.core.spa)."""

import pytest
from django.http import HttpResponse

from apps.core import miniapp
from apps.core.spa import DASHBOARD_CSP, SpaWhiteNoiseMiddleware

INDEX = b'<!doctype html><script type="module" src="/dashboard/assets/index-BJyE8SXe.js"></script>'
CSP = (
    "default-src 'self'; img-src 'self' data: blob: https://*.tile.openstreetmap.org; "
    "connect-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' https://telegram.org; "
    "frame-ancestors https://web.telegram.org; base-uri 'none'; form-action 'self'"
)


def body(response) -> bytes:
    return b"".join(response.streaming_content)


@pytest.fixture
def dashboard(tmp_path, settings):
    dist = tmp_path / "dashboard"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_bytes(INDEX)
    (dist / "assets" / "index-BJyE8SXe.js").write_text("console.log('console')")
    settings.DASHBOARD_DIST = dist
    return dist


def assert_page_headers(response):
    assert response["Content-Security-Policy"] == CSP
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Referrer-Policy"] == "same-origin"
    assert response["Cache-Control"] == "no-cache"
    # Telegram Web frames the dashboard; frame-ancestors decides who may, not X-Frame-Options.
    assert "X-Frame-Options" not in response


def test_the_policy_is_exactly_the_planned_one():
    assert DASHBOARD_CSP == CSP


@pytest.mark.parametrize(
    "url", ["/dashboard/", "/dashboard/c/12/sales/shifts/1042", "/dashboard/login"]
)
def test_every_dashboard_route_gets_the_page_with_its_headers(client, dashboard, url):
    response = client.get(url)

    assert response.status_code == 200
    assert response.content == INDEX
    assert response["Content-Type"] == "text/html; charset=utf-8"
    assert_page_headers(response)


def test_the_bare_path_redirects_to_the_page(client, dashboard):
    response = client.get("/dashboard")

    assert response.status_code == 301
    assert response["Location"] == "/dashboard/"


def test_unknown_assets_never_fall_back_to_the_page(client, dashboard):
    # Otherwise a missing script would be answered with HTML.
    assert client.get("/dashboard/assets/missing-AAAAAAAA.js").status_code == 404


def test_an_unchanged_page_is_not_sent_again(client, dashboard):
    first = client.get("/dashboard/")
    again = client.get("/dashboard/c/1", HTTP_IF_NONE_MATCH=first["ETag"])

    assert again.status_code == 304
    assert_page_headers(again)


def test_a_rebuilt_page_is_sent(client, dashboard):
    first = client.get("/dashboard/")
    (dashboard / "index.html").write_bytes(INDEX + b"<!-- v2 -->")

    again = client.get("/dashboard/", HTTP_IF_NONE_MATCH=first["ETag"])

    assert again.status_code == 200
    assert again.content.endswith(b"<!-- v2 -->")


def test_only_reading_is_allowed(client, dashboard):
    response = client.post("/dashboard/")

    assert response.status_code == 405
    assert_page_headers(response)


def test_a_missing_build_says_so(client, settings, tmp_path):
    settings.DASHBOARD_DIST = tmp_path / "nothing-here"

    response = client.get("/dashboard/")

    assert response.status_code == 404
    assert b"isn't built" in response.content
    assert_page_headers(response)


@pytest.fixture
def middleware(tmp_path, settings, dashboard):
    app = tmp_path / "miniapp"
    (app / "assets").mkdir(parents=True)
    (app / "index.html").write_text("<html>daybook</html>")
    settings.MINIAPP_DIST = app
    settings.STATIC_ROOT = tmp_path / "static"
    settings.STATIC_ROOT.mkdir()
    settings.WHITENOISE_INDEX_FILE = True
    return SpaWhiteNoiseMiddleware(lambda request: HttpResponse("from django", status=404))


def test_dashboard_assets_are_served_for_good(middleware, rf):
    response = middleware(rf.get("/dashboard/assets/index-BJyE8SXe.js"))

    assert response.status_code == 200
    assert body(response) == b"console.log('console')"
    assert "immutable" in response["Cache-Control"]


def test_the_dashboard_page_is_never_served_by_whitenoise(middleware, rf):
    # It must come from dashboard_index, with the security headers.
    for url in ("/dashboard/", "/dashboard/index.html", "/dashboard/assets/../index.html"):
        assert middleware(rf.get(url)).status_code == 404


def test_the_mini_app_is_still_served(middleware, rf):
    response = middleware(rf.get("/app/"))

    assert response.status_code == 200
    assert body(response) == b"<html>daybook</html>"


def test_the_old_middleware_name_still_works():
    assert miniapp.MiniAppWhiteNoiseMiddleware is SpaWhiteNoiseMiddleware
