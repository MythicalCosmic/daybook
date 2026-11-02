"""Owner dashboard endpoints of HR records (`hr/…`, docs/PLAN-OWNER.md §4.10).

    GET/PATCH  hr/settings/                              warning days, celebrations (hr.manage)
    GET        hr/overview/                              headcount, expiring, probation, birthdays
    GET/PATCH  hr/people/{mid}/profile/                  IDs masked (hr.view / hr.manage)
    GET        hr/people/{mid}/sensitive/                unmasked, audited (hr.sensitive)
    CRUD       hr/people/{mid}/emergency-contacts/       (hr.view / hr.manage)
    CRUD       hr/documents/?member&kind&state&expiring_within&branch&q  (hr.view / hr.manage)
    POST       hr/documents/{id}/verify/                 (hr.manage; an ID needs hr.sensitive)
    GET        hr/documents/compliance/?position&branch  who lacks what
    CRUD       hr/required-documents/                    (hr.view / hr.manage)

Everything is company- and branch-scoped (a person outside the caller's branches answers 404,
like another company's id) and answers 403 while the HR module is off, except the settings.
"""

from datetime import timedelta

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.console.base import OwnerAPIView, OwnerViewSet
from apps.hr import conf, overview, queries, services
from apps.hr import serializers as s
from apps.hr.models import DocumentKind, EmergencyContact, EmployeeDocument, RequiredDocument
from apps.members.models import Membership, Position
from apps.members.permissions import Perm

VIEW, MANAGE, SENSITIVE = Perm.HR_VIEW, Perm.HR_MANAGE, Perm.HR_SENSITIVE
BRANCH_PARAM = OpenApiParameter("branch", int, many=True, description="Branch ids (in scope).")


class ModuleOn:
    """403 while HR is switched off for the company."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not self.company.has_feature("hr"):
            raise PermissionDenied(_("HR isn't switched on for this company."))


class HRContext:
    """What the HR shapes need besides the viewer: today and the warning days."""

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["today"] = queries.today(self.company)
        context["warn_days"] = conf.get_settings(self.company).document_warn_days
        return context

    def person(self, member_id) -> Membership:
        found = queries.person(self.company, member_id, branch_ids=self.branch_scope)
        if found is None:
            raise NotFound
        return found

    def requested_branches(self) -> list[int] | None:
        asked = _ints(self.request.query_params.getlist("branch"), "branch")
        allowed = self.branch_scope
        if not asked:
            return allowed
        return asked if allowed is None else [branch for branch in asked if branch in allowed]


def _ints(values, name: str) -> list[int]:
    try:
        return [int(value) for value in values if str(value).strip()]
    except ValueError as exc:
        raise ValidationError({name: [_("Give a number.")]}) from exc


def _int(value, name: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({name: [_("Give a number.")]}) from exc


# Settings and the overview ---------------------------------------------------------------


class SettingsView(OwnerAPIView):
    """How many days ahead HR is warned, and the celebrations."""

    perm = VIEW
    perms_by_action = {"patch": MANAGE}

    @extend_schema(responses=s.SettingsSerializer)
    def get(self, request, company_id):
        return Response(s.SettingsSerializer(conf.get_settings(self.company)).data)

    @extend_schema(request=s.SettingsSerializer, responses=s.SettingsSerializer)
    def patch(self, request, company_id):
        serializer = s.SettingsSerializer(
            conf.get_settings(self.company), data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        row = services.update_settings(
            self.company, by=self.membership, **serializer.validated_data
        )
        return Response(s.SettingsSerializer(row).data)


class OverviewView(ModuleOn, HRContext, OwnerAPIView):
    """The HR overview page: headcount and its trend, what expires, probations ending,
    birthdays and work anniversaries of the next days."""

    perm = VIEW

    @extend_schema(parameters=[BRANCH_PARAM], responses=overview.OverviewSerializer)
    def get(self, request, company_id):
        data = overview.build(self.company, self.membership, branch_ids=self.requested_branches())
        return Response(
            overview.OverviewSerializer(data, context=self.get_serializer_context()).data
        )


# Profiles ---------------------------------------------------------------------------------


class ProfileView(ModuleOn, HRContext, OwnerAPIView):
    """A person's profile: IDs masked, notes for hr.manage."""

    perm = VIEW
    perms_by_action = {"patch": MANAGE}

    @extend_schema(responses=s.ProfileSerializer)
    def get(self, request, company_id, member_id):
        profile = queries.profile_of(self.person(member_id))
        return Response(s.ProfileSerializer(profile, context=self.get_serializer_context()).data)

    @extend_schema(request=s.ProfileUpdateSerializer, responses=s.ProfileSerializer)
    def patch(self, request, company_id, member_id):
        member = self.person(member_id)
        serializer = s.ProfileUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        profile = services.update_profile(member, by=self.membership, **serializer.validated_data)
        return Response(s.ProfileSerializer(profile, context=self.get_serializer_context()).data)


