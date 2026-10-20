"""Owner dashboard endpoints of people, join requests, roles and positions; routed in
`owner_urls.py` (docs/PLAN-OWNER.md §4.6).

    GET    people/                    the team directory (branch-scoped, up to 500 per page)
    GET    people/{id}/               Person 360: details, numbers and what you may do
    PATCH  people/{id}/               name, position, branches, home branch; role (roles.manage)
    POST   people/{id}/block/ · unblock/ · suspend/ · reinstate/
    GET    people/{id}/offboard-preview/  ·  POST people/{id}/offboard/
    GET    people/{id}/history/       audit rows about them and their time off
    GET    join-requests/  ·  POST join-requests/{id}/approve/ · reject/
    CRUD   roles/  ·  CRUD positions/  ·  POST positions/reorder/
"""

from datetime import timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import (
    OpenApiParameter,
    extend_schema,
    extend_schema_field,
    inline_serializer,
)
from rest_framework import mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from apps.audit import queries as audit_queries
from apps.audit.models import AuditLog
from apps.companies.models import Branch
from apps.console import registry
from apps.console.base import AnyOf, OwnerViewSet
from apps.core.api import Pagination
from apps.members import queries, scope, services
from apps.members.models import AccessRole, Membership, Position
from apps.members.permissions import Perm
from apps.members.queries import branch_ref, photo_url

PEOPLE = "members.people"


class PeoplePagination(Pagination):
    # Pickers load the whole team at once (a business has tens or a few hundred people).
    max_page_size = 500


# Shapes ----------------------------------------------------------------------------------


class NamedSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class BranchRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    code = serializers.CharField()


class RoleRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    is_owner = serializers.BooleanField()


class PersonSerializer(serializers.ModelSerializer):
    """A row of the team directory."""

    name = serializers.SerializerMethodField()
    full_name = serializers.SerializerMethodField()
    photo_url = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    username = serializers.SerializerMethodField()
    position = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    home_branch = serializers.SerializerMethodField()
    branches = serializers.SerializerMethodField()
    joined_on = serializers.SerializerMethodField()
    left_on = serializers.SerializerMethodField()
    onboarded = serializers.SerializerMethodField()
    bot_blocked = serializers.SerializerMethodField()
    work = serializers.SerializerMethodField()
    fields = serializers.SerializerMethodField(
        method_name="get_extra",
        help_text="Fields other modules add (attendance_today, attendance_30d, salary with "
        "payroll.view, time_off_today…); absent without their permission.",
    )

    class Meta:
        model = Membership
        fields = (
            "id",
            "name",
            "full_name",
            "first_name",
            "last_name",
            "photo_url",
            "phone",
            "username",
            "position",
            "role",
            "home_branch",
            "branches",
            "status",
            "suspended_until",
            "joined_on",
            "left_on",
            "onboarded",
            "bot_blocked",
            "work",
            "fields",
        )
        read_only_fields = fields

    def get_name(self, person: Membership) -> str:
        return str(person)

    def get_full_name(self, person: Membership) -> str:
        return str(person)

    def get_photo_url(self, person: Membership) -> str | None:
        return photo_url(person)

    def get_phone(self, person: Membership) -> str:
        return person.user.phone or ""

    def get_username(self, person: Membership) -> str:
        return person.user.telegram_username or ""

    @extend_schema_field(NamedSerializer(allow_null=True))
    def get_position(self, person: Membership) -> dict | None:
        return {"id": person.position.pk, "name": person.position.name} if person.position else None

    @extend_schema_field(RoleRefSerializer(allow_null=True))
    def get_role(self, person: Membership) -> dict | None:
        role = person.role
        return {"id": role.pk, "name": role.name, "is_owner": role.is_owner} if role else None

    @extend_schema_field(BranchRefSerializer(allow_null=True))
    def get_home_branch(self, person: Membership) -> dict | None:
        return branch_ref(person.home_branch)

    @extend_schema_field(BranchRefSerializer(many=True))
    def get_branches(self, person: Membership) -> list[dict]:
        return [branch_ref(b) for b in sorted(person.branches.all(), key=lambda b: (b.order, b.pk))]

    def get_joined_on(self, person: Membership) -> str | None:
        """Their first day (the employment-dates contract); when they asked, for a request."""
        dates = self.context.get("dates", {}).get(person.pk)
        if dates is not None:
            return dates[0].isoformat()
        asked = person.onboarded_at or person.created_at
        tz = ZoneInfo(self.context["company"].timezone)
        return timezone.localtime(asked, tz).date().isoformat() if asked else None

    def get_left_on(self, person: Membership) -> str | None:
        """Their last day, for someone who left or was blocked."""
        dates = self.context.get("dates", {}).get(person.pk)
        return dates[1].isoformat() if dates is not None and dates[1] else None

    def get_onboarded(self, person: Membership) -> bool:
        return person.onboarded_at is not None

    def get_bot_blocked(self, person: Membership) -> bool:
        return person.user.employee_bot_blocked_at is not None

    @extend_schema_field(
        inline_serializer(
            "MembersWork",
            {
                "on_time_30d": serializers.CharField(allow_null=True),
                "done_30d": serializers.IntegerField(),
                "late_now": serializers.IntegerField(),
                "open_now": serializers.IntegerField(),
            },
        )
    )
    def get_work(self, person: Membership) -> dict:
        return self.context.get("work", {}).get(
            person.pk, {"on_time_30d": None, "done_30d": 0, "late_now": 0, "open_now": 0}
        )

    @extend_schema_field(serializers.DictField())
    def get_extra(self, person: Membership) -> dict:
        return self.context.get("fields", {}).get(person.pk, {})


