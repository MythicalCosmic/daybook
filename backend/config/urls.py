from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.core.spa import dashboard_index
from apps.core.views import health

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
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
