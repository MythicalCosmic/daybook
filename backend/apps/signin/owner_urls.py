"""Owner sign-in endpoints, mounted at `/api/v1/owner/auth/`."""

from django.urls import path

from apps.signin.owner_api import (
    DevLoginView,
    LoginLinkClaimView,
    LoginLinksView,
    LoginLinkView,
    LogoutView,
    RefreshView,
    SessionRevokeView,
    SessionsRevokeAllView,
    SessionsView,
    TelegramLoginView,
)

urlpatterns = [
    path("refresh/", RefreshView.as_view(), name="signin-refresh"),
    path("logout/", LogoutView.as_view(), name="signin-logout"),
    path("dev-login/", DevLoginView.as_view(), name="signin-dev-login"),
    path("login-links/", LoginLinksView.as_view(), name="signin-login-links"),
    path("login-links/<str:link_id>/", LoginLinkView.as_view(), name="signin-login-link"),
    path(
        "login-links/<str:link_id>/claim/",
        LoginLinkClaimView.as_view(),
        name="signin-login-link-claim",
    ),
    path("telegram/", TelegramLoginView.as_view(), name="signin-telegram"),
    path("sessions/", SessionsView.as_view(), name="signin-sessions"),
    path(
        "sessions/revoke-all/", SessionsRevokeAllView.as_view(), name="signin-sessions-revoke-all"
    ),
    path(
        "sessions/<int:session_id>/revoke/",
        SessionRevokeView.as_view(),
        name="signin-session-revoke",
    ),
]
