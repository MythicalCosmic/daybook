"""Owner dashboard endpoints of attendance (`attendance/…`, docs/PLAN-OWNER.md §4.9).

Every endpoint is company-scoped and branch-scoped (§2.6: an id outside the caller's
branches answers 404), checks `attendance.view` or `attendance.manage`, audits writes through
the services and bumps the module's pulse keys after commit. Dates are company-local
`YYYY-MM-DD`. Except for the settings, the endpoints answer 403 while the module is off.
"""

from datetime import date, datetime

from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.attendance import clock, conf, queries, services
from apps.attendance import serializers as s
from apps.attendance.models import (
    AttendanceCorrection,
    AttendanceRecord,
    ShiftSwap,
    ShiftTemplate,
    WorkSchedule,
    WorkShift,
)
from apps.companies.models import Branch
from apps.console.base import OwnerAPIView, OwnerViewSet, RangeMixin
from apps.core.files import signed_url
from apps.members import scope
from apps.members.models import Membership, Position
from apps.members.permissions import Perm

VIEW, MANAGE = Perm.ATTENDANCE_VIEW, Perm.ATTENDANCE_MANAGE
BRANCH_PARAM = OpenApiParameter(
    "branch", int, many=True, description="Branch ids (within your scope)."
)


class ModuleOn:
    """403 while attendance is switched off for the company."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not self.company.has_feature("attendance"):
            raise PermissionDenied(_("Attendance isn't switched on for this company."))


def _day(value: str | None, name: str, default: date | None = None) -> date:
    if not value:
        if default is None:
            raise ValidationError({name: [_("Give a day as YYYY-MM-DD.")]})
        return default
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError({name: [_("Give a day as YYYY-MM-DD.")]}) from exc


def _month(value: str | None, default: date) -> date:
    if not value:
        return default.replace(day=1)
    try:
        return datetime.strptime(value[:7], "%Y-%m").date()
    except ValueError as exc:
        raise ValidationError({"month": [_("Give a month as YYYY-MM.")]}) from exc


def _ints(values) -> list[int]:
    try:
        return [int(value) for value in values if str(value).strip()]
    except ValueError as exc:
        raise ValidationError({"branch": [_("Give branch ids.")]}) from exc


def _id(value, name: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({name: [_("Give a number.")]}) from exc


class Scoped:
    """Branch-scope helpers for the views below."""

    def requested_branches(self) -> list[int] | None:
        """`?branch=` (repeatable) intersected with the caller's scope; the scope otherwise."""
        asked = _ints(self.request.query_params.getlist("branch"))
        allowed = self.branch_scope
        if not asked:
            return allowed
        return asked if allowed is None else [branch for branch in asked if branch in allowed]

    def one_branch(self, value) -> Branch | None:
        value = _id(value, "branch")
        if value is None:
            return None
        branch = Branch.objects.filter(company=self.company, pk=value).first()
        if branch is None or not scope.allows(self.branch_scope, branch.pk):
            raise NotFound
        return branch

    def staff_member(self, member_id) -> Membership:
        member = (
            queries.staff(self.company, branch_ids=self.branch_scope)
            .filter(pk=member_id)
            .select_related("user", "position", "home_branch", "company")
            .first()
        )
        if member is None:
            raise NotFound
        return member

    def position(self, value) -> Position | None:
        if value in (None, ""):
            return None
        position = Position.objects.filter(company=self.company, pk=value).first()
        if position is None:
            raise NotFound
        return position


# Settings -------------------------------------------------------------------------------


class SettingsView(OwnerAPIView):
    """The company's attendance rules."""

    perm = MANAGE

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


# The board ------------------------------------------------------------------------------


class BoardView(ModuleOn, Scoped, OwnerAPIView):
    """Who is in, late, not here yet, absent or off on a day, per person and branch."""

    perm = VIEW

    @extend_schema(
        parameters=[
            OpenApiParameter("date", str, description="YYYY-MM-DD, today by default."),
            BRANCH_PARAM,
        ],
        responses=s.BoardSerializer,
    )
    def get(self, request, company_id):
        day = _day(request.query_params.get("date"), "date", clock.today(self.company))
        return Response(queries.day_board(self.company, day, branch_ids=self.requested_branches()))