class SensitiveView(ModuleOn, HRContext, OwnerAPIView):
    """PINFL, passport, card and tax numbers in full. Every call is audited."""

    perm = SENSITIVE

    @extend_schema(responses=s.SensitiveSerializer)
    def get(self, request, company_id, member_id):
        profile = services.reveal(self.person(member_id), by=self.membership)
        response = Response(s.sensitive_payload(profile))
        response["Cache-Control"] = "private, no-store"
        return response


class EmergencyContactViewSet(
    ModuleOn,
    HRContext,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    OwnerViewSet,
):
    """Up to three people to call for someone."""

    perm = VIEW
    perms_by_action = {
        "create": MANAGE,
        "update": MANAGE,
        "partial_update": MANAGE,
        "destroy": MANAGE,
    }
    serializer_class = s.EmergencyContactSerializer
    pagination_class = None
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return EmergencyContact.objects.none()
        member = self.person(self.kwargs["member_id"])
        return EmergencyContact.objects.filter(
            company=self.company, profile__membership=member
        ).select_related("profile__membership__company")

    def perform_create(self, serializer):
        member = self.person(self.kwargs["member_id"])
        serializer.instance = services.add_contact(
            member, by=self.membership, **serializer.validated_data
        )

    def perform_update(self, serializer):
        serializer.instance = services.update_contact(
            serializer.instance, by=self.membership, **serializer.validated_data
        )

    def perform_destroy(self, instance):
        services.remove_contact(instance, by=self.membership)


# Documents --------------------------------------------------------------------------------


