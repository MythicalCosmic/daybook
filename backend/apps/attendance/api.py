"""Employee (mini app) endpoints of attendance; routed in `urls.py` under
`/api/v1/companies/<id>/attendance/…` (docs/PLAN-OWNER.md §4.9, prefix E).

Everything is the signed-in person's own (no permission needed), except the board, which
needs `attendance.view`. While the module is off the endpoints answer 403.
"""

from datetime import date, datetime, timedelta

from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.attendance import clock, queries, services
from apps.attendance import serializers as s
from apps.attendance.models import AttendanceCorrection, AttendanceRecord, ShiftSwap, WorkShift
from apps.members import scope
from apps.members.api import IsCompanyMember
from apps.members.models import Membership
from apps.members.permissions import Perm


class AttendanceOn(BasePermission):
    """After IsCompanyMember: the module must be switched on."""

    def has_permission(self, request, view):
        if not view.membership.company.has_feature("attendance"):
            raise PermissionDenied(_("Attendance isn't switched on for this company."))
        return True


class MemberView(APIView):
    permission_classes = (IsAuthenticated, IsCompanyMember, AttendanceOn)
    membership: Membership

    @property
    def company(self):
        return self.membership.company

    def context(self) -> dict:
        return {"company": self.company, "request": self.request}


def _day(value, name):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({name: [_("Give a day as YYYY-MM-DD.")]}) from exc


class TodayView(MemberView):
    """The check-in card: today's shift, the open or latest record, where to check in."""

    @extend_schema(responses=s.MyDaySerializer)
    def get(self, request, company_id):
        return Response(queries.my_day(self.membership))


class CheckInView(MemberView):
    """Check in with the location of the tap (and a selfie when the company asks)."""

    parser_classes = (JSONParser, MultiPartParser, FormParser)

    @extend_schema(
        request=s.CheckInSerializer,
        responses={201: s.CheckResultSerializer, 200: s.CheckResultSerializer},
    )
    def post(self, request, company_id):
        serializer = s.CheckInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = services.check_in(
            self.membership,
            lat=data.get("lat"),
            lng=data.get("lng"),
            accuracy=data.get("accuracy"),
            photo=data.get("photo"),
        )
        return Response(
            {
                "record": queries.record_payload(result.record, self.company),
                "created": result.created,
                "outside": result.outside,
                "distance_m": result.distance_m,
            },
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )


class CheckOutView(MemberView):
    @extend_schema(request=s.CheckOutSerializer, responses=s.CheckResultSerializer)
    def post(self, request, company_id):
        serializer = s.CheckOutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = services.check_out(
            self.membership, lat=data.get("lat"), lng=data.get("lng"), accuracy=data.get("accuracy")
        )
        return Response(
            {
                "record": queries.record_payload(result.record, self.company),
                "created": False,
                "outside": result.outside,
                "distance_m": result.distance_m,
            }
        )


class MonthView(MemberView):
    """My month: a coded day each and the totals."""

    @extend_schema(
        parameters=[OpenApiParameter("month", str, description="YYYY-MM")],
        responses=s.MyMonthSerializer,
    )
    def get(self, request, company_id):
        value = request.query_params.get("month")
        today = clock.today(self.company)
        try:
            month = datetime.strptime(value[:7], "%Y-%m").date() if value else today.replace(day=1)
        except ValueError as exc:
            raise ValidationError({"month": [_("Give a month as YYYY-MM.")]}) from exc
        return Response(queries.my_month(self.membership, month))


class ShiftsView(MemberView):
    """My published shifts in a period (two weeks from today by default)."""

    @extend_schema(
        parameters=[OpenApiParameter("from", str), OpenApiParameter("to", str)],
        responses=s.ShiftOutSerializer(many=True),
    )
    def get(self, request, company_id):
        today = clock.today(self.company)
        params = request.query_params
        start = _day(params["from"], "from") if params.get("from") else today
        end = _day(params["to"], "to") if params.get("to") else today + timedelta(days=20)
        if (end - start).days > 62:
            raise ValidationError({"to": [_("Pick at most two months.")]})
        shifts = queries.shifts_between(
            self.company, start, end, branch_ids=None, member_id=self.membership.pk, drafts=False
        )
        return Response([queries.shift_payload(shift, self.company) for shift in shifts])


class CorrectionsView(MemberView):
    """My correction requests, and a new one."""

    @extend_schema(responses=s.CorrectionOutSerializer(many=True))
    def get(self, request, company_id):
        rows = (
            AttendanceCorrection.objects.filter(membership=self.membership)
            .select_related(
                "membership__user",
                "membership__position",
                "membership__home_branch",
                "record__branch",
            )
            .order_by("-created_at")[:30]
        )
        return Response([queries.correction_payload(row, self.company) for row in rows])

    @extend_schema(
        request=s.CorrectionRequestSerializer, responses={201: s.CorrectionOutSerializer}
    )
    def post(self, request, company_id):
        serializer = s.CorrectionRequestSerializer(data=request.data, context=self.context())
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        record = None
        if data.get("record_id"):
            record = AttendanceRecord.objects.filter(
                membership=self.membership, pk=data["record_id"]
            ).first()
            if record is None:
                raise NotFound
        correction = services.request_correction(
            self.membership,
            date=data["date"],
            reason=data["reason"],
            check_in_at=data.get("check_in_at"),
            check_out_at=data.get("check_out_at"),
            record=record,
        )
        correction = AttendanceCorrection.objects.select_related(
            "membership__user", "membership__position", "membership__home_branch", "record__branch"
        ).get(pk=correction.pk)
        return Response(
            queries.correction_payload(correction, self.company), status=status.HTTP_201_CREATED
        )