# Records --------------------------------------------------------------------------------


def record_row(record: AttendanceRecord, company) -> dict:
    data = queries.record_payload(record, company)
    data["member"] = queries.person_card(record.membership)
    data["shift"] = queries.shift_payload(record.shift, company) if record.shift_id else None
    return data


class RecordViewSet(
    ModuleOn,
    Scoped,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    OwnerViewSet,
):
    """Check-in records: list with filters, detail, manual records, corrections, excuses
    and overtime decisions."""

    perm = VIEW
    perms_by_action = {
        "create": MANAGE,
        "partial_update": MANAGE,
        "update": MANAGE,
        "excuse": MANAGE,
        "overtime": MANAGE,
    }
    lookup_value_regex = r"\d+"
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AttendanceRecord.objects.none()
        params = self.request.query_params
        records = scope.restrict(
            AttendanceRecord.objects.for_company(self.company), self.branch_scope
        ).select_related(
            "membership__user",
            "membership__position",
            "membership__home_branch",
            "shift__branch",
            "shift__position",
            "branch",
            "edited_by",
        )
        if self.action != "list":
            return records
        if params.get("from"):
            records = records.filter(date__gte=_day(params["from"], "from"))
        if params.get("to"):
            records = records.filter(date__lte=_day(params["to"], "to"))
        if params.get("member"):
            records = records.filter(membership_id=_id(params["member"], "member"))
        if params.get("flag"):
            records = records.filter(flags__contains=[params["flag"]])
        if params.get("status"):
            records = records.filter(status=params["status"])
        if params.get("overtime"):
            records = records.filter(overtime_status=params["overtime"])
        branches = _ints(params.getlist("branch"))
        if branches:
            records = records.filter(branch_id__in=branches)
        ordering = params.get("ordering") or "-date"
        allowed = {
            "date",
            "-date",
            "check_in_at",
            "-check_in_at",
            "late_minutes",
            "-late_minutes",
            "worked_minutes",
            "-worked_minutes",
        }
        if ordering not in allowed:
            ordering = "-date"
        return records.order_by(ordering, "-check_in_at", "-pk")

    @extend_schema(
        parameters=[
            OpenApiParameter("from", str),
            OpenApiParameter("to", str),
            OpenApiParameter("member", int),
            OpenApiParameter("flag", str, enum=list(AttendanceRecord.Flag.values)),
            OpenApiParameter("status", str, enum=list(AttendanceRecord.Status.values)),
            OpenApiParameter("overtime", str, enum=list(AttendanceRecord.Overtime.values)),
            BRANCH_PARAM,
        ],
        responses=s.RecordRowSerializer(many=True),
    )
    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response([record_row(record, self.company) for record in page])

    @extend_schema(responses=s.RecordDetailSerializer)
    def retrieve(self, request, *args, **kwargs):
        record = self.get_object()
        data = record_row(record, self.company)
        data["photo_url"] = (
            signed_url(
                record.in_photo,
                user=request.user,
                company_id=self.company.pk,
                check=f"attendance.selfie:{record.pk}",
            )
            if record.in_photo
            else None
        )
        data["edited_by"] = record.edited_by.get_full_name() if record.edited_by_id else None
        data["branch_geo"] = queries.branch_geo(record.branch)
        return Response(data)

    @extend_schema(request=s.RecordCreateSerializer, responses={201: s.RecordRowSerializer})
    def create(self, request, *args, **kwargs):
        serializer = s.RecordCreateSerializer(data=request.data, context={"company": self.company})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        record = services.create_record(
            self.company,
            by=self.membership,
            membership=self.staff_member(data["member_id"]),
            date=data["date"],
            check_in_at=data["check_in_at"],
            check_out_at=data["check_out_at"],
            reason=data["reason"],
            note=data["note"],
        )
        return Response(record_row(record, self.company), status=status.HTTP_201_CREATED)

    @extend_schema(request=s.RecordEditSerializer, responses=s.RecordRowSerializer)
    def partial_update(self, request, *args, **kwargs):
        record = self.get_object()
        serializer = s.RecordEditSerializer(data=request.data, context={"company": self.company})
        serializer.is_valid(raise_exception=True)
        record = services.edit_record(record, by=self.membership, **serializer.validated_data)
        return Response(record_row(record, self.company))

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    @extend_schema(request=s.ReasonSerializer, responses=s.RecordRowSerializer)
    @action(detail=True, methods=["post"])
    def excuse(self, request, company_id, pk):
        serializer = s.ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = services.excuse(self.get_object(), by=self.membership, **serializer.validated_data)
        return Response(record_row(record, self.company))

    @extend_schema(request=s.DecisionSerializer, responses=s.RecordRowSerializer)
    @action(detail=True, methods=["post"])
    def overtime(self, request, company_id, pk):
        serializer = s.DecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = services.decide_overtime(
            self.get_object(), by=self.membership, **serializer.validated_data
        )
        return Response(record_row(record, self.company))


