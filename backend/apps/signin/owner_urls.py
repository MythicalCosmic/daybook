"""Owner sign-in endpoints, mounted at `/api/v1/owner/auth/`."""

from django.urls import path

from apps.signin.owner_api import DevLoginView, LogoutView, RefreshView

urlpatterns = [
    path("refresh/", RefreshView.as_view(), name="signin-refresh"),
    path("logout/", LogoutView.as_view(), name="signin-logout"),
    path("dev-login/", DevLoginView.as_view(), name="signin-dev-login"),
]
