"""Owner endpoints of tasks, mounted at `/api/v1/owner/companies/<int:company_id>/`
(docs/PLAN-OWNER.md §4.1: `tasks/`, `proofs/`, `routines/`)."""

from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.tasks.owner_api import (
    ProofWallView,
    RoutineViewSet,
    TaskOwnerViewSet,
    TasksSettingsView,
)

router = SimpleRouter()
router.register("tasks", TaskOwnerViewSet, basename="owner-task")
router.register("routines", RoutineViewSet, basename="owner-routine")

urlpatterns = [
    path("proofs/", ProofWallView.as_view(), name="owner-task-proofs"),
    # Before the router: "tasks/settings/" isn't a task id.
    path("tasks/settings/", TasksSettingsView.as_view(), name="owner-tasks-settings"),
    *router.urls,
]
