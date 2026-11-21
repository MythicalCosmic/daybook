"""Owner endpoints of the unchangeable lists, mounted at `/api/v1/owner/companies/<int:company_id>/`
through `owner_urls.py`."""

from rest_framework.routers import SimpleRouter

from apps.learning.owner_api_lists import StudyListViewSet

router = SimpleRouter()
router.register("learning/lists", StudyListViewSet, basename="learning-owner-list")

urlpatterns = [*router.urls]
