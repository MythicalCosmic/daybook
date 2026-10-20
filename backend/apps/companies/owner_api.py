"""Owner endpoints of company setup (docs/PLAN-OWNER.md §4.4, §13.2).

Under `/api/v1/owner/companies/<id>/`:

    GET/PATCH settings/        GET: dashboard.access; PATCH: company.settings
    POST/DELETE settings/logo/ company.settings (multipart `logo`, re-encoded on the server)
    GET/PATCH features/        company.settings; switching a module on creates its defaults
    CRUD branches/             list: dashboard.access (branch scope); writes: company.settings;
                               closing instead of deleting; branches/reorder/
    GET invite/ · POST invite/regenerate/          members.approve
    GET setup/ · POST setup/dismiss/ · setup/resume/   GET: dashboard.access

Outside a company (`root_urlpatterns`, `/api/v1/owner/`):

    GET companies/new/         who may create a company, and what can be copied
    POST companies/            a new company (COMPANY_SIGNUP), optionally copying setup
"""

from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.companies import queries, services
from apps.companies.models import Branch, Company, Feature
from apps.console import registry
from apps.console.base import OwnerAPIView, OwnerUserAPIView, OwnerViewSet
from apps.core import uploads
from apps.core.models import Language
from apps.core.money import Currency, MoneySerializerField
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.signin import signup

TIME_FORMATS = ["%H:%M", "%H:%M:%S"]
LOGO_MAX_SIDE = 1024


def _clock_field(**kwargs) -> serializers.TimeField:
    return serializers.TimeField(format="%H:%M", input_formats=TIME_FORMATS, **kwargs)


# Settings ---------------------------------------------------------------------------------


class CompanySettingsSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=200)
    slug = serializers.CharField(read_only=True)
    logo = serializers.SerializerMethodField()
    timezone = serializers.CharField(max_length=64)
    default_language = serializers.ChoiceField(Language.choices)
    base_currency = serializers.ChoiceField(Currency.choices)
    base_currency_locked = serializers.SerializerMethodField(
        help_text="True once the finance ledger has rows: the base currency can't change."
    )
    workdays = serializers.ListField(
        child=serializers.IntegerField(min_value=0, max_value=6),
        help_text="0 = Monday … 6 = Sunday.",
    )
    morning_report_at = _clock_field()
    evening_report_at = _clock_field()
    morning_digest = serializers.BooleanField()
    rejoin_cooldown_hours = serializers.IntegerField(min_value=0, max_value=24 * 30)
    owner_sees_personal_tasks = serializers.BooleanField()
    team_directory_phones = serializers.BooleanField()
    features = serializers.ListField(child=serializers.CharField(), read_only=True)
    setup_completed = serializers.SerializerMethodField()

    def get_logo(self, company: Company) -> str | None:
        return company.logo.url if company.logo else None

    def get_base_currency_locked(self, company: Company) -> bool:
        return services.base_currency_locked(company)

    def get_setup_completed(self, company: Company) -> bool:
        return company.setup_completed_at is not None


