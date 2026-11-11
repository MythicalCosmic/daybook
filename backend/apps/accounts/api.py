from functools import partial

from django.db import transaction
from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts import company_switch
from apps.accounts.models import User
from apps.accounts.services import approved_memberships, bot_membership, sync_telegram_user
from apps.accounts.tasks import relabel_employee_chat
from apps.accounts.telegram_auth import InvalidInitData, validate_init_data
from apps.core.throttles import AddressRateThrottle, throttle_person
from apps.members.api import MembershipSerializer
from apps.members.models import Membership


class TelegramAuthSerializer(serializers.Serializer):
    init_data = serializers.CharField(help_text="Telegram.WebApp.initData, exactly as received.")


class AccessTokenSerializer(serializers.Serializer):
    access = serializers.CharField(
        help_text="Bearer token for the API (1 hour). When it expires, post `refresh` to "
        "auth/telegram/refresh/; when that is refused, sign in with initData again."
    )
    refresh = serializers.CharField(
        help_text="Refresh token (7 days, rotates on every use, blacklisted after): keep it in "
        "the page, never in lasting storage."
    )


class TelegramRefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField(max_length=2048)


class RefreshedSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField(help_text="The next refresh token; the one sent is spent.")


class MeSerializer(serializers.ModelSerializer):
    memberships = serializers.SerializerMethodField()
    bot_company = serializers.IntegerField(
        source="bot_company_id",
        allow_null=True,
        required=False,
        help_text=(
            "The company the person works in, the same in the bot, the mini app and the "
            "dashboard: the one they picked last, else the one they see first (a company they "
            "own, the most branches). Set it to switch."
        ),
    )

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
            "bot_company",
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

    def to_representation(self, user: User) -> dict:
        data = super().to_representation(user)
        membership = bot_membership(user)
        approved = membership is not None and membership.status == Membership.Status.APPROVED
        data["bot_company"] = membership.company_id if approved else None
        return data

    def validate_bot_company(self, value: int | None) -> int | None:
        if value is not None and value not in {
            member.company_id for member in approved_memberships(self.instance)
        }:
            raise serializers.ValidationError(_("You don't work in that company."))
        return value

    @extend_schema_field(MembershipSerializer(many=True))
    def get_memberships(self, user: User) -> list[dict]:
        memberships = (
            Membership.objects.filter(user=user, company__is_active=True)
            .select_related("company", "role", "position", "home_branch", "department")
            .prefetch_related("branches")
        )
        return MembershipSerializer(memberships, many=True).data


class TelegramAuthView(APIView):
    """Exchange the mini app's Telegram init data for an access token and a refresh token.

    Init data is good for a day (`MINIAPP_INIT_DATA_MAX_AGE`); the refresh token keeps an open
    app signed in after that (`auth/telegram/refresh/`, rotating, 7 days), so it never says
    "session ended" while someone is using it. They are simplejwt's own tokens (no audience,
    types `access`/`refresh`): never accepted by the dashboard's endpoints, nor theirs here.

    Limited per Telegram user once the signature checks out; per address only by a ceiling
    that a whole shift behind one mobile operator's NAT address never reaches.
    """

    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = (AddressRateThrottle,)
    address_throttle_scope = "telegram_auth_address"

    @extend_schema(request=TelegramAuthSerializer, responses=AccessTokenSerializer)
    def post(self, request):
        serializer = TelegramAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            tg_user = validate_init_data(serializer.validated_data["init_data"])
        except InvalidInitData as exc:
            raise AuthenticationFailed(str(exc)) from exc
        throttle_person(self, request, "telegram_auth", tg_user.id)

        user = sync_telegram_user(
            telegram_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
            # Uzbek first: an account the mini app makes speaks Uzbek whatever language Telegram
            # is in (the person picks another in Profile); an existing account keeps its own.
            language_code=None,
        )
        refresh = RefreshToken.for_user(user)
        return Response({"access": str(refresh.access_token), "refresh": str(refresh)})

    def get_authenticate_header(self, request):
        # Makes failed logins a 401 rather than a 403.
        return 'Bearer realm="api"'


class TelegramRefreshView(APIView):
    """The mini app's next access token: the refresh token it kept, rotated (the one sent is
    blacklisted). 401 when it is expired, spent, blacklisted or the account is switched off: the
    app then signs in with initData again. An owner (dashboard) token is refused here.

    Limited per person once the token checks out, per address by the sign-in's ceiling."""

    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = (AddressRateThrottle,)
    address_throttle_scope = "telegram_auth_address"

    @extend_schema(request=TelegramRefreshSerializer, responses=RefreshedSerializer)
    def post(self, request):
        serializer = TelegramRefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        raw = serializer.validated_data["refresh"]
        try:
            user_id = RefreshToken(raw)[jwt_settings.USER_ID_CLAIM]
        except (TokenError, KeyError) as exc:
            raise InvalidToken(_("Your session has ended. Sign in again.")) from exc
        throttle_person(self, request, "telegram_auth", f"user{user_id}")
        rotated = TokenRefreshSerializer(data={"refresh": raw})
        try:
            rotated.is_valid(raise_exception=True)
        except TokenError as exc:
            raise InvalidToken(_("Your session has ended. Sign in again.")) from exc
        except User.DoesNotExist as exc:
            raise InvalidToken(_("Your session has ended. Sign in again.")) from exc
        return Response(rotated.validated_data)

    def get_authenticate_header(self, request):
        return 'Bearer realm="api"'


class MeView(RetrieveUpdateAPIView):
    """The signed-in person, with every membership. `language` and `bot_company` can be changed:
    a new language relabels the person's chat with the employee bot too (its menus and
    keyboard), and the company is the one the bot's lists and new tasks use."""

    serializer_class = MeSerializer
    http_method_names = ("get", "patch", "options")

    def get_object(self):
        return self.request.user

    def perform_update(self, serializer):
        before = serializer.instance.language
        company_before = company_switch.bot_company_id(serializer.instance)
        user = serializer.save()
        if user.language != before:
            transaction.on_commit(partial(relabel_employee_chat.delay, user.pk))
        if "bot_company_id" in serializer.validated_data:
            # A switch in the mini app: the bot works in that company from now on, and says so.
            company_switch.follow(user, company_before)
