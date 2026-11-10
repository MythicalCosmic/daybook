"""Owner endpoints, mounted at `/api/v1/owner/companies/<int:company_id>/` (§4.10, prefix `hr/`).

An optional `root_urlpatterns` list is mounted at `/api/v1/owner/` instead, for the few
owner endpoints outside a company.
"""

from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.hr import owner_api
from apps.hr.policies import owner_urls as policies

router = SimpleRouter()
router.register("hr/documents", owner_api.DocumentViewSet, basename="hr-document")
router.register(
    "hr/required-documents", owner_api.RequiredDocumentViewSet, basename="hr-required-document"
)
router.register(
    "hr/contract-templates", owner_api.ContractTemplateViewSet, basename="hr-contract-template"
)
router.register("hr/contracts", owner_api.ContractViewSet, basename="hr-contract")
router.register(
    r"hr/people/(?P<member_id>\d+)/emergency-contacts",
    owner_api.EmergencyContactViewSet,
    basename="hr-emergency-contact",
)

urlpatterns = [
    path("hr/settings/", owner_api.SettingsView.as_view(), name="hr-settings"),
    path("hr/overview/", owner_api.OverviewView.as_view(), name="hr-overview"),
    path("hr/celebrations/", owner_api.CelebrationsView.as_view(), name="hr-celebrations"),
    path("hr/coverage/", owner_api.CoverageView.as_view(), name="hr-coverage"),
    path("hr/coverage/live/", owner_api.LiveCoverageView.as_view(), name="hr-coverage-live"),
    path(
        "hr/coverage/pharmacists/",
        owner_api.PharmacistsView.as_view(),
        name="hr-coverage-pharmacists",
    ),
    path("hr/people/<int:member_id>/profile/", owner_api.ProfileView.as_view(), name="hr-profile"),
    path(
        "hr/people/<int:member_id>/sensitive/",
        owner_api.SensitiveView.as_view(),
        name="hr-sensitive",
    ),
    *router.urls,
    # Hiring: vacancies and applicants (apps.hr.hiring).
    path("", include("apps.hr.hiring.owner_urls")),
    *policies.urlpatterns,
]