class SettingsView(OwnerAPIView):
    """The company's own settings."""

    perms_by_action = {"patch": Perm.COMPANY_SETTINGS}

    @extend_schema(responses=CompanySettingsSerializer)
    def get(self, request, company_id):
        return Response(CompanySettingsSerializer(self.company).data)

    @extend_schema(request=CompanySettingsSerializer, responses=CompanySettingsSerializer)
    def patch(self, request, company_id):
        serializer = CompanySettingsSerializer(self.company, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        company = services.update_settings(
            self.company, by=self.membership, **serializer.validated_data
        )
        self.bump("companies.settings")
        return Response(CompanySettingsSerializer(company).data)


class LogoView(OwnerAPIView):
    """Upload (multipart `logo`) or remove the company logo. Pictures are re-encoded."""

    perm = Perm.COMPANY_SETTINGS
    parser_classes = (MultiPartParser, FormParser)

    @extend_schema(
        request={
            "multipart/form-data": inline_serializer(
                "CompaniesLogoUpload", {"logo": serializers.ImageField()}
            )
        },
        responses=CompanySettingsSerializer,
    )
    def post(self, request, company_id):
        upload = request.FILES.get("logo")
        if upload is None:
            raise ValidationError({"logo": [_("Choose a picture.")]})
        clean = uploads.sanitize_image(upload, max_side=LOGO_MAX_SIDE)
        company = services.set_logo(self.company, by=self.membership, logo=clean)
        self.bump("companies.settings")
        return Response(CompanySettingsSerializer(company).data)

    @extend_schema(request=None, responses=CompanySettingsSerializer)
    def delete(self, request, company_id):
        company = services.set_logo(self.company, by=self.membership, logo=None)
        self.bump("companies.settings")
        return Response(CompanySettingsSerializer(company).data)


# Modules ----------------------------------------------------------------------------------


class ModuleSerializer(serializers.Serializer):
    key = serializers.ChoiceField(Feature.choices)
    label = serializers.CharField()
    enabled = serializers.BooleanField()


class FeaturesSerializer(serializers.Serializer):
    features = serializers.ListField(child=serializers.ChoiceField(Feature.choices))
    modules = ModuleSerializer(many=True, read_only=True)


def features_body(company: Company) -> dict:
    return {
        "features": list(company.features),
        "modules": [
            {"key": key, "label": str(label), "enabled": key in company.features}
            for key, label in Feature.choices
        ],
    }


class FeaturesView(OwnerAPIView):
    """Module switches (`Company.features`)."""

    perm = Perm.COMPANY_SETTINGS

    @extend_schema(responses=FeaturesSerializer)
    def get(self, request, company_id):
        return Response(features_body(self.company))

    @extend_schema(request=FeaturesSerializer, responses=FeaturesSerializer)
    def patch(self, request, company_id):
        serializer = FeaturesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        company = services.set_features(
            self.company, by=self.membership, features=serializer.validated_data["features"]
        )
        self.bump("companies.settings", "companies.setup")
        return Response(features_body(company))


# Branches ---------------------------------------------------------------------------------


class PersonSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class BranchSerializer(serializers.ModelSerializer):
    manager = serializers.SerializerMethodField()
    manager_id = serializers.IntegerField(
        write_only=True, required=False, allow_null=True, help_text="A Membership id."
    )
    latitude = serializers.DecimalField(
        max_digits=9, decimal_places=6, required=False, allow_null=True
    )
    longitude = serializers.DecimalField(
        max_digits=9, decimal_places=6, required=False, allow_null=True
    )
    opens_at = _clock_field(required=False, allow_null=True)
    closes_at = _clock_field(required=False, allow_null=True)
    open_weekdays = serializers.ListField(
        child=serializers.IntegerField(min_value=0, max_value=6), required=False
    )
    cash_limit = MoneySerializerField(positive=False, required=False, allow_null=True)
    people = serializers.SerializerMethodField(help_text="Approved members working there.")

    class Meta:
        model = Branch
        fields = (
            "id",
            "name",
            "code",
            "address",
            "phone",
            "latitude",
            "longitude",
            "geofence_m",
            "opens_at",
            "closes_at",
            "open_weekdays",
            "manager",
            "manager_id",
            "cash_limit",
            "is_active",
            "order",
            "people",
        )
        read_only_fields = ("id", "is_active", "order")
        extra_kwargs = {"name": {"required": True}}

    def get_manager(self, branch: Branch) -> dict | None:
        manager = branch.manager
        return {"id": manager.pk, "name": str(manager)} if manager else None

    def get_people(self, branch: Branch) -> int:
        return getattr(branch, "people", 0)

    def to_service(self) -> dict:
        data = dict(self.validated_data)
        if "manager_id" in data:
            data["manager"] = data.pop("manager_id")
        return data


class ReorderSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(), min_length=1)


class ManagerOptionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    position = serializers.CharField()
    branch = serializers.CharField()
    photo_url = serializers.CharField(allow_null=True)


class BranchViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, OwnerViewSet):
    """Branches: address, hours, open weekdays, the check-in geofence, manager, cash limit.
    Closed instead of deleted, so their history stays."""

    serializer_class = BranchSerializer
    pagination_class = None
    perm = Perm.COMPANY_SETTINGS
    perms_by_action = {"list": None, "retrieve": None}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Branch.objects.none()
        return queries.branches(self.company, branch_ids=self.branch_scope)

    @extend_schema(request=BranchSerializer, responses={201: BranchSerializer})
    def create(self, request, company_id):
        serializer = BranchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        branch = services.create_branch(self.company, by=self.membership, **serializer.to_service())
        self.bump("companies.branches", "companies.setup")
        return Response(self._fresh(branch), status=status.HTTP_201_CREATED)

    @extend_schema(request=BranchSerializer, responses=BranchSerializer)
    def partial_update(self, request, company_id, pk):
        branch = self.get_object()
        serializer = BranchSerializer(branch, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        branch = services.update_branch(branch, by=self.membership, **serializer.to_service())
        self.bump("companies.branches", "companies.setup")
        return Response(self._fresh(branch))

    @extend_schema(request=None, responses=BranchSerializer)
    @action(detail=True, methods=["post"])
    def deactivate(self, request, company_id, pk):
        branch = services.deactivate_branch(self.get_object(), by=self.membership)
        self.bump("companies.branches", "companies.setup")
        return Response(self._fresh(branch))

    @extend_schema(request=None, responses=BranchSerializer)
    @action(detail=True, methods=["post"])
    def activate(self, request, company_id, pk):
        branch = services.activate_branch(self.get_object(), by=self.membership)
        self.bump("companies.branches", "companies.setup")
        return Response(self._fresh(branch))

    @extend_schema(responses=ManagerOptionSerializer(many=True))
    @action(detail=False, methods=["get"])
    def managers(self, request, company_id):
        """Who can manage a branch: the company's approved members."""
        members = (
            Membership.objects.for_company(self.company)
            .filter(status=Membership.Status.APPROVED)
            .select_related("user", "position", "home_branch")
            .order_by("first_name", "last_name", "pk")
        )
        return Response(
            [
                {
                    "id": member.pk,
                    "name": str(member),
                    "position": member.position.name if member.position else "",
                    "branch": member.home_branch.name if member.home_branch else "",
                    "photo_url": member.user.photo.url if member.user.photo else None,
                }
                for member in members
            ]
        )

    @extend_schema(request=ReorderSerializer, responses=BranchSerializer(many=True))
    @action(detail=False, methods=["post"])
    def reorder(self, request, company_id):
        serializer = ReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.reorder_branches(
            self.company, by=self.membership, ids=serializer.validated_data["ids"]
        )
        self.bump("companies.branches")
        return Response(BranchSerializer(self.get_queryset(), many=True).data)

    def _fresh(self, branch: Branch) -> dict:
        return BranchSerializer(self.get_queryset().get(pk=branch.pk)).data


# Invite -----------------------------------------------------------------------------------


class InviteSerializer(serializers.Serializer):
    link = serializers.CharField(help_text="Empty while the employee bot has no username.")
    start_param = serializers.CharField()
    bot_username = serializers.CharField()
    company = inline_serializer(
        "CompaniesInviteCompany",
        {"name": serializers.CharField(), "logo": serializers.CharField(allow_null=True)},
    )
    branches = serializers.ListField(child=serializers.CharField())
    members = inline_serializer(
        "CompaniesInviteMembers",
        {"approved": serializers.IntegerField(), "pending": serializers.IntegerField()},
    )


class InviteView(OwnerAPIView):
    """The company's invite link (the QR is drawn in the browser) and the poster's data."""

    perm = Perm.MEMBERS_APPROVE

    @extend_schema(responses=InviteSerializer)
    def get(self, request, company_id):
        return Response(queries.invite(self.company))


class InviteRegenerateView(OwnerAPIView):
    """A new link; the old one and its printed posters stop working at once."""

    perm = Perm.MEMBERS_APPROVE

    @extend_schema(request=None, responses=InviteSerializer)
    def post(self, request, company_id):
        company = services.regenerate_invite(self.company, by=self.membership)
        self.bump("companies.setup")
        return Response(queries.invite(company))


# Get started ------------------------------------------------------------------------------


class SetupStepSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    description = serializers.CharField()
    url = serializers.CharField(help_text="Dashboard path relative to the company.")
    order = serializers.IntegerField()
    done = serializers.BooleanField()


class SetupSerializer(serializers.Serializer):
    steps = SetupStepSerializer(many=True)
    done = serializers.IntegerField()
    total = serializers.IntegerField()
    dismissed = serializers.BooleanField(help_text="Hidden from the sidebar for everyone.")
    can_dismiss = serializers.BooleanField()


def setup_body(member: Membership, company: Company) -> dict:
    steps = registry.collect_setup_steps(member)
    return {
        "steps": steps,
        "done": sum(1 for step in steps if step["done"]),
        "total": len(steps),
        "dismissed": company.setup_completed_at is not None,
        "can_dismiss": member.has_perm(Perm.COMPANY_SETTINGS),
    }


class SetupView(OwnerAPIView):
    """The "Get started" checklist: steps the modules registered, with `done` flags. Steps of
    switched-off modules and steps you can't act on are left out."""

    @extend_schema(responses=SetupSerializer)
    def get(self, request, company_id):
        return Response(setup_body(self.membership, self.company))


class SetupDismissView(OwnerAPIView):
    perm = Perm.COMPANY_SETTINGS

    @extend_schema(request=None, responses=SetupSerializer)
    def post(self, request, company_id):
        company = services.dismiss_setup(self.company, by=self.membership)
        self.bump("companies.setup")
        return Response(setup_body(self.membership, company))


class SetupResumeView(OwnerAPIView):
    perm = Perm.COMPANY_SETTINGS

    @extend_schema(request=None, responses=SetupSerializer)
    def post(self, request, company_id):
        company = services.resume_setup(self.company, by=self.membership)
        self.bump("companies.setup")
        return Response(setup_body(self.membership, company))


# New company (outside a company) ----------------------------------------------------------


class CopySourceSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    parts = serializers.ListField(
        child=serializers.CharField(), help_text="Copy parts you may take from this company."
    )


class CopyPartSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()


class NewCompanyInfoSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(["open", "code", "off"])
    allowed = serializers.BooleanField()
    needs_code = serializers.BooleanField()
    reason = serializers.CharField()
    owned = serializers.IntegerField()
    limit = serializers.IntegerField(allow_null=True, help_text="null: no limit (platform admin).")
    parts = CopyPartSerializer(many=True)
    sources = CopySourceSerializer(many=True)


class NewCompanySerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    timezone = serializers.CharField(max_length=64, default="Asia/Tashkent")
    language = serializers.ChoiceField(Language.choices, default=Language.UZ)
    base_currency = serializers.ChoiceField(Currency.choices, default=Currency.UZS)
    signup_code = serializers.CharField(max_length=32, required=False, allow_blank=True)
    copy_from = serializers.IntegerField(required=False, allow_null=True)
    parts = serializers.ListField(child=serializers.CharField(), required=False, default=list)


class CreatedCompanySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    slug = serializers.CharField()
    copied = serializers.DictField(child=serializers.IntegerField())


def _copy_sources(user) -> list[tuple[Membership, list[str]]]:
    """Companies whose setup `user` may copy, with the parts they may take from each."""
    from apps.console.perms import holds
    from apps.console.queries import owner_memberships

    sources = []
    for member in owner_memberships(user):
        parts = [
            part.key
            for part in registry.COPY_PARTS
            if (part.feature is None or member.company.has_feature(part.feature))
            and holds(member, part.perm)
        ]
        sources.append((member, parts))
    return sources


class NewCompanyInfoView(OwnerUserAPIView):
    """What the "New company" dialog needs: may you create one, with a code or not, and which
    setup you can copy from your other companies."""

    @extend_schema(responses=NewCompanyInfoSerializer)
    def get(self, request):
        from django.conf import settings

        user = request.user
        rules = signup.policy(user)
        owned = len(queries.owned_companies(user))
        limit = None if user.is_platform_admin else settings.MAX_COMPANIES_PER_USER
        allowed = rules.allowed and (limit is None or owned < limit)
        reason = rules.reason
        if rules.allowed and not allowed:
            reason = _("You already own %(count)d companies, the most one person can.") % {
                "count": owned
            }
        return Response(
            {
                "mode": rules.mode,
                "allowed": allowed,
                "needs_code": rules.needs_code,
                "reason": reason,
                "owned": owned,
                "limit": limit,
                "parts": [{"key": p.key, "label": str(p.label)} for p in registry.COPY_PARTS],
                "sources": [
                    {"id": member.company_id, "name": member.company.name, "parts": parts}
                    for member, parts in _copy_sources(user)
                ],
            }
        )


class NewCompanyView(OwnerUserAPIView):
    """Create a company you own (the same path as `/new` in the owner bot), then open its
    "Get started"."""

    @extend_schema(
        request=NewCompanySerializer,
        responses={
            201: CreatedCompanySerializer,
            400: OpenApiResponse(description="Not allowed, bad code or bad input."),
        },
    )
    def post(self, request):
        serializer = NewCompanySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        source = None
        if data.get("copy_from"):
            member = next(
                (
                    m
                    for m, _parts in _copy_sources(request.user)
                    if m.company_id == data["copy_from"]
                ),
                None,
            )
            if member is None:
                raise ValidationError({"copy_from": [_("Pick one of your companies.")]})
            source = member.company
        company, copied = services.create_company_for(
            request.user,
            name=data["name"],
            timezone=data["timezone"],
            language=data["language"],
            base_currency=data["base_currency"],
            signup_code=data.get("signup_code") or None,
            copy_from=source,
            parts=data["parts"] if source else (),
        )
        return Response(
            {"id": company.pk, "name": company.name, "slug": company.slug, "copied": copied},
            status=status.HTTP_201_CREATED,
        )
