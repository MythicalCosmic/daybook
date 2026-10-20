from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import User
from apps.accounts.services import sync_telegram_user
from apps.accounts.telegram_auth import InvalidInitData, validate_init_data
from apps.members.api import MembershipSerializer
from apps.members.models import Membership


class TelegramAuthSerializer(serializers.Serializer):
    init_data = serializers.CharField(help_text="Telegram.WebApp.initData, exactly as received.")


class AccessTokenSerializer(serializers.Serializer):
    access = serializers.CharField(
        help_text="Bearer token for the API. When it expires, sign in with initData again."
    )


class MeSerializer(serializers.ModelSerializer):
    memberships = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "telegram_id",
            "telegram_username",
            "first_name",
            "last_name",
            "phone",
            "language",
            "memberships",
        )
        read_only_fields = (
            "id",
            "telegram_id",
            "telegram_username",
            "first_name",
            "last_name",
            "phone",
        )

    @extend_schema_field(MembershipSerializer(many=True))
    def get_memberships(self, user: User) -> list[dict]:
        memberships = (
            Membership.objects.filter(user=user, company__is_active=True)
            .select_related("company", "role", "position", "home_branch")
            .prefetch_related("branches")
        )
        return MembershipSerializer(memberships, many=True).data


class TelegramAuthView(APIView):
    """Exchange the mini app's Telegram init data for an access token.

    Only an access token: the mini app signs in again with fresh init data when it expires,
    so no refresh token (and no blacklist row) is made every time the app opens.
    """

    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "telegram_auth"

    @extend_schema(request=TelegramAuthSerializer, responses=AccessTokenSerializer)
    def post(self, request):
        serializer = TelegramAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            tg_user = validate_init_data(serializer.validated_data["init_data"])
        except InvalidInitData as exc:
            raise AuthenticationFailed(str(exc)) from exc

        user = sync_telegram_user(
            telegram_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
            language_code=tg_user.language_code,
        )
        return Response({"access": str(AccessToken.for_user(user))})

    def get_authenticate_header(self, request):
        # Makes failed logins a 401 rather than a 403.
        return 'Bearer realm="api"'


class MeView(RetrieveUpdateAPIView):
    """The signed-in person, with every membership. Only `language` can be changed."""

    serializer_class = MeSerializer
    http_method_names = ("get", "patch", "options")

    def get_object(self):
        return self.request.user
