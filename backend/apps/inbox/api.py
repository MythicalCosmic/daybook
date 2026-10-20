"""Employee (mini app) endpoints of the inbox; routed in `urls.py`."""

from drf_spectacular.utils import extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.inbox import queries, services
from apps.inbox.serializers import MarkReadSerializer, NotificationSerializer, UpdatedSerializer
from apps.members.api import IsCompanyMember


class EmployeeInboxView(ListAPIView):
    """My notifications in this company, newest first."""

    permission_classes = (IsAuthenticated, IsCompanyMember)
    serializer_class = NotificationSerializer

    def get_queryset(self):
        return queries.inbox(self.membership)


class EmployeeMarkReadView(APIView):
    """Mark some (`ids`) or all (`all: true`) of my notifications read."""

    permission_classes = (IsAuthenticated, IsCompanyMember)

    @extend_schema(request=MarkReadSerializer, responses=UpdatedSerializer)
    def post(self, request, company_id):
        serializer = MarkReadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        count = services.mark_read(
            self.membership,
            ids=serializer.validated_data.get("ids", []),
            everything=serializer.validated_data["all"],
        )
        return Response({"updated": count})
