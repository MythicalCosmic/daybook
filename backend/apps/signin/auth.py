"""How owner endpoints authenticate: `OwnerJWTAuthentication` and nothing else.

No session authentication on the owner API, so it has no CSRF surface. The cookie endpoints
(refresh, logout, the login-link claim) add `FromDashboard`: the custom header
`X-Requested-With: dashboard` and a same-origin `Origin`, on top of the cookie's
`SameSite=Strict`.
"""

from django.conf import settings
from django.utils import translation
from django.utils.translation import gettext_lazy as _
from drf_spectacular.contrib.rest_framework_simplejwt import SimpleJWTScheme
from rest_framework.permissions import BasePermission
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from apps.signin.tokens import OwnerAccessToken

DASHBOARD_HEADER = "dashboard"


class OwnerJWTAuthentication(JWTAuthentication):
    """Bearer owner access tokens (`aud="dashboard"`); a mini app token gets a 401.

    Answers in the person's language, like the mini app's authentication does.
    """

    www_authenticate_realm = "dashboard"

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is not None:
            user, _token = result
            translation.activate(user.language)
            request.LANGUAGE_CODE = translation.get_language()
        return result

    def get_validated_token(self, raw_token: bytes) -> OwnerAccessToken:
        try:
            return OwnerAccessToken(raw_token)
        except TokenError as exc:
            raise InvalidToken(
                {"detail": _("Sign in to the dashboard again."), "code": "token_not_valid"}
            ) from exc


class OwnerJWTScheme(SimpleJWTScheme):
    """Documents the owner login in the API schema."""

    target_class = "apps.signin.auth.OwnerJWTAuthentication"
    name = "ownerJwtAuth"


def is_same_origin(request) -> bool:
    """Whether the request's `Origin` is this site (or one of `CSRF_TRUSTED_ORIGINS`)."""
    origin = request.headers.get("Origin")
    if not origin:
        return False
    allowed = {f"{request.scheme}://{request.get_host()}", *settings.CSRF_TRUSTED_ORIGINS}
    return origin in allowed


class FromDashboard(BasePermission):
    """The dashboard itself made this request: custom header plus same-origin `Origin`."""

    message = _("This request must come from the dashboard.")

    def has_permission(self, request, view):
        return request.headers.get("X-Requested-With") == DASHBOARD_HEADER and is_same_origin(
            request
        )
