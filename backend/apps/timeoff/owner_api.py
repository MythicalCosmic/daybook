"""Owner dashboard endpoints of time off and holidays; routed in `owner_urls.py`.

    GET   time-off/?status=&from=&to=&member=&branch=&q=   requests and time off (paginated)
    GET   time-off/{id}/                                    one, with its sick note link
    POST  time-off/{id}/approve/ · reject/                  decide a request
    POST  time-off/record/                                  record time off for someone
    POST  time-off/{id}/revoke/   {reason, from_day?}       take back approved time off
    GET   time-off/calendar/?month=YYYY-MM                  bars per person, and holidays
    GET   time-off/stats/                                   the numbers above the page
    CRUD  holidays/?year=  ·  POST holidays/public/ {year}  company holidays

Everything needs `time_off.approve`; people are limited to the caller's branch scope.
"""

from datetime import date, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Case, IntegerField, Q, Value, When
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
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.console.base import OwnerViewSet
from apps.core.files import PrivateFileSerializerField
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import branch_ref, person_ref
from apps.timeoff import queries, services
from apps.timeoff.models import Holiday, TimeOff

PULSE_KEYS = ("timeoff.pending", "timeoff.time_off")


class PersonRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    photo_url = serializers.CharField(allow_null=True)


class BranchRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    code = serializers.CharField()


class OwnerTimeOffSerializer(serializers.ModelSerializer):
    member = serializers.SerializerMethodField()
    position = serializers.SerializerMethodField()
    home_branch = serializers.SerializerMethodField()
    days = serializers.IntegerField(read_only=True)
    decided_by = serializers.SerializerMethodField()
    recorded_by = serializers.SerializerMethodField()
    revoked_by = serializers.SerializerMethodField()
    attachment = PrivateFileSerializerField(check="timeoff.attachment", allow_null=True)
    can_decide = serializers.SerializerMethodField()
    can_revoke = serializers.SerializerMethodField()

    class Meta:
        model = TimeOff
        fields = (
            "id",
            "member",
            "position",
            "home_branch",
            "first_day",
            "last_day",
            "days",
            "reason",
            "status",
            "created_at",
            "decided_at",
            "decided_by",
            "recorded_by",
            "revoked_at",
            "revoked_by",
            "revoke_reason",
            "attachment",
            "can_decide",
            "can_revoke",
        )
        read_only_fields = fields

    @extend_schema_field(PersonRefSerializer)
    def get_member(self, row: TimeOff) -> dict:
        return person_ref(row.membership)

    def get_position(self, row: TimeOff) -> str | None:
        return row.membership.position.name if row.membership.position_id else None

    @extend_schema_field(BranchRefSerializer(allow_null=True))
    def get_home_branch(self, row: TimeOff) -> dict | None:
        return branch_ref(row.membership.home_branch)

    def get_decided_by(self, row: TimeOff) -> str | None:
        return row.decided_by.get_full_name() if row.decided_by else None

    @extend_schema_field(PersonRefSerializer(allow_null=True))
    def get_recorded_by(self, row: TimeOff) -> dict | None:
        return person_ref(row.recorded_by)

    def get_revoked_by(self, row: TimeOff) -> str | None:
        return row.revoked_by.get_full_name() if row.revoked_by else None

    def get_can_decide(self, row: TimeOff) -> bool:
        viewer = self.context["membership"]
        return row.status == TimeOff.Status.PENDING and row.membership_id != viewer.pk

    def get_can_revoke(self, row: TimeOff) -> bool:
        today = self.context.get("today") or timezone.localdate()
        return row.status == TimeOff.Status.APPROVED and row.last_day >= today - timedelta(
            days=services.MAX_RECORD_DAYS
        )


class RecordSerializer(serializers.Serializer):
    member_id = serializers.IntegerField()
    first_day = serializers.DateField()
    last_day = serializers.DateField()
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    attachment = serializers.FileField(required=False, allow_null=True)


class RevokeSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300)
    from_day = serializers.DateField(required=False, allow_null=True)


class CalendarItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    first_day = serializers.DateField()
    last_day = serializers.DateField()
    status = serializers.ChoiceField(TimeOff.Status.choices)
    reason = serializers.CharField()
    recorded = serializers.BooleanField()
    days = serializers.IntegerField()


class CalendarRowSerializer(serializers.Serializer):
    member = PersonRefSerializer()
    position = serializers.CharField(allow_null=True)
    home_branch = BranchRefSerializer(allow_null=True)
    items = CalendarItemSerializer(many=True)


class HolidaySerializer(serializers.ModelSerializer):
    class Meta:
        model = Holiday
        fields = ("id", "date", "name")
        read_only_fields = ("id",)


class TimeOffViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, OwnerViewSet):
    """Requests and time off of the people you manage, and the actions on them."""

    perm = Perm.TIME_OFF_APPROVE
    serializer_class = OwnerTimeOffSerializer
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return TimeOff.objects.none()
        rows = queries.visible(self.membership).select_related(
            "membership__user",
            "membership__position",
            "membership__home_branch",
            "decided_by",
            "revoked_by",
            "recorded_by__user",
        )
        if self.action != "list":
            return rows
        params = self.request.query_params
        statuses = [s for s in params.getlist("status") if s in TimeOff.Status.values]
        if statuses:
            rows = rows.filter(status__in=statuses)
        start, end = _day(params, "from"), _day(params, "to")
        if start:
            rows = rows.filter(last_day__gte=start)
        if end:
            rows = rows.filter(first_day__lte=end)
        if member := params.get("member"):
            rows = rows.filter(membership_id=_int(member, "member"))
        branches = _ints(params.getlist("branch"))
        if branches:
            allowed = scope.branch_ids(self.membership)
            if allowed is not None:
                branches = [b for b in branches if b in allowed]
            in_branches = Membership.objects.filter(
                company=self.company, branches__in=branches
            ).values("pk")
            rows = rows.filter(membership__in=in_branches)
        if q := params.get("q", "").strip():
            for word in q.split()[:3]:
                rows = rows.filter(
                    Q(membership__first_name__icontains=word)
                    | Q(membership__last_name__icontains=word)
                    | Q(reason__icontains=word)
                )
        ordering = params.get("ordering") or "-first_day"
        allowed_orderings = {"first_day", "-first_day", "created_at", "-created_at"}
        if ordering == "pending_first":
            rows = rows.annotate(
                waiting=Case(
                    When(status=TimeOff.Status.PENDING, then=Value(0)),
                    default=Value(1),
                    output_field=IntegerField(),
                )
            ).order_by("waiting", "first_day")
        else:
            rows = rows.order_by(ordering if ordering in allowed_orderings else "-first_day", "-pk")
        return rows

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if hasattr(self, "company"):
            context["today"] = _today(self.company)
        return context

    @extend_schema(
        parameters=[
            OpenApiParameter("status", str, many=True),
            OpenApiParameter("from", date),
            OpenApiParameter("to", date),
            OpenApiParameter("member", int),
            OpenApiParameter("branch", int, many=True),
            OpenApiParameter("q", str),
            OpenApiParameter(
                "ordering", str, description="first_day, -first_day, created_at, pending_first"
            ),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=None, responses=OwnerTimeOffSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request, company_id, pk):
        return self._decide(approve=True)

    @extend_schema(request=None, responses=OwnerTimeOffSerializer)
    @action(detail=True, methods=["post"])
    def reject(self, request, company_id, pk):
        return self._decide(approve=False)

    def _decide(self, *, approve: bool) -> Response:
        time_off = self.get_object()
        services.decide(time_off.pk, approve, by=self.membership.user)
        self.bump(*PULSE_KEYS)
        return Response(self.get_serializer(self.get_queryset().get(pk=time_off.pk)).data)

    @extend_schema(request=RecordSerializer, responses={201: OwnerTimeOffSerializer})
    @action(detail=False, methods=["post"])
    def record(self, request, company_id):
        serializer = RecordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        member = (
            Membership.objects.for_company(self.company)
            .filter(pk=data["member_id"])
            .select_related("company", "user")
            .first()
        )
        if member is None or not _sees(self.membership, member):
            raise ValidationError({"member_id": [_("Pick someone from your team.")]})
        time_off = services.record_time_off(
            member,
            by=self.membership,
            first_day=data["first_day"],
            last_day=data["last_day"],
            reason=data.get("reason", ""),
            attachment=data.get("attachment"),
        )
        self.bump(*PULSE_KEYS)
        fresh = self.get_queryset().get(pk=time_off.pk)
        return Response(self.get_serializer(fresh).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=RevokeSerializer, responses=OwnerTimeOffSerializer)
    @action(detail=True, methods=["post"])
    def revoke(self, request, company_id, pk):
        time_off = self.get_object()
        serializer = RevokeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.revoke(
            time_off,
            by=self.membership,
            reason=serializer.validated_data["reason"],
            from_day=serializer.validated_data.get("from_day"),
        )
        self.bump(*PULSE_KEYS)
        return Response(self.get_serializer(self.get_queryset().get(pk=time_off.pk)).data)

    @extend_schema(
        parameters=[
            OpenApiParameter("month", str, description="YYYY-MM; this month by default"),
            OpenApiParameter("branch", int, many=True),
            OpenApiParameter("position", int, many=True),
            OpenApiParameter("everyone", bool, description="Also people without time off"),
        ],
        responses=inline_serializer(
            "TimeoffCalendar",
            {
                "month": serializers.CharField(),
                "from": serializers.DateField(),
                "to": serializers.DateField(),
                "today": serializers.DateField(),
                "holidays": HolidaySerializer(many=True),
                "workdays": serializers.ListField(child=serializers.IntegerField()),
                "rows": CalendarRowSerializer(many=True),
            },
        ),
    )
    @action(detail=False, methods=["get"])
    def calendar(self, request, company_id):
        params = request.query_params
        today = _today(self.company)
        start = _month(params.get("month"), today)
        end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        branch_scope = scope.branch_ids(self.membership)
        wanted = _ints(params.getlist("branch"))
        if wanted:
            branch_scope = [b for b in wanted if branch_scope is None or b in branch_scope]
        rows = queries.calendar(
            self.company,
            start,
            end,
            branch_ids=branch_scope,
            include_everyone=params.get("everyone") in ("1", "true"),
            position_ids=_ints(params.getlist("position")) or None,
        )
        holidays = queries.holidays_between(self.company, start, end)
        return Response(
            {
                "month": start.strftime("%Y-%m"),
                "from": start.isoformat(),
                "to": end.isoformat(),
                "today": today.isoformat(),
                "holidays": HolidaySerializer(holidays, many=True).data,
                "workdays": list(self.company.workdays or []),
                "rows": rows,
            }
        )

    @extend_schema(
        responses=inline_serializer(
            "TimeoffStats",
            {
                "pending": serializers.IntegerField(),
                "off_today": serializers.IntegerField(),
                "off_this_week": serializers.IntegerField(),
                "days_this_month": serializers.IntegerField(),
                "next_holiday": HolidaySerializer(allow_null=True),
            },
        )
    )
    @action(detail=False, methods=["get"])
    def stats(self, request, company_id):
        return Response(queries.stats(self.membership, _today(self.company)))


class HolidayViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    OwnerViewSet,
):
    """The company's holidays: no daily tasks or reminders, never counted as leave."""

    perm = Perm.TIME_OFF_APPROVE
    serializer_class = HolidaySerializer
    pagination_class = None
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Holiday.objects.none()
        rows = Holiday.objects.for_company(self.company).order_by("date")
        year = self.request.query_params.get("year")
        if self.action == "list" and year:
            rows = rows.filter(date__year=_int(year, "year"))
        return rows

    @extend_schema(parameters=[OpenApiParameter("year", int)])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.instance = services.create_holiday(
            self.company, by=self.membership, **serializer.validated_data
        )
        self.bump("timeoff.holidays")

    def perform_update(self, serializer):
        serializer.instance = services.update_holiday(
            serializer.instance, by=self.membership, **serializer.validated_data
        )
        self.bump("timeoff.holidays")

    def perform_destroy(self, instance):
        services.delete_holiday(instance, by=self.membership)
        self.bump("timeoff.holidays")

    @extend_schema(
        request=inline_serializer("TimeoffPublicHolidays", {"year": serializers.IntegerField()}),
        responses={201: HolidaySerializer(many=True)},
    )
    @action(detail=False, methods=["post"])
    def public(self, request, company_id):
        """Add Uzbekistan's fixed public holidays of a year that are missing."""
        year = _int(str(request.data.get("year", "")), "year")
        added = services.add_public_holidays(self.company, by=self.membership, year=year)
        self.bump("timeoff.holidays")
        return Response(HolidaySerializer(added, many=True).data, status=status.HTTP_201_CREATED)


def _sees(viewer: Membership, member: Membership) -> bool:
    branches = scope.branch_ids(viewer)
    if branches is None or viewer.pk == member.pk:
        return True
    return member.branches.filter(pk__in=branches).exists()


def _today(company) -> date:
    return timezone.localdate(timezone=ZoneInfo(company.timezone))


def _day(params, key: str) -> date | None:
    text = params.get(key)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValidationError({key: [_("Use a date like 2026-10-20.")]}) from None


def _month(text: str | None, today: date) -> date:
    if not text:
        return today.replace(day=1)
    try:
        year, month = (int(part) for part in text.split("-"))
        return date(year, month, 1)
    except ValueError:
        raise ValidationError({"month": [_("Use a month like 2026-10.")]}) from None


def _int(text: str, key: str) -> int:
    try:
        return int(text)
    except TypeError, ValueError:
        raise ValidationError({key: [_("Must be a whole number.")]}) from None


def _ints(values) -> list[int]:
    found = []
    for value in values:
        for part in str(value).split(","):
            if part.strip().isdigit():
                found.append(int(part))
    return found
