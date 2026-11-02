"""Owner endpoints, mounted at `/api/v1/owner/companies/<int:company_id>/` (§4.10, prefix `hr/`).

An optional `root_urlpatterns` list is mounted at `/api/v1/owner/` instead, for the few
owner endpoints outside a company.
"""

from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.hr import owner_api

router = SimpleRouter()
router.register("hr/documents", owner_api.DocumentViewSet, basename="hr-document")
router.register(
    "hr/required-documents", owner_api.RequiredDocumentViewSet, basename="hr-required-document"
)
router.register(
    r"hr/people/(?P<member_id>\d+)/emergency-contacts",
    owner_api.EmergencyContactViewSet,
    basename="hr-emergency-contact",
)

urlpatterns = [
    path("hr/settings/", owner_api.SettingsView.as_view(), name="hr-settings"),
    path("hr/overview/", owner_api.OverviewView.as_view(), name="hr-overview"),
    path("hr/people/<int:member_id>/profile/", owner_api.ProfileView.as_view(), name="hr-profile"),
    path(
        "hr/people/<int:member_id>/sensitive/",
        owner_api.SensitiveView.as_view(),
        name="hr-sensitive",
    ),
    *router.urls,
]
