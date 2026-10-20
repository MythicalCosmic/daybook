"""Owner endpoints of time off, mounted at `/api/v1/owner/companies/<int:company_id>/`
(docs/PLAN-OWNER.md §4.6). Leave types and balances come with package L."""

from rest_framework.routers import SimpleRouter

from apps.timeoff.owner_api import HolidayViewSet, TimeOffViewSet

router = SimpleRouter()
router.register("time-off", TimeOffViewSet, basename="timeoff-time-off")
router.register("holidays", HolidayViewSet, basename="timeoff-holiday")

urlpatterns = router.urls
