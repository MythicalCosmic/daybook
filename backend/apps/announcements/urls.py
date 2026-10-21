"""Employee endpoints, mounted at `/api/v1/companies/<int:company_id>/`."""

from rest_framework.routers import SimpleRouter

from apps.announcements.api import AnnouncementFeedViewSet

router = SimpleRouter()
router.register("announcements", AnnouncementFeedViewSet, basename="announcements-feed")

urlpatterns = router.urls
