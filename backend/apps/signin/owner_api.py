"""Owner sign-in endpoints under `/api/v1/owner/auth/` (docs/PLAN-OWNER.md §4.3, §7).

POST login-links/                 a QR / deep link with a match number (public, 10/min/IP)
GET  login-links/{id}/            {status} for the browser holding the poll token
POST login-links/{id}/claim/      once, when approved: {access} + the refresh cookie
POST telegram/                    Mini App initData → {access}, no cookie (inside Telegram)
POST refresh/ · logout/           the refresh cookie (rotation, reuse detection)
POST dev-login/                   development only
GET  sessions/ · POST sessions/{id}/revoke/ · POST sessions/revoke-all/
"""

from django.conf import settings
from django.http import Http404
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle, SimpleRateThrottle
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.signin import devices, links, services
from apps.signin.auth import FromDashboard, OwnerJWTAuthentication
from apps.signin.models import DeviceSession, LoginLink
from apps.signin.tokens import SESSION_CLAIM

POLL_HEADER = "X-Login-Poll"


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


# Login links (desktop: QR / deep link, number matching, POST claim) -------------------------


class LoginLinkSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    poll_token = serializers.CharField(
        help_text="Secret only this browser holds; send it as X-Login-Poll."
    )
    deep_link = serializers.CharField(help_text="https://t.me/<bot>?start=login_<code>")
    bot_username = serializers.CharField()
    match_code = serializers.CharField(help_text="The 2-digit number to tap in Telegram.")
    expires_at = serializers.DateTimeField()


class LoginLinkStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(LoginLink.Status.choices)


class LinkPollThrottle(SimpleRateThrottle):
    """60 polls a minute per link, whoever asks."""

    scope = "login_poll"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": str(view.kwargs.get("link_id"))}


