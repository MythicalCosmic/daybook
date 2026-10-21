"""Owner endpoints of reminders, mounted at `/api/v1/owner/companies/<int:company_id>/`
(docs/PLAN-OWNER.md §4.1: `reminder-policies/`, `reminder-log/`, `blocked-bot/`)."""

from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.reminders.owner_api import BlockedBotView, ReminderLogView, ReminderPolicyOwnerViewSet

router = SimpleRouter()
router.register("reminder-policies", ReminderPolicyOwnerViewSet, basename="owner-reminder-policy")

urlpatterns = [
    path("reminder-log/", ReminderLogView.as_view(), name="owner-reminder-log"),
    path("blocked-bot/", BlockedBotView.as_view(), name="owner-reminders-blocked-bot"),
    *router.urls,
]
