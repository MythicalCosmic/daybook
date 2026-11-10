"""The org chart's owner endpoint, included by `apps/lifecycle/owner_urls.py`."""

from django.urls import path

from apps.lifecycle.orgchart import owner_api

urlpatterns = [
    path("lifecycle/org/", owner_api.OrgChartView.as_view(), name="lifecycle-org"),
]
