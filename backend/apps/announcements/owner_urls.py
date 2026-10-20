"""Owner endpoints of announcements, mounted at `/api/v1/owner/companies/<int:company_id>/`
(docs/PLAN-OWNER.md §4.6)."""

from rest_framework.routers import SimpleRouter

from apps.announcements.owner_api import AnnouncementViewSet

router = SimpleRouter()
router.register("announcements", AnnouncementViewSet, basename="announcements-announcement")

urlpatterns = router.urls
