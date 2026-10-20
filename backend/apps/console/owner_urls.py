"""Console endpoints outside a company (`me/`, `permissions/`), mounted at
`/api/v1/owner/`. The ones inside a company are in `company_urls.py`."""

from django.urls import path

from apps.console.owner_api import MeView, PermissionsView

urlpatterns = [
    path("me/", MeView.as_view(), name="console-me"),
    path("permissions/", PermissionsView.as_view(), name="console-permissions"),
]