class PersonDetailSerializer(PersonSerializer):
    language = serializers.SerializerMethodField()
    overview = serializers.SerializerMethodField()
    can = serializers.SerializerMethodField()

    class Meta(PersonSerializer.Meta):
        fields = (
            *PersonSerializer.Meta.fields,
            "language",
            "overview",
            "can",
        )
        read_only_fields = fields

    def get_language(self, person: Membership) -> str:
        return person.user.language

    @extend_schema_field(serializers.DictField())
    def get_overview(self, person: Membership) -> dict:
        return self.context.get("overview", {})

    @extend_schema_field(serializers.DictField(child=serializers.BooleanField()))
    def get_can(self, person: Membership) -> dict:
        return allowed_actions(self.context["membership"], person)


def allowed_actions(viewer: Membership, person: Membership) -> dict[str, bool]:
    """What `viewer` may do to `person` in Person 360 (the server checks again on each)."""
    current = person.status in queries.CURRENT
    is_self = viewer.pk == person.pk
    person_is_owner = bool(person.role and person.role.is_owner)
    viewer_is_owner = bool(viewer.role and viewer.role.is_owner)
    may_touch_owner = viewer_is_owner or not person_is_owner
    manage = viewer.has_perm(Perm.MEMBERS_MANAGE) and may_touch_owner
    # Rule 2 both ways: a non-owner moves someone only out of a role they could have given.
    role_ok = person.role is None or services.may_assign_role(viewer, person.role, target=person)
    return {
        "edit": manage and current,
        "change_role": viewer.has_perm(Perm.ROLES_MANAGE) and current and role_ok,
        "block": manage and not is_self and person.status != Membership.Status.BLOCKED,
        "unblock": manage and person.status == Membership.Status.BLOCKED,
        "offboard": manage and current and not is_self,
        "suspend": viewer.has_perm(Perm.HR_SUSPEND)
        and may_touch_owner
        and not is_self
        and person.status == Membership.Status.APPROVED,
        "reinstate": viewer.has_perm(Perm.HR_SUSPEND)
        and may_touch_owner
        and person.status == Membership.Status.SUSPENDED,
        "record_time_off": viewer.has_perm(Perm.TIME_OFF_APPROVE)
        and person.status == Membership.Status.APPROVED,
    }


class PersonUpdateSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=100, required=False)
    last_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    position_id = serializers.IntegerField(required=False, allow_null=True)
    branch_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    home_branch_id = serializers.IntegerField(required=False, allow_null=True)
    role_id = serializers.IntegerField(required=False)


class SuspendSerializer(serializers.Serializer):
    until = serializers.DateField(required=False, allow_null=True)
    reason = serializers.CharField(max_length=300)


class OffboardSerializer(serializers.Serializer):
    terminated_on = serializers.DateField(required=False, allow_null=True)
    reason = serializers.ChoiceField(services.OFFBOARD_REASONS)
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    steps = serializers.DictField(child=serializers.DictField(), required=False)
    override_blockers = serializers.BooleanField(required=False, default=False)


