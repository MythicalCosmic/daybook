"""Owner endpoints of package Q1 (courses, lessons, videos, who watched what), mounted at
`/api/v1/owner/companies/<int:company_id>/` through `owner_urls.py`."""

from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.learning.owner_api_courses import (
    AssignmentViewSet,
    CourseViewSet,
    LessonViewSet,
    OverviewView,
    PeopleView,
    PersonView,
    SettingsView,
    StepTargetsView,
    VideoViewSet,
)

router = SimpleRouter()
router.register("learning/courses", CourseViewSet, basename="learning-owner-course")
router.register("learning/lessons", LessonViewSet, basename="learning-owner-lesson")
router.register("learning/videos", VideoViewSet, basename="learning-owner-video")
router.register("learning/assignments", AssignmentViewSet, basename="learning-owner-assignment")

urlpatterns = [
    path("learning/overview/", OverviewView.as_view(), name="learning-owner-overview"),
    path("learning/people/", PeopleView.as_view(), name="learning-owner-people"),
    path("learning/people/<int:pk>/", PersonView.as_view(), name="learning-owner-person"),
    path("learning/step-targets/", StepTargetsView.as_view(), name="learning-owner-targets"),
    path("learning/settings/", SettingsView.as_view(), name="learning-owner-settings"),
    *router.urls,
]
