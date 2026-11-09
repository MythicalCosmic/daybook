"""Employee endpoints of package Q1 (courses, lessons, videos, who watched what), mounted at
`/api/v1/companies/<int:company_id>/` through `urls.py`."""

from django.urls import path

from apps.learning.api_courses import (
    CertificateView,
    CourseView,
    HomeView,
    LessonView,
    ProgressView,
    StartView,
)

urlpatterns = [
    path("learning/", HomeView.as_view(), name="learning-home"),
    path("learning/courses/<int:pk>/", CourseView.as_view(), name="learning-course"),
    path("learning/courses/<int:pk>/start/", StartView.as_view(), name="learning-course-start"),
    path("learning/lessons/<int:pk>/", LessonView.as_view(), name="learning-lesson"),
    path(
        "learning/lessons/<int:pk>/progress/",
        ProgressView.as_view(),
        name="learning-lesson-progress",
    ),
    path(
        "learning/assignments/<int:pk>/certificate/",
        CertificateView.as_view(),
        name="learning-certificate",
    ),
]
