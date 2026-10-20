"""Owner endpoints, mounted at `/api/v1/owner/companies/<int:company_id>/`."""

from rest_framework.routers import SimpleRouter

from apps.groups.owner_api import GroupViewSet

router = SimpleRouter()
router.register("groups", GroupViewSet, basename="groups-group")

urlpatterns = router.urls