class LoginLinksView(APIView):
    """Start a desktop sign-in: show `deep_link` as a QR and `match_code` in large type."""

    authentication_classes = ()
    permission_classes = (AllowAny, FromDashboard)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "login_link"

    @extend_schema(
        request=None,
        responses={
            201: LoginLinkSerializer,
            503: OpenApiResponse(description="Telegram sign-in isn't set up."),
        },
    )
    def post(self, request):
        try:
            made = links.create_link(request)
        except links.SigninUnavailable:
            return Response(
                {
                    "detail": _("Telegram sign-in isn't set up on this server yet."),
                    "code": "signin_unavailable",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(
            {
                "id": str(made.link.pk),
                "poll_token": made.poll_token,
                "deep_link": made.deep_link,
                "bot_username": made.bot_username,
                "match_code": made.link.match_code,
                "expires_at": made.link.expires_at,
            },
            status=status.HTTP_201_CREATED,
        )


_POLL = OpenApiParameter(POLL_HEADER, str, OpenApiParameter.HEADER, required=True)


class LoginLinkView(APIView):
    """Where a sign-in stands. Never changes anything and never returns a token."""

    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = (LinkPollThrottle,)

    @extend_schema(parameters=[_POLL], responses={200: LoginLinkStatusSerializer, 404: None})
    def get(self, request, link_id):
        found = links.status_for(link_id, request.headers.get(POLL_HEADER, ""))
        if found is None:
            raise NotFound
        return Response({"status": found})


class LoginLinkClaimView(APIView):
    """Collect the session of an approved sign-in, once."""

    authentication_classes = ()
    permission_classes = (AllowAny, FromDashboard)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "login_claim"

    @extend_schema(
        parameters=[_POLL],
        request=None,
        responses={
            200: AccessSerializer,
            403: OpenApiResponse(description="No dashboard access."),
            404: OpenApiResponse(description="Unknown link or wrong poll token."),
            409: OpenApiResponse(description="Not approved, expired or already used."),
        },
    )
    def post(self, request, link_id):
        try:
            issued = links.claim(link_id, request.headers.get(POLL_HEADER, ""), request)
        except links.ClaimRefused as refused:
            return Response(
                {"detail": _claim_message(refused.code), "code": refused.code},
                status=refused.status,
            )
        response = Response({"access": issued.access})
        services.set_refresh_cookie(response, issued.refresh)
        return response


def _claim_message(code: str) -> str:
    return {
        "not_found": _("This sign-in wasn't found. Start again."),
        "used": _("This sign-in was already used. Start again."),
        "pending": _("Confirm the sign-in in Telegram first."),
        "denied": _("This sign-in was cancelled in Telegram."),
        "expired": _("This sign-in has expired. Get a new code."),
        "no_access": _("You don't have access to the dashboard."),
    }.get(code, _("This sign-in can't be used. Start again."))


# Inside Telegram (Mini App initData; no cookie, no session) ----------------------------------


class TelegramLoginSerializer(serializers.Serializer):
    init_data = serializers.CharField(max_length=4096)


class TelegramLoginView(APIView):
    """Sign in with `Telegram.WebApp.initData` (owner bot, else employee bot), at most
    `OWNER_INIT_DATA_MAX_AGE` old. Answers an access token only; post the same initData again
    when it runs out."""

    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    # Its own bucket: dashboard tabs refreshing from the same office can't lock out the mini app.
    throttle_scope = "owner_telegram"

    def get_authenticate_header(self, request):
        return 'Bearer realm="dashboard"'

    @extend_schema(
        request=TelegramLoginSerializer,
        responses={
            200: AccessSerializer,
            401: OpenApiResponse(description="Invalid or old initData."),
            403: OpenApiResponse(description="No dashboard access."),
        },
    )
    def post(self, request):
        serializer = TelegramLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = services.user_from_init_data(serializer.validated_data["init_data"])
        except services.InitDataRefused as refused:
            if refused.code == "no_access":
                return Response(
                    {"detail": _("You don't have access to the dashboard."), "code": "no_access"},
                    status=status.HTTP_403_FORBIDDEN,
                )
            return Response(
                {
                    "detail": _("Session ended. Reopen the dashboard from the bot."),
                    "code": refused.code,
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )
        return Response({"access": services.issue_access(user)})


# Device sessions ------------------------------------------------------------------------------


class DeviceSerializer(serializers.Serializer):
    label = serializers.CharField(help_text='"Chrome · Windows"')
    browser = serializers.CharField()
    system = serializers.CharField()
    kind = serializers.ChoiceField(["phone", "tablet", "desktop"])


class DeviceSessionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    device = DeviceSerializer()
    ip = serializers.CharField(help_text="Masked: 213.230.x.x")
    created_at = serializers.DateTimeField()
    last_seen_at = serializers.DateTimeField()
    current = serializers.BooleanField(help_text="The session this request comes from.")


class RevokeAllSerializer(serializers.Serializer):
    keep_current = serializers.BooleanField(
        default=False, help_text="Keep this browser signed in (log out every other device)."
    )


class RevokedSerializer(serializers.Serializer):
    revoked = serializers.IntegerField()
    signed_out = serializers.BooleanField(help_text="This browser was signed out too.")


class SessionUserView(APIView):
    authentication_classes = (OwnerJWTAuthentication,)
    permission_classes = (IsAuthenticated,)

    def current_session_id(self) -> int | None:
        token = getattr(self.request, "auth", None)
        value = token.get(SESSION_CLAIM) if token is not None else None
        return value if isinstance(value, int) else None


def session_row(session: DeviceSession, current: int | None) -> dict:
    device = devices.describe(session.user_agent)
    return {
        "id": session.pk,
        "device": {
            "label": device.label,
            "browser": device.browser,
            "system": device.system,
            "kind": device.kind,
        },
        "ip": devices.masked_ip(session.ip),
        "created_at": session.created_at,
        "last_seen_at": session.last_seen_at,
        "current": session.pk == current,
    }


class SessionsView(SessionUserView):
    """Browsers signed in to the dashboard as you (inside Telegram there is no session)."""

    @extend_schema(responses=DeviceSessionSerializer(many=True))
    def get(self, request):
        current = self.current_session_id()
        rows = [session_row(s, current) for s in services.active_sessions(request.user)]
        rows.sort(key=lambda row: not row["current"])  # this browser first
        return Response(rows)


class SessionRevokeView(SessionUserView):
    """Sign one browser out: its refresh stops working at once, its access token within 15
    minutes. Revoking this browser's own session also clears its cookie."""

    @extend_schema(request=None, responses={200: RevokedSerializer, 404: None})
    def post(self, request, session_id):
        session = DeviceSession.objects.filter(pk=session_id, user=request.user).first()
        if session is None or session.revoked_at is not None:
            raise NotFound
        services.revoke_session(session)
        own = session.pk == self.current_session_id()
        response = Response({"revoked": 1, "signed_out": own})
        if own:
            services.clear_refresh_cookie(response)
        return response


class SessionsRevokeAllView(SessionUserView):
    """Log out everywhere (every session, every outstanding token), or every other device."""

    @extend_schema(request=RevokeAllSerializer, responses=RevokedSerializer)
    def post(self, request):
        serializer = RevokeAllSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        current = self.current_session_id()
        if serializer.validated_data["keep_current"] and current is not None:
            count = services.revoke_others(request.user, keep=current)
            return Response({"revoked": count, "signed_out": False})
        count = services.revoke_all(request.user)
        response = Response({"revoked": count, "signed_out": True})
        services.clear_refresh_cookie(response)
        return response
