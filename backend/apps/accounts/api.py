from functools import partial

from django.db import transaction
from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts import company_switch
from apps.accounts.models import User
from apps.accounts.services import approved_memberships, bot_membership, sync_telegram_user
from apps.accounts.tasks import relabel_employee_chat
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
