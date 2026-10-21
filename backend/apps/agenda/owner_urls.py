"""Owner endpoints, mounted at `/api/v1/owner/companies/<int:company_id>/`.

An optional `root_urlpatterns` list is mounted at `/api/v1/owner/` instead, for the few
owner endpoints outside a company.
"""

from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.agenda.owner_api import CalendarView, EventViewSet, PeopleView, SettingsView, SourcesView

router = SimpleRouter()
router.register("calendar/events", EventViewSet, basename="agenda-event")

urlpatterns = [
    path("calendar/", CalendarView.as_view(), name="agenda-calendar"),
    path("calendar/sources/", SourcesView.as_view(), name="agenda-sources"),
    path("calendar/people/", PeopleView.as_view(), name="agenda-people"),
    path("calendar/settings/", SettingsView.as_view(), name="agenda-settings"),
    *router.urls,
]
