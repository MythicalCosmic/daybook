"""Owner dashboard endpoints of exports: `exports/`, `exports/{id}/`, `exports/kinds/`."""

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from drf_spectacular.utils import extend_schema, extend_schema_field, inline_serializer
from rest_framework import mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from apps.console import compat
from apps.console.base import OwnerViewSet
from apps.exports import build, housekeeping, services
from apps.exports.models import Export
from apps.exports.registry import COLUMN_KINDS, get_exporter
from apps.members.permissions import Perm


def file_check_kind(export: Export) -> str:
    return f"exports.export:{export.pk}"


class ExportSerializer(serializers.ModelSerializer):
    label = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()
    file_name = serializers.SerializerMethodField()
    expires_at = serializers.SerializerMethodField()

    class Meta:
        model = Export
        fields = (
            "id",
            "kind",
            "label",
            "format",
            "params",
            "status",
            "rows",
            "error",
            "deliver_telegram",
            "sensitive",
            "created_at",
            "finished_at",
            "expires_at",
            "file_name",
            "file_url",
        )
        read_only_fields = fields

    def get_label(self, export: Export) -> str:
        exporter = get_exporter(export.kind)
        return str(exporter.label) if exporter else export.kind

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_file_url(self, export: Export) -> str | None:
        """A signed link valid for 10 minutes, checked again when used."""
        if export.status != Export.Status.READY or not export.file:
            return None
        return compat.signed_url(
            export.file,
            user=self.context["request"].user,
            company_id=export.company_id,
            check=file_check_kind(export),
        )

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_file_name(self, export: Export) -> str | None:
        return build.download_name(export) if export.file else None

    @extend_schema_field(serializers.DateTimeField())
    def get_expires_at(self, export: Export) -> str:
        return serializers.DateTimeField().to_representation(export.created_at + housekeeping.KEEP)


class ExportRequestSerializer(serializers.Serializer):
    kind = serializers.CharField(max_length=48)
    format = serializers.ChoiceField(Export.Format.choices)
    params = serializers.DictField(required=False, default=dict)
    deliver_telegram = serializers.BooleanField(required=False, default=False)


class ColumnSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    kind = serializers.ChoiceField(COLUMN_KINDS)


class ExporterSerializer(serializers.Serializer):
    kind = serializers.CharField()
    label = serializers.CharField()
    sensitive = serializers.BooleanField()
    formats = serializers.ListField(child=serializers.CharField())
    columns = ColumnSerializer(many=True)


class ExportViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, OwnerViewSet
):
    """Your exports in this company (kept 7 days). Creating one needs `data.export` and the
    exporter's own permission; the file is built in the background (poll the detail)."""

    perm = Perm.DATA_EXPORT
    serializer_class = ExportSerializer
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        return Export.objects.filter(requested_by=self.membership).order_by("-created_at", "-pk")

    def get_throttles(self):
        if self.action == "create":
            self.throttle_scope = "export_create"
            return [ScopedRateThrottle()]
        return super().get_throttles()

    @extend_schema(
        request=ExportRequestSerializer,
        responses={202: inline_serializer("ExportCreated", {"id": serializers.IntegerField()})},
    )
    def create(self, request, *args, **kwargs):
        serializer = ExportRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            export = services.request_export(
                self.membership,
                data["kind"],
                format=data["format"],
                params=data["params"],
                deliver_telegram=data["deliver_telegram"],
            )
        except DjangoPermissionDenied as exc:
            raise PermissionDenied(str(exc)) from exc
        self.bump(build.EXPORTS_PULSE)
        return Response({"id": export.pk}, status=status.HTTP_202_ACCEPTED)

    @extend_schema(responses=ExporterSerializer(many=True))
    @action(detail=False)
    def kinds(self, request, company_id):
        """What you may export here."""
        return Response(
            [
                {
                    "kind": exporter.key,
                    "label": str(exporter.label),
                    "sensitive": exporter.sensitive,
                    "formats": list(exporter.formats),
                    "columns": [
                        {"key": c.key, "label": str(c.label), "kind": c.kind}
                        for c in exporter.columns
                    ],
                }
                for exporter in services.available(self.membership)
            ]
        )
