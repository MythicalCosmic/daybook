"""Owner dashboard endpoints of policies (`hr/…`, docs/PLAN-OWNER.md §4.10).

    GET/POST          hr/policies/?view=active|drafts|archived|all&category&q   (hr.view / manage)
    GET/PATCH/DELETE  hr/policies/{id}/          settings apply at once; delete: never published
    PUT/DELETE        hr/policies/{id}/draft/    the next version (multipart with `file`)
    POST              hr/policies/{id}/publish/  {asks_again, change_note}
    GET               hr/policies/{id}/versions/{number}/        its text and a file link
    GET               hr/policies/{id}/acknowledgements/?state&branch&q    the people grid
    POST              hr/policies/{id}/remind/   {member_ids?}: "Remind now"
    GET               hr/policies/audience/?position&branch      who a choice applies to
    GET               hr/people/{mid}/policies/  a person's policies and signatures (hr.view)

Policies are company documents: hr.view sees the company-wide ones and those of a branch in
scope (another's answers 404, like another company's id); the people behind every number are
branch-scoped. Writing needs hr.manage and a scope that covers the whole policy. Everything
answers 403 while the HR module is off.
"""

from django.db.models import Prefetch, Q
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.console.base import OwnerAPIView, OwnerViewSet
from apps.core.api import Pagination
from apps.hr.models import Policy, PolicyCategory, PolicyVersion
from apps.hr.owner_api import BRANCH_PARAM, HRContext, ModuleOn, _ints
from apps.hr.policies import queries, services
from apps.hr.policies import serializers as s
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import person_ref

VIEW, MANAGE = Perm.HR_VIEW, Perm.HR_MANAGE
AUDIENCE_SHOWN = 6


def _names(company, user_ids) -> dict[int, str]:
    """How the company names the people behind some user ids (who published, who wrote)."""
    ids = {pk for pk in user_ids if pk}
    if not ids:
        return {}
    return {
        member.user_id: str(member)
        for member in Membership.objects.filter(company=company, user_id__in=ids).select_related(
            "user"
        )
    }


