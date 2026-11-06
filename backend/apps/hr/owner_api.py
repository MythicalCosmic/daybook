"""Owner dashboard endpoints of HR records (`hr/…`, docs/PLAN-OWNER.md §4.10).

    GET/PATCH  hr/settings/                              warning days, celebrations, coverage
                                                         (hr.manage)
    GET        hr/overview/                              headcount, expiring, probation, birthdays
    GET        hr/coverage/?from&to&branch&drafts        pharmacist coverage (hr.view or
                                                         attendance.view)
    GET        hr/coverage/live/                         pharmacies without one checked in now
    GET/POST   hr/coverage/pharmacists/                  who counts as a pharmacist (hr.manage)
    GET/PATCH  hr/people/{mid}/profile/                  IDs masked (hr.view / hr.manage)
    GET        hr/people/{mid}/sensitive/                unmasked, audited (hr.sensitive)
    CRUD       hr/people/{mid}/emergency-contacts/       (hr.view / hr.manage)
    CRUD       hr/documents/?member&kind&state&expiring_within&branch&q  (hr.view / hr.manage)
    POST       hr/documents/{id}/verify/                 (hr.manage; an ID needs hr.sensitive)
    GET        hr/documents/compliance/?position&branch  who lacks what
    CRUD       hr/required-documents/                    (hr.view / hr.manage)
    CRUD       hr/contract-templates/  ·  POST …/{id}/preview/ · …/preview/  ·  GET …/placeholders/
    CRUD       hr/contracts/?status&kind&member&ending_within&probation_within&q  (hr.view / manage)
    POST       hr/contracts/{id}/activate|terminate|end|renew|pass-probation|extend-probation|
               generate-pdf/                             (hr.manage)

Everything is company- and branch-scoped (a person outside the caller's branches answers 404,
like another company's id) and answers 403 while the HR module is off, except the settings.
"""

from datetime import date, timedelta

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.console.base import AnyOf, OwnerAPIView, OwnerViewSet
from apps.hr import conf, coverage, overview, printing, queries, services
from apps.hr import serializers as s
from apps.hr.models import (
    Contract,
    ContractKind,
    ContractTemplate,
    DocumentKind,
    EmergencyContact,
    EmployeeDocument,
    RequiredDocument,
)
from apps.members.models import Membership, Position
from apps.members.permissions import Perm
from apps.members.queries import branch_ref, person_ref

VIEW, MANAGE, SENSITIVE = Perm.HR_VIEW, Perm.HR_MANAGE, Perm.HR_SENSITIVE
# The coverage pages are HR's and the roster's (whoever runs attendance reads them too).
COVERAGE_VIEW = AnyOf(Perm.HR_VIEW, Perm.ATTENDANCE_VIEW)
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
        # Every row these views show comes from a query limited to the viewer's branches.
        context["in_scope"] = True
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


class CelebrationsView(ModuleOn, HRContext, OwnerAPIView):
    """Birthdays (of people who show theirs) and work anniversaries between two days: this
    month by default, a year at most."""

    perm = VIEW

    @extend_schema(
        parameters=[
            OpenApiParameter("from", str, description="YYYY-MM-DD; the 1st of this month."),
            OpenApiParameter("to", str, description="YYYY-MM-DD; the month's last day."),
            BRANCH_PARAM,
        ],
        responses=overview.CelebrationSerializer(many=True),
    )
    def get(self, request, company_id):
        today = queries.today(self.company)
        start = _day(request.query_params.get("from"), "from", today.replace(day=1))
        end = _day(request.query_params.get("to"), "to", overview.month_end(start))
        if end < start or (end - start).days > 366:
            raise ValidationError({"to": [_("Pick at most a year, ending after it starts.")]})
        people = queries.people(self.company, branch_ids=self.requested_branches())
        rows = overview.celebrations_between(
            self.company, people.select_related("user"), start, end
        )
        for row in rows:
            row["days_until"] = (row["date"] - today).days
        return Response(overview.CelebrationSerializer(rows, many=True).data)


