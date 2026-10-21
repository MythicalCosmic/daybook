"""Owner endpoints, mounted at `/api/v1/owner/companies/<int:company_id>/`.

An optional `root_urlpatterns` list is mounted at `/api/v1/owner/` instead, for the few
owner endpoints outside a company.
"""

from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.knowledge.owner_api import (
    ImageUploadView,
    LinkDeleteView,
    LinkTargetsView,
    OverviewView,
    PageViewSet,
    PositionsView,
    SettingsView,
    SpaceViewSet,
)

router = SimpleRouter()
router.register("knowledge/spaces", SpaceViewSet, basename="knowledge-space")
router.register("knowledge/pages", PageViewSet, basename="knowledge-page")

urlpatterns = [
    path("knowledge/overview/", OverviewView.as_view(), name="knowledge-overview"),
    path("knowledge/images/", ImageUploadView.as_view(), name="knowledge-images"),
    path("knowledge/links/<int:pk>/", LinkDeleteView.as_view(), name="knowledge-link"),
    path("knowledge/link-targets/", LinkTargetsView.as_view(), name="knowledge-link-targets"),
    path("knowledge/positions/", PositionsView.as_view(), name="knowledge-positions"),
    path("knowledge/settings/", SettingsView.as_view(), name="knowledge-settings"),
    *router.urls,
]
