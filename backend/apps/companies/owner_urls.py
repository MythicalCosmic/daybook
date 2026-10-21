"""Owner endpoints, mounted at `/api/v1/owner/companies/<int:company_id>/`.

`root_urlpatterns` is mounted at `/api/v1/owner/` instead: creating a company happens outside
any company (§13.2).
"""

from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.companies import owner_api

router = SimpleRouter()
router.register("branches", owner_api.BranchViewSet, basename="companies-branch")

urlpatterns = [
    path("settings/", owner_api.SettingsView.as_view(), name="companies-settings"),
    path("settings/logo/", owner_api.LogoView.as_view(), name="companies-logo"),
    path("features/", owner_api.FeaturesView.as_view(), name="companies-features"),
    path("invite/", owner_api.InviteView.as_view(), name="companies-invite"),
    path(
        "invite/regenerate/",
        owner_api.InviteRegenerateView.as_view(),
        name="companies-invite-regenerate",
    ),
    path("setup/", owner_api.SetupView.as_view(), name="companies-setup"),
    path("setup/dismiss/", owner_api.SetupDismissView.as_view(), name="companies-setup-dismiss"),
    path("setup/resume/", owner_api.SetupResumeView.as_view(), name="companies-setup-resume"),
    *router.urls,
]

root_urlpatterns = [
    path("companies/", owner_api.NewCompanyView.as_view(), name="companies-new"),
    path("companies/new/", owner_api.NewCompanyInfoView.as_view(), name="companies-new-info"),
]
