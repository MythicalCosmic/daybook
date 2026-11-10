"""Owner endpoints of policies, included by apps/hr/owner_urls.py (under
`/api/v1/owner/companies/<int:company_id>/`)."""

from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.hr.policies import owner_api

router = SimpleRouter()
router.register("hr/policies", owner_api.PolicyViewSet, basename="hr-policy")

urlpatterns = [
    path(
        "hr/people/<int:member_id>/policies/",
        owner_api.PersonPoliciesView.as_view(),
        name="hr-person-policies",
    ),
    *router.urls,
]
