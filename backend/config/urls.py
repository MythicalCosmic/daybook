import re

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.core.spa import dashboard_index
from apps.core.storage import SANDBOX_HEADERS
from apps.core.views import health


def media(request, path):
    """Development only: MEDIA_ROOT with the headers Caddy adds in production."""
    response = serve(request, path, document_root=settings.MEDIA_ROOT)
    for header, value in SANDBOX_HEADERS.items():
        response[header] = value
    return response


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("api/v1/", include("config.api_urls")),
    # The full schema (both audiences, unless SCHEMA_AUDIENCE narrows it for a generator run).
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    # The owner dashboard's page for /dashboard/ and every client route; its fingerprinted
    # assets are served by WhiteNoise (apps.core.spa) and never fall back to the page.
    re_path(r"^dashboard/(?!assets/).*$", dashboard_index, name="dashboard"),
]

# Development only; in production the reverse proxy serves MEDIA_ROOT.
if settings.DEBUG:
    prefix = re.escape(settings.MEDIA_URL.strip("/"))
    urlpatterns.append(re_path(rf"^{prefix}/(?P<path>.*)$", media))