class HistoryRecordSerializer(serializers.ModelSerializer):
    action_label = serializers.CharField()
    actor = serializers.SerializerMethodField()
    details = serializers.JSONField()

    class Meta:
        model = AuditLog
        fields = (
            "id",
            "created_at",
            "action",
            "action_label",
            "actor",
            "target_type",
            "target_id",
            "target",
            "details",
        )
        read_only_fields = fields

    @extend_schema_field(NamedSerializer(allow_null=True))
    def get_actor(self, row: AuditLog) -> dict | None:
        if row.actor_id is None:
            return None
        member = self.context.get("members", {}).get(row.actor_id)
        return {
            "id": member.pk if member else None,
            "name": (member.full_name if member else "") or str(row.actor),
        }


def people_context(viewer: Membership, people: list[Membership]) -> dict:
    """Serializer context for directory rows: employment dates, work numbers and other
    modules' fields, each fetched once for the whole page."""
    from apps.hr.queries import employment_dates

    ids = [person.pk for person in people]
    now = timezone.now()
    return {
        "membership": viewer,
        "company": viewer.company,
        "dates": employment_dates(viewer.company, ids),
        "work": queries.work_scores(viewer.company, ids, now),
        "fields": registry.collect_person_fields(viewer, ids, now),
    }


def person_detail(viewer: Membership, person: Membership) -> dict:
    """Person 360 as `viewer` sees it."""
    now = timezone.now()
    today = timezone.localtime(now, ZoneInfo(viewer.company.timezone)).date()
    context = people_context(viewer, [person]) | {
        "overview": queries.person_overview(person, today - timedelta(days=29), today, now)
    }
    return PersonDetailSerializer(person, context=context).data


# People ---------------------------------------------------------------------------------


class PeopleViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, OwnerViewSet
):
    """The team directory and Person 360."""

    perm = Perm.MEMBERS_VIEW
    perms_by_action = {
        "partial_update": Perm.MEMBERS_MANAGE,
        "update": Perm.MEMBERS_MANAGE,
        "block": Perm.MEMBERS_MANAGE,
        "unblock": Perm.MEMBERS_MANAGE,
        "offboard_preview": Perm.MEMBERS_MANAGE,
        "offboard": Perm.MEMBERS_MANAGE,
        "suspend": Perm.HR_SUSPEND,
        "reinstate": Perm.HR_SUSPEND,
    }
    serializer_class = PersonSerializer
    pagination_class = PeoplePagination
    lookup_value_regex = r"\d+"
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Membership.objects.none()
        branch_scope = scope.branch_ids(self.membership)
        if self.action != "list":
            # Anyone they may see, whatever their status (a former member's page too).
            people = Membership.objects.filter(company=self.company)
            if branch_scope is not None:
                shared = Membership.objects.filter(
                    company=self.company, branches__in=branch_scope
                ).values("pk")
                people = people.filter(Q(pk__in=shared) | Q(pk=self.membership.pk))
            return people.select_related(
                "user", "role", "position", "home_branch", "company"
            ).prefetch_related("branches")
        params = self.request.query_params
        branches = _ints(params.getlist("branch"))
        if branches and branch_scope is not None:
            branches = [b for b in branches if b in branch_scope] or [-1]
        people = queries.directory(
            self.company,
            branch_ids=branch_scope,
            q=params.get("q", "").strip() or None,
            position_id=_ints(params.getlist("position")) or None,
            role_id=_ints(params.getlist("role")) or None,
            status=_status(params.get("status")),
            branch=branches or None,
            include=self.membership,
        )
        if params.get("bot_blocked") in ("1", "true"):
            people = people.filter(user__employee_bot_blocked_at__isnull=False)
        ordering = {
            "name": ("first_name", "last_name"),
            "-name": ("-first_name", "-last_name"),
            "position": ("position__order", "position__name", "first_name"),
            "-position": ("-position__order", "-position__name", "first_name"),
            "joined": ("decided_at", "pk"),
            "-joined": ("-decided_at", "-pk"),
            "branch": ("home_branch__order", "home_branch__name", "first_name"),
            "-branch": ("-home_branch__order", "-home_branch__name", "first_name"),
        }.get(params.get("ordering") or "name", ("first_name", "last_name"))
        return people.order_by(*ordering, "pk")

    def _context_for(self, people: list[Membership]) -> dict:
        return self.get_serializer_context() | people_context(self.membership, people)

    @extend_schema(
        parameters=[
            OpenApiParameter("q", str),
            OpenApiParameter(
                "status",
                str,
                description="current (default), active, suspended, pending, left, blocked, former",
            ),
            OpenApiParameter("position", int, many=True),
            OpenApiParameter("role", int, many=True),
            OpenApiParameter("branch", int, many=True),
            OpenApiParameter("bot_blocked", bool),
            OpenApiParameter("ordering", str, description="name, position, branch, joined"),
        ]
    )
    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        context = self._context_for(page)
        return self.get_paginated_response(PersonSerializer(page, many=True, context=context).data)

    @extend_schema(responses=PersonDetailSerializer)
    def retrieve(self, request, *args, **kwargs):
        person = self.get_object()
        return Response(self._detail(person))

    def _detail(self, person: Membership) -> dict:
        return person_detail(self.membership, person)

    @extend_schema(request=PersonUpdateSerializer, responses=PersonDetailSerializer)
    def partial_update(self, request, *args, **kwargs):
        person = self.get_object()
        serializer = PersonUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # The role and the rest change together or not at all.
        with transaction.atomic():
            self._update(person, serializer.validated_data)
        self.bump(PEOPLE)
        return Response(self._detail(self.get_queryset().get(pk=person.pk)))

    def _update(self, person: Membership, data: dict) -> None:
        if "role_id" in data:
            if not self.membership.has_perm(Perm.ROLES_MANAGE):
                self.permission_denied(
                    self.request, message=_("Changing a role needs roles.manage.")
                )
            role = get_object_or_404(
                AccessRole.objects.for_company(self.company), pk=data["role_id"]
            )
            services.change_role(person, by=self.membership, role=role)
        changes = {}
        for field in ("first_name", "last_name"):
            if field in data:
                changes[field] = data[field]
        if "position_id" in data:
            changes["position"] = (
                _position(self.company, data["position_id"])
                if data["position_id"] is not None
                else None
            )
        if "branch_ids" in data:
            changes["branches"] = _branches(self.company, data["branch_ids"])
        if "home_branch_id" in data:
            changes["home_branch"] = (
                _branch(self.company, data["home_branch_id"])
                if data["home_branch_id"] is not None
                else None
            )
        if changes:
            services.update_member(person, by=self.membership, **changes)

    @extend_schema(request=None, responses=PersonDetailSerializer)
    @action(detail=True, methods=["post"])
    def block(self, request, company_id, pk):
        person = services.block_member(self.get_object(), by=self.membership)
        self.bump(PEOPLE, "members.pending")
        return Response(self._detail(self.get_queryset().get(pk=person.pk)))

    @extend_schema(request=None, responses=PersonDetailSerializer)
    @action(detail=True, methods=["post"])
    def unblock(self, request, company_id, pk):
        person = services.unblock(self.get_object(), by=self.membership)
        self.bump(PEOPLE)
        return Response(self._detail(self.get_queryset().get(pk=person.pk)))

    @extend_schema(request=SuspendSerializer, responses=PersonDetailSerializer)
    @action(detail=True, methods=["post"])
    def suspend(self, request, company_id, pk):
        serializer = SuspendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        person = services.suspend(
            self.get_object(),
            by=self.membership,
            until=serializer.validated_data.get("until"),
            reason=serializer.validated_data["reason"],
        )
        self.bump(PEOPLE)
        return Response(self._detail(self.get_queryset().get(pk=person.pk)))

    @extend_schema(request=None, responses=PersonDetailSerializer)
    @action(detail=True, methods=["post"])
    def reinstate(self, request, company_id, pk):
        person = services.reinstate(self.get_object(), by=self.membership)
        self.bump(PEOPLE)
        return Response(self._detail(self.get_queryset().get(pk=person.pk)))

    @extend_schema(
        responses=inline_serializer(
            "MembersOffboardPreview",
            {
                "steps": serializers.ListField(child=serializers.DictField()),
                "blockers": serializers.IntegerField(),
                "can_override": serializers.BooleanField(),
                "reasons": serializers.ListField(child=serializers.CharField()),
                "today": serializers.DateField(),
            },
        )
    )
    @action(detail=True, methods=["get"], url_path="offboard-preview")
    def offboard_preview(self, request, company_id, pk):
        person = self.get_object()
        if person.status not in queries.CURRENT:
            raise ValidationError({"detail": _("Only current members can be offboarded.")})
        preview = services.offboard_preview(person, by=self.membership)
        today = timezone.localdate(timezone=ZoneInfo(self.company.timezone))
        return Response(
            preview | {"reasons": list(services.OFFBOARD_REASONS), "today": today.isoformat()}
        )

    @extend_schema(request=OffboardSerializer, responses=PersonDetailSerializer)
    @action(detail=True, methods=["post"])
    def offboard(self, request, company_id, pk):
        serializer = OffboardSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        person = services.complete_offboarding(
            self.get_object(),
            by=self.membership,
            terminated_on=data.get("terminated_on"),
            reason=data["reason"],
            note=data.get("note", ""),
            steps=data.get("steps") or {},
            override_blockers=data.get("override_blockers", False),
        )
        self.bump(PEOPLE, "timeoff.time_off")
        return Response(self._detail(self.get_queryset().get(pk=person.pk)))

    @extend_schema(
        responses=inline_serializer(
            "MembersStats",
            {
                "current": serializers.IntegerField(),
                "active": serializers.IntegerField(),
                "suspended": serializers.IntegerField(),
                "on_leave_today": serializers.IntegerField(),
                "joined_30d": serializers.IntegerField(),
                "left_30d": serializers.IntegerField(),
                "pending_requests": serializers.IntegerField(),
                "bot_blocked": serializers.IntegerField(),
            },
        )
    )
    @action(detail=False, methods=["get"])
    def stats(self, request, company_id):
        """The numbers above the directory, inside the caller's branch scope."""
        return Response(queries.team_stats(self.membership, timezone.now()))

    @extend_schema(responses=HistoryRecordSerializer(many=True))
    @action(detail=True, methods=["get"])
    def history(self, request, company_id, pk):
        person = self.get_object()
        from apps.timeoff.models import TimeOff

        time_off_ids = list(TimeOff.objects.filter(membership=person).values_list("pk", flat=True))
        rows = audit_queries.events(self.membership).filter(
            Q(target_type="membership", target_id=person.pk)
            | Q(target_type="timeoff", target_id__in=time_off_ids)
        )
        page = self.paginate_queryset(rows)
        actor_ids = {row.actor_id for row in page if row.actor_id}
        members = Membership.objects.filter(company=self.company, user_id__in=actor_ids)
        context = {"members": {member.user_id: member for member in members}}
        return self.get_paginated_response(
            HistoryRecordSerializer(page, many=True, context=context).data
        )


