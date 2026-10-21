"""Employee endpoints, mounted at `/api/v1/companies/<int:company_id>/`."""

from django.urls import path

from apps.agenda.api import CalendarView, EventView, RespondView

urlpatterns = [
    path("calendar/", CalendarView.as_view(), name="agenda-employee-calendar"),
    path("calendar/events/<int:pk>/", EventView.as_view(), name="agenda-employee-event"),
    path(
        "calendar/events/<int:pk>/respond/", RespondView.as_view(), name="agenda-employee-respond"
    ),
]
