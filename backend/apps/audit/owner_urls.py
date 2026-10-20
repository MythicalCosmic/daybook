"""Owner endpoints, mounted at `/api/v1/owner/companies/<int:company_id>/`.

An optional `root_urlpatterns` list is mounted at `/api/v1/owner/` instead, for the few
owner endpoints outside a company.
"""

from django.urls import path

from apps.audit.owner_api import RecordHistoryView

urlpatterns = [
    path("audit/records/", RecordHistoryView.as_view(), name="audit-records"),
]