# Join requests -----------------------------------------------------------------------------


class JoinRequestSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    photo_url = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    username = serializers.SerializerMethodField()
    position = serializers.SerializerMethodField()
    onboarded = serializers.SerializerMethodField()
    requested_at = serializers.SerializerMethodField()
    former = serializers.SerializerMethodField()
    fields = serializers.SerializerMethodField(method_name="get_extra")

    class Meta:
        model = Membership
        fields = (
            "id",
            "name",
            "first_name",
            "last_name",
            "photo_url",
            "phone",
            "username",
            "position",
            "onboarded",
            "requested_at",
            "former",
            "fields",
        )
        read_only_fields = fields

    def get_name(self, row: Membership) -> str:
        return row.full_name or row.user.get_full_name() or str(row.user)

    def get_photo_url(self, row: Membership) -> str | None:
        return photo_url(row)

    def get_phone(self, row: Membership) -> str:
        return row.user.phone or ""

    def get_username(self, row: Membership) -> str:
        return row.user.telegram_username or ""

    @extend_schema_field(NamedSerializer(allow_null=True))
    def get_position(self, row: Membership) -> dict | None:
        return {"id": row.position.pk, "name": row.position.name} if row.position else None

    def get_onboarded(self, row: Membership) -> bool:
        return row.onboarded_at is not None

    def get_requested_at(self, row: Membership):
        return (row.onboarded_at or row.created_at).isoformat()

    @extend_schema_field(
        inline_serializer(
            "MembersFormer",
            {"left_on": serializers.DateField(), "how": serializers.CharField()},
            allow_null=True,
        )
    )
    def get_former(self, row: Membership) -> dict | None:
        former = self.context.get("former")
        return former.get(row.pk) if former is not None else queries.former_member(row)

    @extend_schema_field(serializers.DictField())
    def get_extra(self, row: Membership) -> dict:
        return self.context.get("fields", {}).get(row.pk, {})