# Timesheet, summary, staff, one person --------------------------------------------------


class TimesheetView(ModuleOn, Scoped, OwnerAPIView):
    """People by days of a month, with each person's totals."""

    perm = VIEW

    @extend_schema(
        parameters=[
            OpenApiParameter("month", str, description="YYYY-MM, this month by default."),
            OpenApiParameter("branch", int),
        ],
        responses=s.TimesheetSerializer,
    )
    def get(self, request, company_id):
        month = _month(request.query_params.get("month"), clock.today(self.company))
        branch = self.one_branch(request.query_params.get("branch"))
        return Response(
            queries.timesheet(
                self.company,
                month,
                branch_ids=self.branch_scope,
                branch_id=branch.pk if branch else None,
            )
        )


class SummaryView(ModuleOn, Scoped, RangeMixin, OwnerAPIView):
    """Attendance in the analytics shape: present, late, absent, rostered, rates, hours."""

    perm = VIEW

    @extend_schema(
        parameters=[
            OpenApiParameter("from", str),
            OpenApiParameter("to", str),
            OpenApiParameter("preset", str),
            OpenApiParameter("compare", str, enum=["none", "prev", "year"]),
            OpenApiParameter("member", int),
            BRANCH_PARAM,
        ],
        responses=s.SummarySerializer,
    )
    def get(self, request, company_id):
        period = self.range
        member_id = _id(request.query_params.get("member"), "member")
        member = self.staff_member(member_id) if member_id else None
        compare = (period.compare_start, period.compare_end) if period.has_compare else None
        return Response(
            queries.summary(
                self.company,
                period.start,
                period.end,
                branch_ids=self.requested_branches(),
                membership=member,
                compare=compare,
            )
        )


class StaffView(ModuleOn, Scoped, OwnerAPIView):
    """People in scope with their position, home branch and schedule (for pickers)."""

    perm = VIEW

    @extend_schema(
        parameters=[OpenApiParameter("branch", int)], responses=s.RosterMemberSerializer(many=True)
    )
    def get(self, request, company_id):
        branch = self.one_branch(request.query_params.get("branch"))
        people = (
            queries.staff_at(
                self.company, branch.pk if branch else None, branch_ids=self.branch_scope
            )
            .select_related("user", "position", "home_branch", "work_schedule__schedule")
            .order_by("first_name", "last_name", "pk")
        )
        return Response(
            [
                queries.person_card(member)
                | {"schedule": queries._schedule_ref(member), "minutes": 0, "leave": []}
                for member in people
            ]
        )


class MemberView(ModuleOn, Scoped, OwnerAPIView):
    """One person's month (Person 360 tab): coded days, totals, schedule, recent records."""

    perm = VIEW

    @extend_schema(parameters=[OpenApiParameter("month", str)], responses=s.MyMonthSerializer)
    def get(self, request, company_id, member_id):
        member = self.staff_member(member_id)
        month = _month(request.query_params.get("month"), clock.today(self.company))
        data = queries.my_month(member, month)
        data["member"] = queries.person_card(member)
        data["schedule"] = queries._schedule_ref(member)
        start, end = queries.month_bounds(month)
        data["summary"] = queries.summary(
            self.company, start, end, branch_ids=None, membership=member
        )["totals"]
        records = (
            AttendanceRecord.objects.filter(membership=member)
            .select_related("branch", "shift__branch", "shift__position")
            .order_by("-date", "-check_in_at")[:12]
        )
        data["records"] = [queries.record_payload(record, self.company) for record in records]
        data["next_shifts"] = [
            queries.shift_payload(shift, self.company)
            for shift in WorkShift.objects.working()
            .filter(membership=member, starts_at__gt=timezone.now())
            .select_related("branch", "position")
            .order_by("starts_at")[:5]
        ]
        return Response(data)


