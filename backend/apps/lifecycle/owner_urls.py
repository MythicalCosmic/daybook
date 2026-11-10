"""Owner endpoints, mounted at `/api/v1/owner/companies/<int:company_id>/` (prefix `lifecycle/`).

An optional `root_urlpatterns` list is mounted at `/api/v1/owner/` instead, for the few
owner endpoints outside a company.
"""

from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.lifecycle import owner_api, review_owner_urls

router = SimpleRouter()
router.register(
    "lifecycle/discipline", owner_api.DisciplineViewSet, basename="lifecycle-discipline"
)
router.register(
    "lifecycle/suspensions", owner_api.SuspensionViewSet, basename="lifecycle-suspension"
)
router.register(
    "lifecycle/terminations", owner_api.TerminationViewSet, basename="lifecycle-termination"
)
router.register(
    "lifecycle/job-changes", owner_api.JobChangeViewSet, basename="lifecycle-job-change"
)

urlpatterns = [
    *router.urls,
    path(
        "lifecycle/people/<int:member_id>/career/",
        owner_api.CareerView.as_view(),
        name="lifecycle-career",
    ),
    # The org chart and equipment (package B, v11).
    path("", include("apps.lifecycle.orgchart.owner_urls")),
    path("", include("apps.lifecycle.equipment.owner_urls")),
    # Performance reviews.
    *review_owner_urls.urlpatterns,
]