class ApproveSerializer(serializers.Serializer):
    role_id = serializers.IntegerField(required=False, allow_null=True)
    position_id = serializers.IntegerField(required=False, allow_null=True)
    branch_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    home_branch_id = serializers.IntegerField(required=False, allow_null=True)


class RejectSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=300)


class JoinRequestViewSet(mixins.ListModelMixin, OwnerViewSet):
    """People asking to join, with approve (role, position, branches) and reject."""

    perm = Perm.MEMBERS_APPROVE
    serializer_class = JoinRequestSerializer
    pagination_class = None
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Membership.objects.none()
        return queries.join_requests(self.company)

    def list(self, request, *args, **kwargs):
        rows = list(self.get_queryset())
        ids = [row.pk for row in rows]
        fields = registry.collect_person_fields(self.membership, ids, timezone.now())
        context = self.get_serializer_context() | {
            "fields": fields,
            "former": queries.former_members(self.company, ids),
        }
        return Response(JoinRequestSerializer(rows, many=True, context=context).data)

    def _request(self, pk) -> Membership:
        found = self.get_queryset().filter(pk=pk).first()
        if found is None:
            raise NotFound
        return found

    @extend_schema(request=ApproveSerializer, responses=PersonDetailSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request, company_id, pk):
        serializer = ApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        role = (
            get_object_or_404(AccessRole.objects.for_company(self.company), pk=data["role_id"])
            if data.get("role_id")
            else None
        )
        position = _position(self.company, data["position_id"]) if data.get("position_id") else None
        branches = _branches(self.company, data.get("branch_ids") or [])
        home = _branch(self.company, data["home_branch_id"]) if data.get("home_branch_id") else None
        person = services.approve_request(
            self._request(pk),
            by=self.membership,
            role=role,
            position=position,
            branches=branches or None,
            home_branch=home,
        )
        self.bump("members.pending", PEOPLE)
        fresh = (
            Membership.objects.select_related("user", "role", "position", "home_branch", "company")
            .prefetch_related("branches")
            .get(pk=person.pk)
        )
        return Response(person_detail(self.membership, fresh))

    @extend_schema(request=RejectSerializer, responses={204: None})
    @action(detail=True, methods=["post"])
    def reject(self, request, company_id, pk):
        serializer = RejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.reject_request(
            self._request(pk),
            by=self.membership,
            reason=serializer.validated_data.get("reason", ""),
        )
        self.bump("members.pending")
        return Response(status=status.HTTP_204_NO_CONTENT)


# Roles ------------------------------------------------------------------------------------


class RoleSerializer(serializers.ModelSerializer):
    members_count = serializers.IntegerField(read_only=True)
    can_edit = serializers.SerializerMethodField()
    can_assign = serializers.SerializerMethodField()
    permissions = serializers.ListField(child=serializers.ChoiceField(Perm.choices))

    class Meta:
        model = AccessRole
        fields = (
            "id",
            "name",
            "permissions",
            "is_owner",
            "is_default",
            "members_count",
            "can_edit",
            "can_assign",
        )
        read_only_fields = ("id", "is_owner", "members_count", "can_edit", "can_assign")

    def get_can_edit(self, role: AccessRole) -> bool:
        viewer = self.context["membership"]
        return viewer.has_perm(Perm.ROLES_MANAGE) and services.may_edit_role(viewer, role)

    def get_can_assign(self, role: AccessRole) -> bool:
        return services.may_assign_role(self.context["membership"], role)


class RoleViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    OwnerViewSet,
):
    """Roles (permission bundles) with the anti-escalation rules of §5."""

    perm = Perm.ROLES_MANAGE
    perms_by_action = {"list": AnyOf(Perm.ROLES_MANAGE, Perm.MEMBERS_APPROVE, Perm.MEMBERS_VIEW)}
    serializer_class = RoleSerializer
    pagination_class = None
    lookup_value_regex = r"\d+"
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AccessRole.objects.none()
        return queries.roles(self.company)

    def perform_create(self, serializer):
        data = serializer.validated_data
        role = services.save_role(
            self.company,
            by=self.membership,
            name=data["name"],
            permissions=data.get("permissions", []),
            is_default=data.get("is_default") or None,
        )
        serializer.instance = queries.roles(self.company).get(pk=role.pk)
        self.bump("members.roles")

    def perform_update(self, serializer):
        data = serializer.validated_data
        role = serializer.instance
        saved = services.save_role(
            self.company,
            by=self.membership,
            role=role,
            name=data.get("name", role.name),
            permissions=data.get("permissions", role.permissions),
            is_default=data.get("is_default") or None,
        )
        serializer.instance = queries.roles(self.company).get(pk=saved.pk)
        self.bump("members.roles", PEOPLE)

    def perform_destroy(self, instance):
        services.delete_role(instance, by=self.membership)
        self.bump("members.roles")


# Positions --------------------------------------------------------------------------------


class PositionSerializer(serializers.ModelSerializer):
    members_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Position
        fields = ("id", "name", "order", "is_active", "members_count")
        read_only_fields = ("id", "order", "members_count")


class PositionViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    OwnerViewSet,
):
    """Job titles people pick when they join; the order is the order they see."""

    perm = Perm.POSITIONS_MANAGE
    perms_by_action = {"list": None}
    serializer_class = PositionSerializer
    pagination_class = None
    lookup_value_regex = r"\d+"
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Position.objects.none()
        active = self.request.query_params.get("active")
        flag = True if active in ("1", "true") else False if active in ("0", "false") else None
        return queries.positions(self.company, active=flag if self.action == "list" else None)

    @extend_schema(parameters=[OpenApiParameter("active", bool)])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer):
        position = services.save_position(
            self.company,
            by=self.membership,
            name=serializer.validated_data["name"],
            is_active=serializer.validated_data.get("is_active"),
        )
        serializer.instance = queries.positions(self.company).get(pk=position.pk)
        self.bump("members.positions")

    def perform_update(self, serializer):
        position = services.save_position(
            self.company,
            by=self.membership,
            position=serializer.instance,
            name=serializer.validated_data.get("name"),
            is_active=serializer.validated_data.get("is_active"),
        )
        serializer.instance = queries.positions(self.company).get(pk=position.pk)
        self.bump("members.positions", PEOPLE)

    def perform_destroy(self, instance):
        services.delete_position(instance, by=self.membership)
        self.bump("members.positions")

    @extend_schema(
        request=inline_serializer(
            "MembersPositionsOrder",
            {"ids": serializers.ListField(child=serializers.IntegerField())},
        ),
        responses=PositionSerializer(many=True),
    )
    @action(detail=False, methods=["post"])
    def reorder(self, request, company_id):
        ids = request.data.get("ids")
        if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
            raise ValidationError({"ids": [_("Send the position ids in their new order.")]})
        services.reorder_positions(self.company, by=self.membership, ids=ids)
        self.bump("members.positions")
        return Response(PositionSerializer(queries.positions(self.company), many=True).data)


# Helpers ----------------------------------------------------------------------------------


def _ints(values) -> list[int]:
    found = []
    for value in values:
        for part in str(value).split(","):
            part = part.strip()
            if part.isdigit():
                found.append(int(part))
    return found


def _status(value: str | None) -> str:
    return value if value in queries.DIRECTORY_STATUSES else "current"


def _position(company, position_id: int) -> Position:
    found = Position.objects.for_company(company).filter(pk=position_id).first()
    if found is None:
        raise ValidationError({"position_id": [_("Pick a position of this company.")]})
    return found


def _branch(company, branch_id: int) -> Branch:
    found = Branch.objects.for_company(company).filter(pk=branch_id).first()
    if found is None:
        raise ValidationError({"home_branch_id": [_("Pick a branch of this company.")]})
    return found


def _branches(company, ids: list[int]) -> list[Branch]:
    found = list(Branch.objects.for_company(company).filter(pk__in=ids))
    if len(found) != len(set(ids)):
        raise ValidationError({"branch_ids": [_("Pick branches of this company.")]})
    return sorted(found, key=lambda b: ids.index(b.pk))