# Schedules and templates ----------------------------------------------------------------


class ScheduleViewSet(
    ModuleOn,
    Scoped,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    OwnerViewSet,
):
    """Work schedules (weekly, rotating, flexible) and who follows them. Deleting archives."""

    perm = VIEW
    perms_by_action = {
        "create": MANAGE,
        "update": MANAGE,
        "partial_update": MANAGE,
        "destroy": MANAGE,
        "assign": MANAGE,
        "unassign": MANAGE,
    }
    serializer_class = s.ScheduleSerializer
    pagination_class = None
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return WorkSchedule.objects.none()
        rows = WorkSchedule.objects.for_company(self.company).prefetch_related("days")
        if self.action == "list" and self.request.query_params.get("archived") != "1":
            rows = rows.filter(is_active=True)
        return rows.order_by("-is_active", "name")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if hasattr(self, "company"):
            context["assignments"] = queries.assignments(self.company)
        return context

    def perform_create(self, serializer):
        data = serializer.validated_data
        serializer.instance = services.create_schedule(self.company, by=self.membership, **data)

    def perform_update(self, serializer):
        data = dict(serializer.validated_data)
        days = data.pop("days", None)
        serializer.instance = services.update_schedule(
            serializer.instance, by=self.membership, days=days, **data
        )

    def perform_destroy(self, instance):
        services.archive_schedule(instance, by=self.membership)

    @extend_schema(request=s.AssignSerializer, responses=s.CountSerializer)
    @action(detail=True, methods=["post"])
    def assign(self, request, company_id, pk):
        schedule = self.get_object()
        serializer = s.AssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        count = services.assign_schedule(
            self.company,
            schedule,
            serializer.validated_data["member_ids"],
            by=self.membership,
            effective_from=serializer.validated_data.get("effective_from"),
        )
        return Response({"count": count})

    @extend_schema(request=s.UnassignSerializer, responses=s.CountSerializer)
    @action(detail=False, methods=["post"])
    def unassign(self, request, company_id):
        serializer = s.UnassignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        count = services.assign_schedule(
            self.company, None, serializer.validated_data["member_ids"], by=self.membership
        )
        return Response({"count": count})


class TemplateViewSet(
    ModuleOn,
    Scoped,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    OwnerViewSet,
):
    """Ready-made shifts for the roster builder ("Morning 09:00-18:00")."""

    perm = VIEW
    perms_by_action = {
        "create": MANAGE,
        "update": MANAGE,
        "partial_update": MANAGE,
        "destroy": MANAGE,
    }
    serializer_class = s.TemplateSerializer
    pagination_class = None
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ShiftTemplate.objects.none()
        return ShiftTemplate.objects.for_company(self.company).filter(is_active=True)

    def _fields(self, data: dict) -> dict:
        data = dict(data)
        if "position_id" in data:
            data["position"] = self.position(data.pop("position_id"))
        return data

    def perform_create(self, serializer):
        serializer.instance = services.save_template(
            self.company, by=self.membership, **self._fields(serializer.validated_data)
        )

    def perform_update(self, serializer):
        serializer.instance = services.save_template(
            self.company,
            by=self.membership,
            template=serializer.instance,
            **self._fields(serializer.validated_data),
        )

    def perform_destroy(self, instance):
        services.remove_template(instance, by=self.membership)


# Shifts and the roster ------------------------------------------------------------------


