"""Owner dashboard endpoints of the audit log; routed in `owner_urls.py`.

    GET audit/records/?target_type=task&target_id=12   the History tab of any record

Like every owner endpoint it accepts only dashboard tokens and needs an approved membership
with dashboard.access in the URL's company (`apps.console.base.OwnerMixin`).
"""

from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from rest_framework import serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.generics import ListAPIView

from apps.audit import queries, registry
from apps.audit.models import AuditLog
from apps.console.base import OwnerMixin
from apps.members.models import Membership
from apps.members.permissions import Perm


class ActorSerializer(serializers.Serializer):
    id = serializers.IntegerField(
        allow_null=True, help_text="Their membership, when they have one."
    )
    name = serializers.CharField()


class AuditRecordSerializer(serializers.ModelSerializer):
    action_label = serializers.CharField()
    actor = serializers.SerializerMethodField()
    details = serializers.JSONField(help_text="Secret values are always shown as •••.")

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

    @extend_schema_field(ActorSerializer(allow_null=True))
    def get_actor(self, row: AuditLog) -> dict | None:
        if row.actor_id is None:
            return None
        member = self.context.get("members", {}).get(row.actor_id)
        name = (member.full_name if member else "") or str(row.actor)
        return {"id": member.pk if member else None, "name": name}


class RecordHistoryView(OwnerMixin, ListAPIView):
    """The History tab of one record: its audit rows the caller may see, newest first.

    Needs audit.view, or the permission the record's app registered for its history (for
    example tasks.view_all for a task). Rows touching salaries or IDs are left out unless the
    caller holds the permission they need.
    """

    serializer_class = AuditRecordSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AuditLog.objects.none()
        member = self.membership
        target_type, target_id = self._target()
        if not member.has_perm(Perm.AUDIT_VIEW):
            history = registry.target(target_type)
            if history is None or not member.has_perm(history.perm):
                self.permission_denied(self.request)
            if history.check is not None and not history.check(member, target_id):
                raise NotFound
        return queries.events(member, target_type=target_type, target_id=target_id)

    def get_serializer(self, *args, **kwargs):
        rows = args[0] if args else None
        if isinstance(rows, list) and hasattr(self, "membership"):
            # Actors are users; show them as members of this company where they are one.
            actor_ids = {row.actor_id for row in rows if row.actor_id is not None}
            members = Membership.objects.for_company(self.membership.company_id).filter(
                user_id__in=actor_ids
            )
            kwargs.setdefault("context", self.get_serializer_context())
            kwargs["context"]["members"] = {member.user_id: member for member in members}
        return super().get_serializer(*args, **kwargs)

    @extend_schema(
        parameters=[
            OpenApiParameter("target_type", required=True, description="e.g. task, membership"),
            OpenApiParameter("target_id", int, required=True),
        ],
        responses=AuditRecordSerializer(many=True),
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def _target(self) -> tuple[str, int]:
        params = self.request.query_params
        target_type = params.get("target_type", "").strip().lower()
        target_id = params.get("target_id", "")
        errors = {}
        if not target_type:
            errors["target_type"] = [_("This field is required.")]
        if not target_id.isdigit():
            errors["target_id"] = [_("A record id is required.")]
        if errors:
            raise ValidationError(errors)
        return target_type, int(target_id)
