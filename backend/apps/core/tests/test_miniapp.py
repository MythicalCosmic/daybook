from pathlib import Path

from django.conf import settings as django_settings
from django.http import HttpResponse

from apps.core.miniapp import MiniAppWhiteNoiseMiddleware


def body(response) -> bytes:
    return b"".join(response.streaming_content)


def test_built_mini_app_is_served_at_app(tmp_path, settings, rf):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>daybook</html>")
    (dist / "assets" / "index-BJyE8SXe.js").write_text("console.log('daybook')")
    settings.MINIAPP_DIST = dist
    settings.STATIC_ROOT = tmp_path / "static"
    settings.STATIC_ROOT.mkdir()
    settings.WHITENOISE_INDEX_FILE = True

    middleware = MiniAppWhiteNoiseMiddleware(lambda request: HttpResponse(status=404))
    page = middleware(rf.get("/app/"))
    asset = middleware(rf.get("/app/assets/index-BJyE8SXe.js"))

    assert page.status_code == 200
    assert body(page) == b"<html>daybook</html>"
    # The page is checked again on every open (after a deploy it names new assets);
    # fingerprinted assets are cached for good, so phones never fetch them twice.
    assert page["Cache-Control"] == "no-cache"
    assert page["Last-Modified"]
    assert asset.status_code == 200
    assert "immutable" in asset["Cache-Control"]
    assert "max-age=315360000" in asset["Cache-Control"]
    revalidated = middleware(rf.get("/app/", HTTP_IF_MODIFIED_SINCE=page["Last-Modified"]))
    assert revalidated.status_code == 304


def test_missing_build_is_not_an_error(tmp_path, settings, rf):
    settings.MINIAPP_DIST = tmp_path / "nothing-here"
    settings.STATIC_ROOT = tmp_path / "static"
    settings.STATIC_ROOT.mkdir()

    middleware = MiniAppWhiteNoiseMiddleware(lambda request: HttpResponse(status=404))

    assert middleware(rf.get("/app/")).status_code == 404


def test_configured_paths_are_real_paths():
    # django-environ's env.path() returns its own Path type, which lacks is_dir().
    assert isinstance(django_settings.MINIAPP_DIST, Path)
    assert isinstance(django_settings.MEDIA_ROOT, Path)