def _day(value, name: str, default):
    if not value:
        return default
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError({name: [_("Give a day as YYYY-MM-DD.")]}) from exc


# Pharmacist coverage (docs/PLAN-OWNER.md §14.9) ------------------------------------------


class CoverageView(ModuleOn, HRContext, OwnerAPIView):
    """A period of every pharmacy in scope: its open hours, the pharmacists planned and the
    gaps with fewer qualified pharmacists than it needs. A week from today by default, 62 days
    at most. Drafts count only for whoever may see them (attendance.manage)."""

    perm = COVERAGE_VIEW

    @extend_schema(
        parameters=[
            OpenApiParameter("from", str, description="YYYY-MM-DD; today."),
            OpenApiParameter("to", str, description="YYYY-MM-DD; six days after `from`."),
            OpenApiParameter("drafts", bool, description="Count unpublished shifts (the roster)."),
            BRANCH_PARAM,
        ],
        responses=s.CoverageSerializer,
    )
    def get(self, request, company_id):
        today = queries.today(self.company)
        start = _day(request.query_params.get("from"), "from", today)
        end = _day(request.query_params.get("to"), "to", start + timedelta(days=6))
        if end < start or (end - start).days >= coverage.MAX_DAYS:
            raise ValidationError({"to": [_("Pick at most 62 days, ending after it starts.")]})
        drafts = request.query_params.get("drafts") in ("true", "1") and self.membership.has_perm(
            Perm.ATTENDANCE_MANAGE
        )
        found = coverage.plan(
            self.company, start, end, branch_ids=self.requested_branches(), drafts=drafts
        )
        return Response(
            s.coverage_payload(found, drafts=drafts, reasons=self.membership.has_perm(Perm.HR_VIEW))
        )


