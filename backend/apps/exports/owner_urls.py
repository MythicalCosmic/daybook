"""Export endpoints, mounted at `/api/v1/owner/companies/<int:company_id>/`."""

from rest_framework.routers import SimpleRouter

from apps.exports.owner_api import ExportViewSet

router = SimpleRouter()
router.register("exports", ExportViewSet, basename="exports-export")

urlpatterns = [*router.urls]
