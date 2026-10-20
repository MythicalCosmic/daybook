"""Employee endpoints, mounted at `/api/v1/companies/<int:company_id>/`."""

from django.urls import path

from apps.inbox.api import EmployeeInboxView, EmployeeMarkReadView

urlpatterns = [
    path("inbox/", EmployeeInboxView.as_view(), name="inbox-employee"),
    path("inbox/read/", EmployeeMarkReadView.as_view(), name="inbox-employee-read"),
]
