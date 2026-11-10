"""Employee (mini app) endpoints of fixed assets, routed in `urls.py` under
`/api/v1/companies/<id>/assets/…`: "Jihozlarim" (My equipment).

    GET   assets/mine/                     what I hold now, newest first
    POST  assets/mine/{id}/acknowledge/    "I have it", in the state written down

Only the person's own items; never a value. While the assets module is off the endpoints
answer 403.
"""

from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.assets import queries, services
from apps.assets.models import AssetAssignment, AssetFile
from apps.core.files import signed_url
from apps.members.api import IsCompanyMember
from apps.members.models import Membership


class AssetsOn(BasePermission):
    def has_permission(self, request, view):
        if not view.membership.company.has_feature("assets"):
            raise PermissionDenied(_("Assets aren't switched on for this company."))
        return True


class MineItemSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="The hand-out (what is acknowledged).")
    asset_id = serializers.IntegerField()
    number = serializers.CharField()
    name = serializers.CharField()
    model = serializers.CharField()
    serial = serializers.CharField()
    category = serializers.CharField()
    icon = serializers.CharField()
    branch = serializers.CharField(allow_null=True)
    issued_on = serializers.DateField()
    condition = serializers.CharField()
    note = serializers.CharField()
    acknowledged_at = serializers.DateTimeField(allow_null=True)
    photo_url = serializers.CharField(
        allow_null=True,
        help_text="The photo taken when it was given to them, else a photo of the asset.",
    )

    class Meta:
        ref_name = "AssetsMineItem"


def _photo_url(assignment: AssetAssignment, user) -> str | None:
    asset = assignment.asset
    if assignment.photo_out:
        return signed_url(
            assignment.photo_out,
            user=user,
            company_id=asset.company_id,
            check=f"assets.handout:{assignment.pk}",
        )
    photo = next(
        (row for row in asset.files.all() if row.kind == AssetFile.Kind.PHOTO and row.file), None
    )
    if photo is None:
        return None
    return signed_url(
        photo.file, user=user, company_id=asset.company_id, check=f"assets.file:{photo.pk}"
    )


def item_of(assignment: AssetAssignment, user) -> dict:
    asset = assignment.asset
    return {
        "id": assignment.pk,
        "asset_id": asset.pk,
        "number": asset.number,
        "name": asset.name,
        "model": asset.model,
        "serial": asset.serial,
        "category": asset.category.name,
        "icon": asset.category.icon,
        "branch": asset.branch.name if asset.branch_id else None,
        "issued_on": assignment.issued_on,
        "condition": assignment.condition_out or asset.condition,
        "note": assignment.note_out,
        "acknowledged_at": assignment.acknowledged_at,
        "photo_url": _photo_url(assignment, user),
    }


class MemberView(APIView):
    permission_classes = (IsAuthenticated, IsCompanyMember, AssetsOn)
    membership: Membership


class MineView(MemberView):
    @extend_schema(responses=MineItemSerializer(many=True))
    def get(self, request, company_id):
        rows = queries.mine(self.membership)
        return Response(
            MineItemSerializer([item_of(row, request.user) for row in rows], many=True).data
        )


class AcknowledgeView(MemberView):
    @extend_schema(request=None, responses=MineItemSerializer)
    def post(self, request, company_id, pk):
        assignment = (
            AssetAssignment.objects.filter(
                company=self.membership.company,
                membership=self.membership,
                returned_on__isnull=True,
                pk=pk,
            )
            .select_related("asset__category", "asset__branch")
            .first()
        )
        if assignment is None:
            raise NotFound
        assignment = services.acknowledge(assignment, by=self.membership)
        assignment = (
            AssetAssignment.objects.select_related("asset__category", "asset__branch")
            .prefetch_related("asset__files")
            .get(pk=assignment.pk)
        )
        return Response(MineItemSerializer(item_of(assignment, request.user)).data)