class ShiftViewSet(
    ModuleOn,
    Scoped,
    mixins.ListModelMixin,
    mixins.DestroyModelMixin,
    OwnerViewSet,
):
    """The roster's shifts: list, add (`member_id` empty: an open shift), move, remove,
    bulk actions on a week and publishing."""

    perm = VIEW
    perms_by_action = {
        "create": MANAGE,
        "partial_update": MANAGE,
        "destroy": MANAGE,
        "bulk": MANAGE,
        "publish": MANAGE,
    }
    pagination_class = None
    lookup_value_regex = r"\d+"
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return WorkShift.objects.none()
        shifts = WorkShift.objects.for_company(self.company).exclude(
            status=WorkShift.Status.CANCELLED
        )
        return scope.restrict(shifts, self.branch_scope).select_related(
            "membership__user", "branch", "position", "company"
        )

    @extend_schema(
        parameters=[
            OpenApiParameter("from", str, required=True),
            OpenApiParameter("to", str, required=True),
            OpenApiParameter("member", int),
            OpenApiParameter("branch", int),
        ],
        responses=s.ShiftOutSerializer(many=True),
    )
    def list(self, request, *args, **kwargs):
        params = request.query_params
        start, end = _day(params.get("from"), "from"), _day(params.get("to"), "to")
        if (end - start).days > 62:
            raise ValidationError({"to": [_("Pick at most two months.")]})
        branch = self.one_branch(params.get("branch"))
        shifts = queries.shifts_between(
            self.company,
            start,
            end,
            branch_ids=self.branch_scope,
            branch_id=branch.pk if branch else None,
            member_id=_id(params.get("member"), "member"),
        )
        return Response([queries.shift_payload(shift, self.company) for shift in shifts])

    @extend_schema(request=s.ShiftWriteSerializer, responses={201: s.ShiftOutSerializer})
    def create(self, request, company_id):
        serializer = s.ShiftWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        member = self.staff_member(data["member_id"]) if data.get("member_id") else None
        shift = services.create_shift(
            self.company,
            by=self.membership,
            membership=member,
            date=data["date"],
            starts_at=data["start"],
            ends_at=data["end"],
            break_minutes=data["break_minutes"],
            branch=self.one_branch(data.get("branch_id")),
            position=self.position(data.get("position_id")),
            note=data["note"],
            publish=data["publish"],
        )
        return Response(queries.shift_payload(shift, self.company), status=status.HTTP_201_CREATED)

    @extend_schema(request=s.ShiftPatchSerializer, responses=s.ShiftOutSerializer)
    def partial_update(self, request, company_id, pk):
        shift = self.get_object()
        serializer = s.ShiftPatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        changes = {}
        if "member_id" in data:
            changes["membership"] = (
                self.staff_member(data["member_id"]) if data["member_id"] else None
            )
        for field, name in (("date", "date"), ("start", "starts_at"), ("end", "ends_at")):
            if field in data:
                changes[name] = data[field]
        for name in ("break_minutes", "note"):
            if name in data:
                changes[name] = data[name]
        if "branch_id" in data:
            changes["branch"] = self.one_branch(data["branch_id"])
        if "position_id" in data:
            changes["position"] = self.position(data["position_id"])
        shift = services.update_shift(shift, by=self.membership, **changes)
        return Response(queries.shift_payload(shift, self.company))

    def perform_destroy(self, instance):
        services.delete_shift(instance, by=self.membership)

    @extend_schema(request=s.BulkSerializer, responses=s.CountSerializer)
    @action(detail=False, methods=["post"])
    def bulk(self, request, company_id):
        serializer = s.BulkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        branch = self.one_branch(data.get("branch_id"))
        count = services.bulk_roster(
            self.company,
            by=self.membership,
            action=data["action"],
            week=data["week"],
            branch_id=branch.pk if branch else None,
            member_ids=data.get("member_ids"),
        )
        return Response({"count": count})

    @extend_schema(request=s.PublishSerializer, responses=s.CountSerializer)
    @action(detail=False, methods=["post"])
    def publish(self, request, company_id):
        serializer = s.PublishSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        branch = self.one_branch(data.get("branch_id"))
        count = services.publish_roster(
            self.company,
            by=self.membership,
            start=data["start"],
            end=data["end"],
            branch_id=branch.pk if branch else None,
        )
        return Response({"count": count})


class RosterView(ModuleOn, Scoped, OwnerAPIView):
    """One week of the roster for the grid: people, shifts (drafts and open shifts too),
    leave, holidays and coverage."""

    perm = VIEW

    @extend_schema(
        parameters=[
            OpenApiParameter("week", str, description="Any day of the week."),
            OpenApiParameter("branch", int),
        ],
        responses=s.RosterSerializer,
    )
    def get(self, request, company_id):
        week = _day(request.query_params.get("week"), "week", clock.today(self.company))
        branch = self.one_branch(request.query_params.get("branch"))
        data = queries.roster(
            self.company,
            week,
            branch_ids=self.branch_scope,
            branch_id=branch.pk if branch else None,
        )
        data["templates"] = s.TemplateSerializer(
            ShiftTemplate.objects.for_company(self.company).filter(is_active=True), many=True
        ).data
        return Response(data)


