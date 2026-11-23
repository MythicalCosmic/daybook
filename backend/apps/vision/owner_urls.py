"""Owner endpoints of Ko‘z, mounted at `/api/v1/owner/companies/<int:company_id>/`
(docs/KOZ.md §6)."""

from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.vision import owner_api

router = SimpleRouter()
router.register("vision/cameras", owner_api.CameraViewSet, basename="vision-camera")
router.register("vision/alerts", owner_api.AlertViewSet, basename="vision-alert")
router.register("vision/clips", owner_api.ClipViewSet, basename="vision-clip")
router.register("vision/agents", owner_api.AgentViewSet, basename="vision-agent")

urlpatterns = [
    path("vision/overview/", owner_api.OverviewView.as_view(), name="vision-overview"),
    path("vision/live/", owner_api.LiveView.as_view(), name="vision-live"),
    path("vision/settings/", owner_api.SettingsView.as_view(), name="vision-settings"),
    path("vision/review/", owner_api.ReviewView.as_view(), name="vision-review"),
    *router.urls,
]