class DocumentViewSet(
    ModuleOn,
    HRContext,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    OwnerViewSet,
):
    """Everyone's documents in scope; uploads are multipart (`file`: a PDF or a picture)."""

    perm = VIEW
    perms_by_action = {
        "create": MANAGE,
        "partial_update": MANAGE,
        "destroy": MANAGE,
        "verify": MANAGE,
    }
    serializer_class = s.DocumentSerializer
    parser_classes = (MultiPartParser, FormParser, JSONParser)
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return EmployeeDocument.objects.none()
        rows = queries.documents(self.company, branch_ids=self.branch_scope).select_related(
            "membership__user",
            "membership__position",
            "membership__home_branch",
            "membership__company",
            "uploaded_by",
            "verified_by",
        )
        if self.action != "list":
            return rows
        return self.filtered(rows)

    def filtered(self, rows):
        params = self.request.query_params
        if member := _int(params.get("member"), "member"):
            rows = rows.filter(membership_id=member)
        kinds = [kind for kind in params.getlist("kind") if kind in DocumentKind.values]
        if kinds:
            rows = rows.filter(kind__in=kinds)
        if branches := _ints(params.getlist("branch"), "branch"):
            rows = rows.filter(membership__branches__in=branches).distinct()
        today = queries.today(self.company)
        within = _int(params.get("expiring_within"), "expiring_within")
        if within is not None:
            rows = rows.filter(
                expires_on__isnull=False, expires_on__lte=today + timedelta(days=within)
            )
        warn = conf.get_settings(self.company).document_warn_days
        match params.get("state"):
            case queries.EXPIRED:
                rows = rows.filter(expires_on__lt=today)
            case queries.EXPIRING:
                rows = rows.filter(
                    expires_on__gte=today, expires_on__lte=today + timedelta(days=warn)
                )
            case queries.VALID:
                rows = rows.filter(expires_on__gt=today + timedelta(days=warn))
            case queries.NO_EXPIRY:
                rows = rows.filter(expires_on__isnull=True)
        match params.get("verified"):
            case "true":
                rows = rows.filter(verified_at__isnull=False)
            case "false":
                rows = rows.filter(verified_at__isnull=True)
        if params.get("current") == "true":
            rows = rows.filter(pk__in=queries.latest_documents(rows).values("pk"))
        if q := (params.get("q") or "").strip():
            for word in q.split()[:4]:
                rows = rows.filter(
                    Q(membership__first_name__icontains=word)
                    | Q(membership__last_name__icontains=word)
                    | Q(title__icontains=word)
                )
        ordering = {
            "expires_on": ("expires_on", "pk"),
            "-expires_on": ("-expires_on", "-pk"),
            "created_at": ("created_at", "pk"),
            "-created_at": ("-created_at", "-pk"),
        }.get(params.get("ordering") or "-created_at", ("-created_at", "-pk"))
        return rows.order_by(*ordering)

    @extend_schema(
        parameters=[
            OpenApiParameter("member", int),
            OpenApiParameter("kind", str, many=True),
            OpenApiParameter("state", str, enum=list(queries.DOCUMENT_STATES)),
            OpenApiParameter("expiring_within", int, description="Expires within N days."),
            OpenApiParameter("verified", bool),
            OpenApiParameter("current", bool, description="Only each person's newest per kind."),
            OpenApiParameter("q", str),
            OpenApiParameter(
                "ordering", str, enum=["expires_on", "-expires_on", "created_at", "-created_at"]
            ),
            BRANCH_PARAM,
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=s.DocumentWriteSerializer, responses={201: s.DocumentSerializer})
    def create(self, request, company_id):
        data = self.write_data()
        member = self.person(data.pop("member_id", None))
        kind = data.pop("kind", None)
        if kind is None:
            raise ValidationError({"kind": [_("Pick a kind of document.")]})
        document = services.add_document(member, by=self.membership, kind=kind, **data)
        return Response(
            self.get_serializer(self.reload(document)).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(request=s.DocumentWriteSerializer, responses=s.DocumentSerializer)
    def partial_update(self, request, company_id, pk):
        document = self.get_object()
        data = self.write_data()
        data.pop("member_id", None)
        document = services.update_document(document, by=self.membership, **data)
        return Response(self.get_serializer(self.reload(document)).data)

    def perform_destroy(self, instance):
        services.remove_document(instance, by=self.membership)

    @extend_schema(request=None, responses=s.DocumentSerializer)
    @action(detail=True, methods=["post"])
    def verify(self, request, company_id, pk):
        document = services.verify_document(self.get_object(), by=self.membership)
        return Response(self.get_serializer(self.reload(document)).data)

    @extend_schema(
        parameters=[OpenApiParameter("position", int, many=True), BRANCH_PARAM],
        responses=s.ComplianceSerializer,
    )
    @action(detail=False, methods=["get"])
    def compliance(self, request, company_id):
        found = queries.compliance(
            self.company,
            branch_ids=self.branch_scope,
            day=queries.today(self.company),
            position_ids=_ints(request.query_params.getlist("position"), "position") or None,
            branch=_ints(request.query_params.getlist("branch"), "branch") or None,
        )
        return Response(s.compliance_payload(found))

    def write_data(self) -> dict:
        serializer = s.DocumentWriteSerializer(data=self.request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        if data.get("file") is None:
            data.pop("file", None)
        return data

    def reload(self, document):
        return self.get_queryset().get(pk=document.pk)


class RequiredDocumentViewSet(
    ModuleOn,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    OwnerViewSet,
):
    """Which documents everyone, or everyone in a position, must have."""

    perm = VIEW
    perms_by_action = {
        "create": MANAGE,
        "update": MANAGE,
        "partial_update": MANAGE,
        "destroy": MANAGE,
    }
    serializer_class = s.RequiredDocumentSerializer
    pagination_class = None
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return RequiredDocument.objects.none()
        return RequiredDocument.objects.for_company(self.company).select_related("position")

    def perform_create(self, serializer):
        serializer.instance = self._save(serializer.validated_data)

    def perform_update(self, serializer):
        data = {
            "kind": serializer.instance.kind,
            "position_id": serializer.instance.position_id,
            "level": serializer.instance.level,
            "alternatives": serializer.instance.alternatives,
            **serializer.validated_data,
        }
        serializer.instance = self._save(data, required=serializer.instance)

    def perform_destroy(self, instance):
        services.remove_required(instance, by=self.membership)

    def _save(self, data: dict, required: RequiredDocument | None = None) -> RequiredDocument:
        position = None
        if (position_id := data.get("position_id")) is not None:
            position = get_object_or_404(Position, company=self.company, pk=position_id)
        return services.save_required(
            self.company,
            by=self.membership,
            kind=data["kind"],
            position=position,
            level=data.get("level", ""),
            alternatives=data.get("alternatives", []),
            required=required,
        )
