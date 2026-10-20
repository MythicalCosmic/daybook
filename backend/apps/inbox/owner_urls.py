"""Inbox endpoints, mounted at `/api/v1/owner/companies/<int:company_id>/`."""

from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.inbox.owner_api import InboxViewSet, NotificationPreferencesView

router = SimpleRouter()
router.register("inbox", InboxViewSet, basename="inbox")

urlpatterns = [
    *router.urls,
    path(
        "notification-preferences/",
        NotificationPreferencesView.as_view(),
        name="inbox-notification-preferences",
    ),
]
