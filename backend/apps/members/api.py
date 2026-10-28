from django.db.models import Q
from drf_spectacular.utils import extend_schema, extend_schema_field, inline_serializer
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.generics import ListAPIView
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.companies.models import Branch, Company, Feature
from apps.members import bot_messages, departments, scope, services
from apps.members.models import Membership, Position
from apps.members.permissions import Perm
from apps.members.queries import person_ref


class CompanySerializer(serializers.ModelSerializer):
    features = serializers.ListField(
        child=serializers.ChoiceField(Feature.choices), help_text="Modules switched on."
    )

    class Meta:
        model = Company
        fields = (
            "id",
            "name",
            "timezone",
            "features",
            "owner_sees_personal_tasks",
            "base_currency",
            "team_directory_phones",
        )
        read_only_fields = fields


class BranchBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = ("id", "name")
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
    home_branch = BranchBriefSerializer(allow_null=True, help_text="Where they work.")
    branch_ids = serializers.SerializerMethodField()
    suspended_until = serializers.DateField(
        allow_null=True, help_text="While suspended: the last day of it; null: until reinstated."
    )
    joined_by_link = serializers.BooleanField(
        help_text="A team link let them in, without anyone's check (the app welcomes them)."
    )
    department = serializers.SerializerMethodField()
    manager = serializers.SerializerMethodField()
    team_size = serializers.SerializerMethodField()

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
            "home_branch",
            "branch_ids",
            "suspended_until",
            "joined_by_link",
            "department",
            "manager",
            "team_size",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.ListField(child=serializers.ChoiceField(Perm.choices)))
    def get_permissions(self, membership: Membership) -> list[str]:
        return [perm.value for perm in Perm if membership.has_perm(perm)]

    @extend_schema_field(
        inline_serializer(
            "MembersDepartmentRef",
            {"id": serializers.IntegerField(), "name": serializers.CharField()},
            allow_null=True,
        )
    )
    def get_department(self, membership: Membership) -> dict | None:
        department = membership.department
        return {"id": department.pk, "name": department.name} if department else None

    @extend_schema_field(
        inline_serializer(
            "MembersManager",
            {
                "id": serializers.IntegerField(),
                "name": serializers.CharField(),
                "photo_url": serializers.CharField(allow_null=True),
            },
            allow_null=True,
        )
    )
    def get_manager(self, membership: Membership) -> dict | None:
        """Their own head (the nearest head above them in the departments)."""
        return person_ref(departments.manager_of(membership, org=self._org(membership)))

    def get_team_size(self, membership: Membership) -> int:
        """People they manage through departments: a head may give them work."""
        return len(departments.team_ids(membership, org=self._org(membership)))

    def _org(self, membership: Membership) -> departments.Org:
        """The company's departments, loaded once per response."""
        orgs = self.context.setdefault("orgs", {})
        if membership.company_id not in orgs:
            orgs[membership.company_id] = departments.Org(membership.company_id)
        return orgs[membership.company_id]

    @extend_schema_field(serializers.ListField(child=serializers.IntegerField()))
    def get_branch_ids(self, membership: Membership) -> list[int]:
        """The branches they work in (what they may see is decided by their role too)."""
        return sorted(branch.pk for branch in membership.branches.all())


class OnboardingSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100)
    position_id = serializers.IntegerField(
        default=None,
        allow_null=True,
        help_text="Required when the company has positions.",
    )


class MemberSuspended(PermissionDenied):
    """403 {"code": "suspended", "detail": …, "until": "2026-10-31" | null}: the mini app shows
    its "Access paused" screen."""

    default_code = "suspended"

    def __init__(self, membership: Membership):
        until = membership.suspended_until
        text = bot_messages.paused_text(membership)
        super().__init__(text)
        # The body as is: DRF would turn a missing date into the string "None".
        self.detail = {
            "code": "suspended",
            "detail": text,
            "until": until.isoformat() if until else None,
        }


class IsCompanyMember(BasePermission):
    """Approved members of the URL's company get in; to anyone else the company doesn't exist.

    A suspended member gets 403 {"code": "suspended"} instead, except on views that set
    `allow_suspended = True` (their own profile, wallet and documents), and there only to read.
    """

    statuses = (Membership.Status.APPROVED,)

    def has_permission(self, request, view):
        membership = (
            Membership.objects.select_related("company", "user", "role", "position")
            .filter(
                company_id=view.kwargs["company_id"],
                company__is_active=True,
                user=request.user,
                status__in=(*self.statuses, Membership.Status.SUSPENDED),
            )
            .first()
        )
        if membership is None:
            raise NotFound
        if membership.status == Membership.Status.SUSPENDED:
            allowed = getattr(view, "allow_suspended", False) and request.method in SAFE_METHODS
            if not allowed:
                raise MemberSuspended(membership)
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
        return (
            member.has_perm(Perm.MEMBERS_VIEW)
            or member.has_perm(Perm.TASKS_ASSIGN)
            or departments.leads(member)
        )


class MemberListView(ListAPIView):
    """Registered members of the company, e.g. to pick who a task is for: with members.view or
    tasks.assign everyone with branches.all, otherwise the people sharing one of the caller's
    branches (§2.6); and for a head the people they manage (apps.members.departments)."""

    permission_classes = (IsAuthenticated, IsCompanyMember, CanSeeMembers)
    serializer_class = MemberBriefSerializer
    pagination_class = None

    def get_queryset(self):
        member = self.membership
        people = Membership.objects.for_company(member.company).filter(
            status=Membership.Status.APPROVED, onboarded_at__isnull=False
        )
        team = departments.team_ids(member)
        if member.has_perm(Perm.MEMBERS_VIEW) or member.has_perm(Perm.TASKS_ASSIGN):
            visible = scope.restrict(people, scope.branch_ids(member), field="branches")
            if team:
                visible = people.filter(Q(pk__in=visible.values("pk")) | Q(pk__in=team))
        else:
            visible = people.filter(Q(pk__in=team) | Q(pk=member.pk))
        return visible.select_related("user", "position").order_by("first_name", "last_name")


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