class LiveCoverageView(ModuleOn, OwnerAPIView):
    """Pharmacies in scope open now with fewer qualified pharmacists checked in than they need."""

    perm = COVERAGE_VIEW

    @extend_schema(responses=s.LiveCoverageSerializer)
    def get(self, request, company_id):
        now = timezone.now()
        scope_ids = self.branch_scope
        branches = {
            branch.pk: branch for branch in coverage.pharmacies(self.company, branch_ids=scope_ids)
        }
        gaps = [gap for gap in coverage.live(self.company, now) if gap.branch_id in branches]
        people = {
            member.pk: member
            for member in Membership.objects.filter(
                pk__in={pk for gap in gaps for pk in gap.others}
            ).select_related("user")
        }
        return Response(
            {
                "state": coverage.state(self.company),
                "at": now,
                "gaps": [
                    {
                        "branch": branch_ref(branches[gap.branch_id]),
                        "since": gap.since,
                        "minutes": int((now - gap.since).total_seconds() // 60),
                        "have": gap.have,
                        "need": gap.need,
                        "checked_in": [person_ref(people[pk]) for pk in gap.others if pk in people],
                    }
                    for gap in gaps
                ],
            }
        )


class PharmacistsView(ModuleOn, OwnerAPIView):
    """Who counts as a pharmacist on duty: each position, whether it does (and as what), and
    the documents it asks for. Saving chooses them (the setup step hr.pharmacists)."""

    perm = VIEW
    perms_by_action = {"post": MANAGE}

    @extend_schema(responses=s.PharmacistsSerializer)
    def get(self, request, company_id):
        return Response(self.payload())

    @extend_schema(request=s.PharmacistsWriteSerializer, responses=s.PharmacistsSerializer)
    def post(self, request, company_id):
        serializer = s.PharmacistsWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        chosen = serializer.validated_data["positions"]
        found = {
            position.pk: position
            for position in Position.objects.filter(
                company=self.company, pk__in=[row["id"] for row in chosen]
            )
        }
        if len(found) != len({row["id"] for row in chosen}):
            raise ValidationError({"positions": [_("Pick a position of this company.")]})
        services.set_pharmacists(
            self.company,
            by=self.membership,
            roles={found[row["id"]]: row["role"] for row in chosen},
        )
        return Response(self.payload())

    def payload(self) -> dict:
        settings = conf.get_settings(self.company)
        chosen = conf.pharmacist_position_ids(settings)
        required = queries.required_for(self.company)
        rows = []
        positions = (
            Position.objects.filter(company=self.company)
            .filter(Q(is_active=True) | Q(pk__in=chosen))
            .annotate(
                people=Count(
                    "members", filter=Q(members__status__in=queries.CURRENT), distinct=True
                )
            )
            .order_by("order", "name", "pk")
        )
        for position in positions:
            documents = required.get(position.pk, [])
            role = None
            if position.pk in chosen:
                role = services.standard_role(documents) or services.CUSTOM
            rows.append(
                {
                    "position": {"id": position.pk, "name": position.name},
                    "role": role,
                    "people": position.people,
                    "required": [
                        {"kind": row.kind, "level": row.level, "alternatives": row.alternatives}
                        for row in documents
                    ],
                }
            )
        return {"positions": rows}


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


# Contract templates -----------------------------------------------------------------------


class ContractTemplateViewSet(
    ModuleOn,
    HRContext,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    OwnerViewSet,
):
    """The company's contract texts with {{placeholders}}, and a live preview for a person."""

    perm = MANAGE
    serializer_class = s.ContractTemplateSerializer
    pagination_class = None
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ContractTemplate.objects.none()
        return ContractTemplate.objects.for_company(self.company).annotate(
            contracts_count=Count("contracts")
        )

    def perform_create(self, serializer):
        serializer.instance = services.save_template(
            self.company, by=self.membership, **serializer.validated_data
        )

    def perform_update(self, serializer):
        template = serializer.instance
        data = {
            "name": template.name,
            "body": template.body,
            "kind": template.kind,
            "language": template.language,
            "is_active": template.is_active,
            **serializer.validated_data,
        }
        serializer.instance = services.save_template(
            self.company, by=self.membership, template=template, **data
        )

    def perform_destroy(self, instance):
        services.remove_template(instance, by=self.membership)

    @extend_schema(request=s.PreviewRequestSerializer, responses=s.PreviewSerializer)
    @action(detail=True, methods=["post"])
    def preview(self, request, company_id, pk):
        return self._preview(self.get_object())

    @extend_schema(
        operation_id="companies_hr_contract_templates_preview_unsaved",
        request=s.PreviewRequestSerializer,
        responses=s.PreviewSerializer,
        description="Preview text that isn't saved yet (`body` is required).",
    )
    @action(detail=False, methods=["post"], url_path="preview")
    def preview_new(self, request, company_id):
        if "body" not in request.data:
            raise ValidationError({"body": [_("Write the contract's text.")]})
        language = request.data.get("language") or self.company.default_language
        return self._preview(ContractTemplate(company=self.company, language=language, body=""))

    @extend_schema(responses=s.PlaceholdersSerializer)
    @action(detail=False, methods=["get"])
    def placeholders(self, request, company_id):
        return Response({"placeholders": list(printing.PLACEHOLDERS)})

    def _preview(self, template: ContractTemplate) -> Response:
        serializer = s.PreviewRequestSerializer(data=self.request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        member = None
        if data.get("member_id") is not None:
            member = self.person(data["member_id"])
        if data.get("language"):
            template.language = data["language"]
        filled = services.preview(
            template, by=self.membership, membership=member, body=data.get("body")
        )
        return Response(
            {"html": filled.html, "empty": list(filled.empty), "has_salary": filled.has_salary}
        )


# Contracts --------------------------------------------------------------------------------


class ContractViewSet(
    ModuleOn,
    HRContext,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    OwnerViewSet,
):
    """Everyone's contracts in scope, and what happens to them: signing, ending,
    terminating, renewing, probation, the PDF from a template."""

    perm = VIEW
    perms_by_action = {
        "create": MANAGE,
        "partial_update": MANAGE,
        "destroy": MANAGE,
        "activate": MANAGE,
        "terminate": MANAGE,
        "end": MANAGE,
        "renew": MANAGE,
        "pass_probation": MANAGE,
        "extend_probation": MANAGE,
        "generate_pdf": MANAGE,
    }
    serializer_class = s.ContractSerializer
    parser_classes = (MultiPartParser, FormParser, JSONParser)
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Contract.objects.none()
        rows = queries.contracts(self.company, branch_ids=self.branch_scope).select_related(
            "membership__user",
            "membership__home_branch",
            "membership__company",
            "position",
            "template",
            "created_by",
        )
        if self.action != "list":
            return rows
        return self.filtered(rows)

    def filtered(self, rows):
        params = self.request.query_params
        statuses = [value for value in params.getlist("status") if value in Contract.Status.values]
        if statuses:
            rows = rows.filter(status__in=statuses)
        kinds = [value for value in params.getlist("kind") if value in ContractKind.values]
        if kinds:
            rows = rows.filter(kind__in=kinds)
        if member := _int(params.get("member"), "member"):
            rows = rows.filter(membership_id=member)
        if branches := _ints(params.getlist("branch"), "branch"):
            rows = rows.filter(membership__branches__in=branches).distinct()
        today = queries.today(self.company)
        if (within := _int(params.get("ending_within"), "ending_within")) is not None:
            rows = rows.filter(
                status=Contract.Status.ACTIVE,
                ends_on__isnull=False,
                ends_on__lte=today + timedelta(days=within),
            )
        if (within := _int(params.get("probation_within"), "probation_within")) is not None:
            rows = rows.filter(
                status=Contract.Status.ACTIVE,
                probation_until__isnull=False,
                probation_passed_at__isnull=True,
                probation_until__lte=today + timedelta(days=within),
            )
        match params.get("acknowledged"):
            case "true":
                rows = rows.filter(acknowledged_at__isnull=False)
            case "false":
                rows = rows.filter(acknowledged_at__isnull=True)
        if q := (params.get("q") or "").strip():
            for word in q.split()[:4]:
                rows = rows.filter(
                    Q(membership__first_name__icontains=word)
                    | Q(membership__last_name__icontains=word)
                    | Q(number__icontains=word)
                )
        ordering = {
            "starts_on": ("starts_on", "pk"),
            "-starts_on": ("-starts_on", "-pk"),
            "ends_on": ("ends_on", "pk"),
            "-ends_on": ("-ends_on", "-pk"),
        }.get(params.get("ordering") or "-starts_on", ("-starts_on", "-pk"))
        return rows.order_by(*ordering)

    @extend_schema(
        parameters=[
            OpenApiParameter("status", str, many=True, enum=list(Contract.Status.values)),
            OpenApiParameter("kind", str, many=True, enum=list(ContractKind.values)),
            OpenApiParameter("member", int),
            OpenApiParameter("ending_within", int, description="In force, ends within N days."),
            OpenApiParameter("probation_within", int, description="Probation ends within N days."),
            OpenApiParameter("acknowledged", bool),
            OpenApiParameter("q", str),
            OpenApiParameter(
                "ordering", str, enum=["starts_on", "-starts_on", "ends_on", "-ends_on"]
            ),
            BRANCH_PARAM,
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=s.ContractWriteSerializer, responses={201: s.ContractSerializer})
    def create(self, request, company_id):
        data = self.write_data()
        member = self.person(data.pop("member_id", None))
        if data.get("starts_on") is None:
            raise ValidationError({"starts_on": [_("Give the first day of the contract.")]})
        contract = services.create_contract(member, by=self.membership, **data)
        return Response(
            self.get_serializer(self.reload(contract)).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(request=s.ContractWriteSerializer, responses=s.ContractSerializer)
    def partial_update(self, request, company_id, pk):
        contract = self.get_object()
        data = self.write_data()
        data.pop("member_id", None)
        contract = services.update_contract(contract, by=self.membership, **data)
        return Response(self.get_serializer(self.reload(contract)).data)

    def perform_destroy(self, instance):
        services.delete_contract(instance, by=self.membership)

    @extend_schema(request=None, responses=s.ContractSerializer)
    @action(detail=True, methods=["post"])
    def activate(self, request, company_id, pk):
        contract = services.activate_contract(self.get_object(), by=self.membership)
        return Response(self.get_serializer(self.reload(contract)).data)

    @extend_schema(request=s.TerminateSerializer, responses=s.ContractSerializer)
    @action(detail=True, methods=["post"])
    def terminate(self, request, company_id, pk):
        contract = self.get_object()
        data = self.valid(s.TerminateSerializer)
        contract = services.terminate_contract(contract, by=self.membership, **data)
        return Response(self.get_serializer(self.reload(contract)).data)

    @extend_schema(request=s.EndSerializer, responses=s.ContractSerializer)
    @action(detail=True, methods=["post"])
    def end(self, request, company_id, pk):
        contract = self.get_object()
        data = self.valid(s.EndSerializer)
        contract = services.end_contract(contract, by=self.membership, **data)
        return Response(self.get_serializer(self.reload(contract)).data)

    @extend_schema(request=s.RenewSerializer, responses={201: s.ContractSerializer})
    @action(detail=True, methods=["post"])
    def renew(self, request, company_id, pk):
        contract = self.get_object()
        data = self.valid(s.RenewSerializer)
        renewed = services.renew_contract(
            contract,
            by=self.membership,
            ends_on=data.get("ends_on"),
            starts_on=data.get("starts_on"),
            kind=data.get("kind"),
        )
        return Response(
            self.get_serializer(self.reload(renewed)).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(request=None, responses=s.ContractSerializer)
    @action(detail=True, methods=["post"], url_path="pass-probation")
    def pass_probation(self, request, company_id, pk):
        contract = services.pass_probation(self.get_object(), by=self.membership)
        return Response(self.get_serializer(self.reload(contract)).data)

    @extend_schema(request=s.ExtendProbationSerializer, responses=s.ContractSerializer)
    @action(detail=True, methods=["post"], url_path="extend-probation")
    def extend_probation(self, request, company_id, pk):
        contract = self.get_object()
        data = self.valid(s.ExtendProbationSerializer)
        contract = services.extend_probation(contract, by=self.membership, until=data["until"])
        return Response(self.get_serializer(self.reload(contract)).data)

    @extend_schema(request=s.GeneratePdfSerializer, responses=s.ContractSerializer)
    @action(detail=True, methods=["post"], url_path="generate-pdf")
    def generate_pdf(self, request, company_id, pk):
        contract = self.get_object()
        data = self.valid(s.GeneratePdfSerializer)
        template = None
        if data.get("template_id") is not None:
            template = self.template(data["template_id"])
        contract = services.generate_pdf(contract, by=self.membership, template=template)
        return Response(self.get_serializer(self.reload(contract)).data)

    def valid(self, serializer_class) -> dict:
        serializer = serializer_class(data=self.request.data)
        serializer.is_valid(raise_exception=True)
        return dict(serializer.validated_data)

    def template(self, template_id) -> ContractTemplate:
        found = ContractTemplate.objects.filter(company=self.company, pk=template_id).first()
        if found is None:
            raise ValidationError({"template_id": [_("Pick a contract template.")]})
        return found

    def write_data(self) -> dict:
        data = self.valid(s.ContractWriteSerializer)
        if data.get("file") is None:
            data.pop("file", None)
        if "position_id" in data:
            position_id = data.pop("position_id")
            data["position"] = (
                get_object_or_404(Position, company=self.company, pk=position_id)
                if position_id is not None
                else None
            )
        if "template_id" in data:
            template_id = data.pop("template_id")
            data["template"] = self.template(template_id) if template_id is not None else None
        return data

    def reload(self, contract: Contract) -> Contract:
        return self.get_queryset().get(pk=contract.pk)