def _swap_rows(rows, company) -> list[dict]:
    return [queries.swap_payload(swap, company) for swap in rows]


class SwapsView(MemberView):
    """My requests and the ones waiting for my answer; ask for cover or a swap."""

    @extend_schema(responses=s.MySwapsSerializer)
    def get(self, request, company_id):
        mine = queries.my_swaps(self.membership)[:30]
        return Response(
            {
                "mine": _swap_rows(mine, self.company),
                "requests": _swap_rows(queries.requests_for(self.membership), self.company),
            }
        )

    @extend_schema(request=s.SwapRequestSerializer, responses={201: s.SwapOutSerializer})
    def post(self, request, company_id):
        serializer = s.SwapRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        shift = (
            WorkShift.objects.filter(company=self.company, pk=data["shift_id"])
            .select_related("membership", "branch", "company")
            .first()
        )
        if shift is None:
            raise NotFound
        other = None
        if data.get("other_shift_id"):
            other = (
                WorkShift.objects.filter(company=self.company, pk=data["other_shift_id"])
                .select_related("membership", "branch", "company")
                .first()
            )
            if other is None:
                raise NotFound
        target = None
        if data.get("target_id"):
            target = Membership.objects.filter(
                company=self.company, pk=data["target_id"], status=Membership.Status.APPROVED
            ).first()
            if target is None:
                raise NotFound
        swap = services.request_swap(
            self.membership,
            shift=shift,
            kind=data["kind"],
            other_shift=other,
            target=target,
            note=data["note"],
        )
        return Response(
            queries.swap_payload(_load_swap(swap.pk), self.company), status=status.HTTP_201_CREATED
        )


def _load_swap(pk) -> ShiftSwap:
    return ShiftSwap.objects.select_related(
        "shift__branch",
        "shift__position",
        "shift__company",
        "other_shift__branch",
        "requested_by__user",
        "accepted_by__user",
        "target__user",
    ).get(pk=pk)


class SwapActionView(MemberView):
    """accept · decline · cancel one request."""

    ACTIONS = {
        "accept": services.accept_swap,
        "decline": services.decline_swap,
        "cancel": services.cancel_swap,
    }

    @extend_schema(request=None, responses=s.SwapOutSerializer)
    def post(self, request, company_id, pk, verb):
        if verb not in self.ACTIONS:
            raise NotFound
        swap = ShiftSwap.objects.filter(company=self.company, pk=pk).first()
        if swap is None:
            raise NotFound
        mine = self.membership.pk in (swap.requested_by_id, swap.target_id, swap.accepted_by_id)
        if not mine and not (verb == "accept" and swap.target_id is None):
            raise NotFound
        self.ACTIONS[verb](swap, by=self.membership)
        return Response(queries.swap_payload(_load_swap(swap.pk), self.company))


class CandidatesView(MemberView):
    """Who could cover one of my shifts, with their coming shifts I could swap for."""

    @extend_schema(
        parameters=[OpenApiParameter("shift_id", int, required=True)],
        responses=s.CandidateSerializer(many=True),
    )
    def get(self, request, company_id):
        try:
            shift_id = int(request.query_params.get("shift_id", ""))
        except ValueError as exc:
            raise ValidationError({"shift_id": [_("Pick one of your shifts.")]}) from exc
        shift = (
            WorkShift.objects.working()
            .filter(pk=shift_id, membership=self.membership)
            .select_related("company", "membership")
            .first()
        )
        if shift is None:
            raise NotFound
        people = list(queries.eligible_for(shift))
        horizon = timezone.now() + timedelta(days=21)
        theirs: dict[int, list] = {}
        for other in (
            WorkShift.objects.working()
            .filter(membership__in=people, starts_at__gt=timezone.now(), starts_at__lte=horizon)
            .select_related("branch", "position")
            .order_by("starts_at")
        ):
            if queries.is_eligible(other, self.membership, ignore_shift_ids=[shift.pk]):
                theirs.setdefault(other.membership_id, []).append(
                    queries.shift_payload(other, self.company)
                )
        return Response(
            [
                {"member": queries.person_card(member), "shifts": theirs.get(member.pk, [])[:6]}
                for member in people
            ]
        )


class OpenShiftsView(MemberView):
    """Open shifts I may claim."""

    @extend_schema(responses=s.OpenShiftSerializer(many=True))
    def get(self, request, company_id):
        shifts = queries.open_shifts_for(self.membership)
        return Response(
            [
                queries.shift_payload(shift, self.company) | {"claimed": bool(shift.claimed)}
                for shift in shifts
            ]
        )


class ClaimView(MemberView):
    @extend_schema(request=None, responses=s.SwapOutSerializer)
    def post(self, request, company_id, pk):
        shift = WorkShift.objects.filter(
            company=self.company, pk=pk, status=WorkShift.Status.OPEN
        ).first()
        if shift is None:
            raise NotFound
        swap = services.claim_open_shift(shift, by=self.membership)
        return Response(queries.swap_payload(_load_swap(swap.pk), self.company))


class BoardView(MemberView):
    """Who's in now (managers in the app)."""

    @extend_schema(responses=s.BoardSerializer)
    def get(self, request, company_id):
        if not self.membership.has_perm(Perm.ATTENDANCE_VIEW):
            raise PermissionDenied(_("You don't have permission to do this."))
        day = clock.today(self.company)
        return Response(
            queries.day_board(self.company, day, branch_ids=scope.branch_ids(self.membership))
        )
