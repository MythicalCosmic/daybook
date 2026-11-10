"""Hiring's owner routes, included by `apps/hr/owner_urls.py` (prefix `hr/`)."""

from rest_framework.routers import SimpleRouter

from apps.hr.hiring import owner_api

router = SimpleRouter()
router.register("hr/vacancies", owner_api.VacancyViewSet, basename="hr-vacancy")
router.register("hr/applicants", owner_api.ApplicantViewSet, basename="hr-applicant")

urlpatterns = router.urls
