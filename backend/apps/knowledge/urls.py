"""Employee endpoints, mounted at `/api/v1/companies/<int:company_id>/`."""

from django.urls import path

from apps.knowledge.api import AckView, HomeView, LinkedView, PageView, SearchView, SpaceView

urlpatterns = [
    path("knowledge/", HomeView.as_view(), name="knowledge-home"),
    path("knowledge/search/", SearchView.as_view(), name="knowledge-search"),
    path("knowledge/linked/", LinkedView.as_view(), name="knowledge-linked"),
    path("knowledge/spaces/<int:pk>/", SpaceView.as_view(), name="knowledge-employee-space"),
    path("knowledge/pages/<int:pk>/", PageView.as_view(), name="knowledge-employee-page"),
    path("knowledge/pages/<int:pk>/ack/", AckView.as_view(), name="knowledge-employee-ack"),
]