class PolicyViewSet(
    ModuleOn,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    OwnerViewSet,
):
    """The company's policies, their drafts and versions, and who has signed them."""

    perm = VIEW
    perms_by_action = {
        "create": MANAGE,
        "partial_update": MANAGE,
        "destroy": MANAGE,
        "draft": MANAGE,
        "publish": MANAGE,
        "remind": MANAGE,
    }
    serializer_class = s.PolicySerializer
    parser_classes = (MultiPartParser, FormParser, JSONParser)
    lookup_value_regex = r"\d+"
    pagination_class = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Policy.objects.none()
        drafts = PolicyVersion.objects.filter(published_at__isnull=True)
        return (
            queries.policies(self.company, branch_ids=self.branch_scope)
            .select_related("current_version", "ack_version", "company")
            .prefetch_related(
                "positions", "branches", Prefetch("versions", queryset=drafts, to_attr="drafts")
            )
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["today"] = queries.today(self.company)
        return context

    def context_for(self, rows: list[Policy]) -> dict:
        context = self.get_serializer_context()
        context["tallies"] = queries.tallies(
            [row for row in rows if row.is_active],
            branch_ids=self.branch_scope,
            day=context["today"],
        )
        return context

    def detail(self, policy: Policy) -> dict:
        policy = self.get_queryset().get(pk=policy.pk)
        context = self.context_for([policy])
        users = [policy.created_by_id, *policy.versions.values_list("published_by_id", flat=True)]
        context["names"] = _names(self.company, users)
        return s.PolicyDetailSerializer(policy, context=context).data

    def valid(self, serializer_class, *, partial=True) -> dict:
        serializer = serializer_class(data=self.request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        return dict(serializer.validated_data)

    # Policies --------------------------------------------------------------------------------

    @extend_schema(
        parameters=[
            OpenApiParameter("view", str, enum=[*queries.VIEWS, "all"]),
            OpenApiParameter("category", str, many=True, enum=PolicyCategory.values),
            OpenApiParameter("q", str),
        ],
        responses=s.PolicySerializer(many=True),
    )
    def list(self, request, *args, **kwargs):
        rows = self.get_queryset()
        view = request.query_params.get("view") or queries.ACTIVE
        if view in queries.VIEWS:
            rows = queries.view_filter(rows, view)
        categories = [
            value
            for value in request.query_params.getlist("category")
            if value in PolicyCategory.values
        ]
        if categories:
            rows = rows.filter(category__in=categories)
        for word in (request.query_params.get("q") or "").split()[:4]:
            rows = rows.filter(
                Q(title__icontains=word) | Q(current_version__body_text__icontains=word)
            )
        rows = list(rows.order_by("title", "pk"))
        return Response(s.PolicySerializer(rows, many=True, context=self.context_for(rows)).data)

    @extend_schema(responses=s.PolicyDetailSerializer)
    def retrieve(self, request, *args, **kwargs):
        return Response(self.detail(self.get_object()))

    @extend_schema(request=s.PolicyWriteSerializer, responses={201: s.PolicyDetailSerializer})
    def create(self, request, company_id):
        data = self.valid(s.PolicyWriteSerializer, partial=False)
        if not (data.get("title") or "").strip():
            raise ValidationError({"title": [_("Give the policy a title.")]})
        data.pop("is_active", None)
        policy = services.create_policy(self.company, by=self.membership, **data)
        return Response(self.detail(policy), status=status.HTTP_201_CREATED)

    @extend_schema(request=s.PolicyWriteSerializer, responses=s.PolicyDetailSerializer)
    def partial_update(self, request, company_id, pk):
        policy = self.get_object()
        data = self.valid(s.PolicyWriteSerializer)
        data.pop("body", None)
        data.pop("change_note", None)
        policy = services.update_policy(policy, by=self.membership, **data)
        return Response(self.detail(policy))

    def perform_destroy(self, instance):
        services.delete_policy(instance, by=self.membership)

    # Drafts, publishing, versions -------------------------------------------------------------

    @extend_schema(
        methods=["PUT"], request=s.DraftWriteSerializer, responses=s.VersionDetailSerializer
    )
    @extend_schema(methods=["DELETE"], request=None, responses={204: None})
    @action(detail=True, methods=["put", "delete"])
    def draft(self, request, company_id, pk):
        policy = self.get_object()
        if request.method == "DELETE":
            services.discard_draft(policy, by=self.membership)
            return Response(status=status.HTTP_204_NO_CONTENT)
        data = self.valid(s.DraftWriteSerializer)
        fields = {name: data[name] for name in ("body", "change_note") if name in data}
        version = services.save_draft(
            policy,
            by=self.membership,
            file=data.get("file"),
            remove_file=data.get("remove_file", False),
            **fields,
        )
        version = PolicyVersion.objects.select_related("policy", "published_by").get(pk=version.pk)
        context = self.get_serializer_context()
        return Response(s.VersionDetailSerializer(version, context=context).data)

    @extend_schema(request=s.PublishSerializer, responses=s.PolicyDetailSerializer)
    @action(detail=True, methods=["post"])
    def publish(self, request, company_id, pk):
        policy = self.get_object()
        data = self.valid(s.PublishSerializer, partial=False)
        fields = {"change_note": data["change_note"]} if "change_note" in data else {}
        services.publish(
            policy, by=self.membership, asks_again=data.get("asks_again", True), **fields
        )
        return Response(self.detail(policy))

    @extend_schema(
        parameters=[OpenApiParameter("number", int, OpenApiParameter.PATH)],
        responses=s.VersionDetailSerializer,
    )
    @action(detail=True, methods=["get"], url_path=r"versions/(?P<number>\d+)")
    def version(self, request, company_id, pk, number):
        policy = self.get_object()
        found = (
            policy.versions.select_related("policy", "published_by").filter(number=number).first()
        )
        if found is None:
            raise NotFound
        context = self.get_serializer_context()
        context["names"] = _names(self.company, [found.published_by_id])
        return Response(s.VersionDetailSerializer(found, context=context).data)

    # Who signed --------------------------------------------------------------------------------

    @extend_schema(
        parameters=[
            OpenApiParameter("state", str, enum=[*queries.STATES]),
            OpenApiParameter("q", str),
            OpenApiParameter("page", int),
            OpenApiParameter("page_size", int),
            BRANCH_PARAM,
        ],
        responses=s.SignatureSerializer(many=True),
    )
    @action(detail=True, methods=["get"])
    def acknowledgements(self, request, company_id, pk):
        policy = self.get_object()
        day = queries.today(self.company)
        rows = queries.grid(policy, branch_ids=self.branch_scope)
        rows = queries.with_state(rows, request.query_params.get("state"), day)
        if branches := _ints(request.query_params.getlist("branch"), "branch"):
            rows = rows.filter(membership__branches__in=branches).distinct()
        for word in (request.query_params.get("q") or "").split()[:4]:
            rows = rows.filter(
                Q(membership__first_name__icontains=word) | Q(membership__last_name__icontains=word)
            )
        paginator = Pagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        earlier = queries.earlier_signatures(policy, [row.membership_id for row in page])
        data = [s.signature_payload(row, day, earlier) for row in page]
        return paginator.get_paginated_response(s.SignatureSerializer(data, many=True).data)

    @extend_schema(request=s.RemindSerializer, responses=s.RemindedSerializer)
    @action(detail=True, methods=["post"])
    def remind(self, request, company_id, pk):
        policy = self.get_object()
        data = self.valid(s.RemindSerializer, partial=False)
        count = services.remind(policy, by=self.membership, member_ids=data.get("member_ids"))
        return Response({"reminded": count})

    @extend_schema(
        parameters=[OpenApiParameter("position", int, many=True), BRANCH_PARAM],
        responses=s.AudienceSerializer,
    )
    @action(detail=False, methods=["get"])
    def audience(self, request, company_id):
        """Who a choice of positions and branches applies to (the editor's live count)."""
        position_ids = _ints(request.query_params.getlist("position"), "position")
        branch_ids = _ints(request.query_params.getlist("branch"), "branch")
        rows = queries.audience_of(
            self.company.pk, position_ids=position_ids, branch_ids=branch_ids
        )
        shown = rows
        if self.branch_scope is not None:
            shown = rows.filter(
                pk__in=Membership.objects.filter(branches__in=self.branch_scope).values("pk")
            )
        people = shown.select_related("user").order_by("first_name", "last_name", "pk")
        return Response(
            {
                "count": rows.count(),
                "people": [person_ref(member) for member in people[:AUDIENCE_SHOWN]],
            }
        )


class PersonPoliciesView(ModuleOn, HRContext, OwnerAPIView):
    """Person 360's HR tab: the policies that apply to the person and where they stand, and
    every signature they gave (earlier versions too)."""

    perm = VIEW

    @extend_schema(responses=s.PersonPoliciesSerializer)
    def get(self, request, company_id, member_id):
        member = self.person(member_id)
        day = queries.today(self.company)
        visible = set(
            queries.policies(self.company, branch_ids=self.branch_scope).values_list(
                "pk", flat=True
            )
        )
        current = [
            s.standing_payload(item)
            for item in queries.mine(member, day)
            if item.policy.pk in visible
        ]
        history = [
            {
                "policy": s.policy_ref(row.version.policy),
                "number": row.version.number,
                "signed_number": row.signed_version.number if row.signed_version else None,
                "signed_at": row.acknowledged_at,
            }
            for row in queries.history(member)
            if row.version.policy_id in visible
        ]
        return Response({"current": current, "history": history})
