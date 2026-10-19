from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.generics import ListAPIView
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.companies.models import Company
from apps.members import services
from apps.members.models import Membership, Position
from apps.members.permissions import Perm


class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ("id", "name", "timezone")


class PositionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Position
        fields = ("id", "name")


class MembershipSerializer(serializers.ModelSerializer):
    company = CompanySerializer()
    position = PositionSerializer(allow_null=True)
    role = serializers.CharField(source="role.name", allow_null=True)
    permissions = serializers.SerializerMethodField()
    is_onboarded = serializers.BooleanField()

    class Meta:
        model = Membership
        fields = (
            "id",
            "company",
            "status",
            "first_name",
            "last_name",
            "position",
            "role",
            "permissions",
            "is_onboarded",
        )

    @extend_schema_field(serializers.ListField(child=serializers.ChoiceField(Perm.choices)))
    def get_permissions(self, membership: Membership) -> list[str]:
        return [perm.value for perm in Perm if membership.has_perm(perm)]


class OnboardingSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100)
    position_id = serializers.IntegerField(
        default=None,
        allow_null=True,
        help_text="Required when the company has positions.",
    )


class IsCompanyMember(BasePermission):
    """Approved members of the URL's company get in; to anyone else the company doesn't exist."""

    def has_permission(self, request, view):
        membership = (
            Membership.objects.select_related("company", "user", "role", "position")
            .filter(
                company_id=view.kwargs["company_id"],
                company__is_active=True,
                user=request.user,
                status=Membership.Status.APPROVED,
            )
            .first()
        )
        if membership is None:
            raise NotFound
        view.membership = membership
        return True


class PositionListView(ListAPIView):
    """Positions an employee can pick during onboarding."""

    permission_classes = (IsAuthenticated, IsCompanyMember)
    serializer_class = PositionSerializer
    pagination_class = None

    def get_queryset(self):
        return Position.objects.for_company(self.membership.company).filter(is_active=True)


class OnboardingView(APIView):
    """Finish registration: name and position. The phone comes from Telegram contact sharing."""

    permission_classes = (IsAuthenticated, IsCompanyMember)

    @extend_schema(request=OnboardingSerializer, responses=MembershipSerializer)
    def post(self, request, company_id):
        serializer = OnboardingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = services.complete_onboarding(self.membership, **serializer.validated_data)
        return Response(MembershipSerializer(membership).data)
