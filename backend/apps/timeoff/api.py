from datetime import timedelta
from zoneinfo import ZoneInfo

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.members.api import IsCompanyMember
from apps.timeoff import services
from apps.timeoff.models import Holiday, TimeOff

# How long finished time off stays in someone's list.
RECENT = timedelta(days=30)


class TimeOffSerializer(serializers.ModelSerializer):
    days = serializers.IntegerField(read_only=True)
    decided_by = serializers.CharField(
        source="decided_by.get_full_name", read_only=True, allow_null=True, default=None
    )

    class Meta:
        model = TimeOff
        fields = (
            "id",
            "first_day",
            "last_day",
            "reason",
            "status",
            "days",
            "decided_by",
            "created_at",
        )
        read_only_fields = ("id", "status", "days", "decided_by", "created_at")


class TimeOffViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    """The signed-in member's own time off: upcoming requests and the last month's."""

    permission_classes = (IsAuthenticated, IsCompanyMember)
    serializer_class = TimeOffSerializer
    pagination_class = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return TimeOff.objects.none()
        today = timezone.localdate(timezone=ZoneInfo(self.membership.company.timezone))
        return (
            TimeOff.objects.filter(membership=self.membership, last_day__gte=today - RECENT)
            .select_related("decided_by")
            .order_by("first_day")
        )

    def create(self, request, company_id):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        time_off = services.request_time_off(self.membership, **serializer.validated_data)
        return Response(self.get_serializer(time_off).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def cancel(self, request, company_id, pk):
        time_off = services.cancel(
            get_object_or_404(self.get_queryset(), pk=pk), by=self.membership
        )
        return Response(self.get_serializer(time_off).data)


class HolidaySerializer(serializers.ModelSerializer):
    class Meta:
        model = Holiday
        fields = ("id", "date", "name")
        read_only_fields = fields


class HolidayListView(generics.ListAPIView):
    """The company's coming holidays: no daily tasks and no reminders on those days."""

    permission_classes = (IsAuthenticated, IsCompanyMember)
    serializer_class = HolidaySerializer
    pagination_class = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Holiday.objects.none()
        company = self.membership.company
        today = timezone.localdate(timezone=ZoneInfo(company.timezone))
        return Holiday.objects.for_company(company).filter(date__gte=today)[:20]
