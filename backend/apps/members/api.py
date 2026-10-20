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
        read_only_fields = fields


class PositionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Position
        fields = ("id", "name")
        read_only_fields = fields


class MembershipSerializer(serializers.ModelSerializer):
    company = CompanySerializer()
    position = PositionSerializer(allow_null=True)
    role = serializers.CharField(source="role.name", allow_null=True)
    permissions = serializers.SerializerMethodField()
    is_onboarded = serializers.BooleanField()
    rejoin_available_at = serializers.DateTimeField(
        allow_null=True, help_text="When a rejected person can ask again."
    )

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
            "onboarded_at",
            "decided_at",
            "rejoin_available_at",
        )
        read_only_fields = fields

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

    statuses = (Membership.Status.APPROVED,)

    def has_permission(self, request, view):
        membership = (
            Membership.objects.select_related("company", "user", "role", "position")
            .filter(
                company_id=view.kwargs["company_id"],
                company__is_active=True,
                user=request.user,
                status__in=self.statuses,
            )
            .first()
        )
        if membership is None:
            raise NotFound
        view.membership = membership
        return True


class IsCompanyApplicant(IsCompanyMember):
    """Also lets in people whose request is pending, so they can create their account."""

    statuses = (Membership.Status.PENDING, Membership.Status.APPROVED)


def requires(perm: Perm) -> type[BasePermission]:
    """Permission class for an endpoint that needs `perm` in the URL's company."""

    class RequiresPerm(BasePermission):
        def has_permission(self, request, view):
            return view.membership.has_perm(perm)

    RequiresPerm.__name__ = f"Requires_{perm.name}"
    return RequiresPerm


class MemberBriefSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="__str__")
    position = serializers.CharField(source="position.name", allow_null=True)

    class Meta:
        model = Membership
        fields = ("id", "name", "position")
        read_only_fields = fields


class CanSeeMembers(BasePermission):
    def has_permission(self, request, view):
        member = view.membership
        return member.has_perm(Perm.MEMBERS_VIEW) or member.has_perm(Perm.TASKS_ASSIGN)


class MemberListView(ListAPIView):
    """Registered members of the company, e.g. to pick who a task is for."""

    permission_classes = (IsAuthenticated, IsCompanyMember, CanSeeMembers)
    serializer_class = MemberBriefSerializer
    pagination_class = None

    def get_queryset(self):
        return (
            Membership.objects.for_company(self.membership.company)
            .filter(status=Membership.Status.APPROVED, onboarded_at__isnull=False)
            .select_related("user", "position")
            .order_by("first_name", "last_name")
        )


class PositionListView(ListAPIView):
    """Positions an employee can pick when creating their account."""

    permission_classes = (IsAuthenticated, IsCompanyApplicant)
    serializer_class = PositionSerializer
    pagination_class = None

    def get_queryset(self):
        return Position.objects.for_company(self.membership.company).filter(is_active=True)


class OnboardingView(APIView):
    """Create the account: name and position. The phone comes from Telegram contact sharing.

    For a pending request this is what sends it to the approvers.
    """

    permission_classes = (IsAuthenticated, IsCompanyApplicant)

    @extend_schema(request=OnboardingSerializer, responses=MembershipSerializer)
    def post(self, request, company_id):
        serializer = OnboardingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = services.complete_onboarding(self.membership, **serializer.validated_data)
        return Response(MembershipSerializer(membership).data)