# Swaps and corrections ------------------------------------------------------------------


class SwapViewSet(ModuleOn, Scoped, mixins.ListModelMixin, OwnerViewSet):
    """Swaps, covers and open-shift claims; the accepted ones wait for a decision."""

    perm = MANAGE
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ShiftSwap.objects.none()
        rows = ShiftSwap.objects.for_company(self.company)
        rows = scope.restrict(rows, self.branch_scope, field="shift__branch")
        return rows.select_related(
            "shift__branch",
            "shift__position",
            "shift__company",
            "other_shift__branch",
            "other_shift__position",
            "requested_by__user",
            "accepted_by__user",
            "target__user",
        )

    @extend_schema(
        parameters=[
            OpenApiParameter("status", str, enum=[*ShiftSwap.Status.values, "open", "all"])
        ],
        responses=s.SwapOutSerializer(many=True),
    )
    def list(self, request, *args, **kwargs):
        wanted = request.query_params.get("status") or ShiftSwap.Status.ACCEPTED
        rows = self.get_queryset()
        if wanted == "open":
            rows = rows.filter(status__in=ShiftSwap.OPEN_STATUSES)
        elif wanted != "all":
            rows = rows.filter(status=wanted)
        rows = rows.order_by(
            "expires_at" if wanted in ("open", "accepted", "requested") else "-created_at"
        )
        page = self.paginate_queryset(rows)
        return self.get_paginated_response(
            [queries.swap_payload(swap, self.company) for swap in page]
        )

    @extend_schema(request=None, responses=s.SwapOutSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request, company_id, pk):
        swap = services.decide_swap(self.get_object(), by=self.membership, approve=True)
        return Response(queries.swap_payload(swap, self.company))

    @extend_schema(request=s.ReasonSerializer, responses=s.SwapOutSerializer)
    @action(detail=True, methods=["post"])
    def reject(self, request, company_id, pk):
        serializer = s.ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        swap = services.decide_swap(
            self.get_object(),
            by=self.membership,
            approve=False,
            reason=serializer.validated_data["reason"],
        )
        return Response(queries.swap_payload(swap, self.company))


class CorrectionViewSet(ModuleOn, Scoped, mixins.ListModelMixin, OwnerViewSet):
    """ "I forgot to check in" requests."""

    perm = MANAGE
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AttendanceCorrection.objects.none()
        rows = AttendanceCorrection.objects.for_company(self.company)
        allowed = self.branch_scope
        if allowed is not None:
            from django.db.models import Q

            rows = rows.filter(
                Q(record__branch_id__in=allowed)
                | Q(record__isnull=True, membership__home_branch_id__in=allowed)
            )
        return rows.select_related(
            "membership__user",
            "membership__position",
            "membership__home_branch",
            "record__branch",
            "record__shift",
        )

    @extend_schema(
        parameters=[
            OpenApiParameter("status", str, enum=[*AttendanceCorrection.Status.values, "all"])
        ],
        responses=s.CorrectionOutSerializer(many=True),
    )
    def list(self, request, *args, **kwargs):
        wanted = request.query_params.get("status") or AttendanceCorrection.Status.PENDING
        rows = self.get_queryset()
        if wanted != "all":
            rows = rows.filter(status=wanted)
        rows = rows.order_by("created_at" if wanted == "pending" else "-decided_at", "pk")
        page = self.paginate_queryset(rows)
        return self.get_paginated_response(
            [queries.correction_payload(correction, self.company) for correction in page]
        )

    @extend_schema(request=s.DecisionSerializer, responses=s.CorrectionOutSerializer)
    @action(detail=True, methods=["post"])
    def decide(self, request, company_id, pk):
        serializer = s.DecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correction = services.decide_correction(
            self.get_object(), by=self.membership, **serializer.validated_data
        )
        return Response(queries.correction_payload(correction, self.company))
