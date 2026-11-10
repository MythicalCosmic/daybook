"""Owner endpoints of Face ID, mounted at `/api/v1/owner/companies/<int:company_id>/`."""

from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.faceid.owner_api import (
    BotTestView,
    BotView,
    DeviceViewSet,
    EventViewSet,
    IgnoreView,
    LinkViewSet,
    PeopleView,
    SettingsView,
    StatusView,
)

router = SimpleRouter()
router.register("faceid/devices", DeviceViewSet, basename="faceid-device")
router.register("faceid/events", EventViewSet, basename="faceid-event")
router.register("faceid/links", LinkViewSet, basename="faceid-link")

urlpatterns = [
    path("faceid/status/", StatusView.as_view(), name="faceid-status"),
    path("faceid/people/", PeopleView.as_view(), name="faceid-people"),
    path("faceid/people/ignore/", IgnoreView.as_view(), name="faceid-people-ignore"),
    path("faceid/settings/", SettingsView.as_view(), name="faceid-settings"),
    path("faceid/bot/", BotView.as_view(), name="faceid-bot"),
    path("faceid/bot/test/", BotTestView.as_view(), name="faceid-bot-test"),
    *router.urls,
]
