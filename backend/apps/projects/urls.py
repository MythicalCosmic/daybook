"""Employee endpoints, mounted at `/api/v1/companies/<int:company_id>/`."""

from django.urls import path

from apps.projects import api

urlpatterns = [
    path("projects/", api.MyProjectsView.as_view(), name="projects-mine"),
    path("projects/time/", api.MyTimeView.as_view(), name="projects-my-time"),
    path(
        "projects/time/<int:entry_id>/",
        api.MyTimeDetailView.as_view(),
        name="projects-my-time-detail",
    ),
    path("projects/timer/", api.MyTimerView.as_view(), name="projects-my-timer"),
    path("projects/timer/stop/", api.MyTimerStopView.as_view(), name="projects-my-timer-stop"),
    path(
        "projects/<int:project_id>/board/",
        api.EmployeeBoardView.as_view(),
        name="projects-employee-board",
    ),
    path(
        "projects/<int:project_id>/cards/<int:task_id>/move/",
        api.EmployeeMoveView.as_view(),
        name="projects-employee-move",
    ),
    path(
        "projects/<int:project_id>/updates/",
        api.EmployeeUpdatesView.as_view(),
        name="projects-employee-updates",
    ),
]
