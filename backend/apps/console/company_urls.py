"""Console endpoints inside a company (pulse, search, queue, stream, branches today,
saved views), mounted at `/api/v1/owner/companies/<int:company_id>/`.

`owner_urls.py` holds the ones outside a company (`me/`, `permissions/`), mounted at
`/api/v1/owner/`.
"""

from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.console.owner_api import (
    BranchesTodayView,
    PulseView,
    QueueCountsView,
    QueueView,
    SavedViewViewSet,
    SearchView,
    StreamView,
)

router = SimpleRouter()
router.register("saved-views", SavedViewViewSet, basename="console-saved-view")

urlpatterns = [
    path("pulse/", PulseView.as_view(), name="console-pulse"),
    path("search/", SearchView.as_view(), name="console-search"),
    path("queue/", QueueView.as_view(), name="console-queue"),
    path("queue/counts/", QueueCountsView.as_view(), name="console-queue-counts"),
    path("stream/", StreamView.as_view(), name="console-stream"),
    path("branches/today/", BranchesTodayView.as_view(), name="console-branches-today"),
    *router.urls,
]
