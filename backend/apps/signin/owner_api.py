"""Owner sign-in endpoints under `/api/v1/owner/auth/`: refresh, logout and dev login.

Package A adds the login links (QR / deep link with number matching) and the Telegram Mini App
sign-in on top of `services.issue_session` and `services.issue_access`.
"""

from django.conf import settings
from django.http import Http404
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.signin import services
from apps.signin.auth import FromDashboard


class AccessSerializer(serializers.Serializer):
    access = serializers.CharField(help_text="Owner access token (aud=dashboard), 15 minutes.")


class DevLoginSerializer(serializers.Serializer):
    telegram_id = serializers.IntegerField()


class CookieAuthView(APIView):
    """Public endpoints that work with the refresh cookie, never with a Bearer token."""

    authentication_classes = ()
    permission_classes = (AllowAny, FromDashboard)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "owner_auth"

    def get_authenticate_header(self, request):
        # Makes a refused cookie a 401 (sign in again) rather than a 403.
        return 'Bearer realm="dashboard"'


class RefreshView(CookieAuthView):
    """Rotate the refresh cookie and return a new access token."""

    @extend_schema(
        request=None,
        responses={200: AccessSerializer, 401: OpenApiResponse(description="Sign in again.")},
        description=(
            "Needs the `owner_refresh` cookie, `X-Requested-With: dashboard` and a same-origin "
            "`Origin`. A refresh token used twice ends its session."
        ),
    )
    def post(self, request):
        raw = request.COOKIES.get(services.REFRESH_COOKIE)
        try:
            if not raw:
                raise services.RefreshFailed("No refresh cookie.")
            access, refresh = services.rotate(raw, request)
        except services.RefreshFailed:
            response = Response(
                {"detail": _("Your session has ended. Sign in again."), "code": "session_ended"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            services.clear_refresh_cookie(response)
            return response
        response = Response({"access": access})
        if refresh is not None:
            services.set_refresh_cookie(response, refresh)
        return response


class LogoutView(CookieAuthView):
    """End this browser's session and clear the refresh cookie."""

    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        services.logout(request.COOKIES.get(services.REFRESH_COOKIE))
        response = Response(status=status.HTTP_204_NO_CONTENT)
        services.clear_refresh_cookie(response)
        return response


class DevLoginView(CookieAuthView):
    """Development only (`DEBUG` and `DASHBOARD_DEV_LOGIN`): sign in as a Telegram id."""

    def initial(self, request, *args, **kwargs):
        # Switched off, it doesn't exist: 404 before any header, permission or throttle check
        # could answer differently.
        if not (settings.DEBUG and settings.DASHBOARD_DEV_LOGIN):
            raise Http404
        super().initial(request, *args, **kwargs)

    @extend_schema(request=DevLoginSerializer, responses={200: AccessSerializer})
    def post(self, request):
        serializer = DevLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.filter(telegram_id=serializer.validated_data["telegram_id"]).first()
        if user is None or not services.can_sign_in(user):
            raise PermissionDenied(_("You don't have access to the dashboard."))
        return services.session_response(user, request)
