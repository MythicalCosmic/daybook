"""Employee endpoints of fixed assets, mounted at `/api/v1/companies/<int:company_id>/`."""

from django.urls import path

from apps.assets import api

urlpatterns = [
    path("assets/mine/", api.MineView.as_view(), name="assets-mine"),
    path(
        "assets/mine/<int:pk>/acknowledge/",
        api.AcknowledgeView.as_view(),
        name="assets-mine-acknowledge",
    ),
]
